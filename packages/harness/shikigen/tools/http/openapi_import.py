"""OpenAPI 导入预览和保存：转换已确认的请求子集，不访问网络。"""

import json
import re
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime

import yaml
from pydantic import ValidationError

from shikigen.contracts.http_requests import SCALAR_TYPES, schema_types
from shikigen.contracts.input_schema import DRAFT2020
from shikigen.contracts.tool_definitions import HttpToolDefinition
from shikigen.tools.http.openapi_auth import authentication_errors, security_options
from shikigen.tools.http.openapi_schema import (
  SUPPORTED_DIALECTS,
  OpenApiSchemas,
  inline_object,
)

METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


class OpenApiImportError(ValueError):
  code = "openapi_invalid"
  status = 422


class DocumentLoader(yaml.SafeLoader):
  def construct_mapping(self, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
      key = self.construct_object(key_node, deep=deep)
      if not isinstance(key, (str, int)) or isinstance(key, bool):
        raise OpenApiImportError("文档对象的键必须是字符串")
      key = str(key)
      if key in result:
        raise OpenApiImportError(f"文档存在重复字段：{key}")
      result[key] = self.construct_object(value_node, deep=deep)
    return result


def read_document(document: str) -> dict:
  try:
    data = yaml.load(document, Loader=DocumentLoader)
    # 排除 YAML 非 JSON 值、非有限数、循环别名；不展开引用或下载文档。
    data = json.loads(json.dumps(data, allow_nan=False))
  except (yaml.YAMLError, ValueError, TypeError, RecursionError) as error:
    raise OpenApiImportError(f"无法解析 JSON／YAML 文档：{error}") from None
  if not isinstance(data, dict):
    raise OpenApiImportError("请提供单份 OpenAPI 对象文档")
  if not re.fullmatch(r"3\.[01]\.\d+", str(data.get("openapi", ""))):
    raise OpenApiImportError("仅支持 OpenAPI 3.0.x／3.1.x，不支持 Swagger 2.0")
  if not isinstance(data.get("paths"), dict):
    raise OpenApiImportError("文档缺少 paths 对象")
  if not isinstance(data.get("info"), dict):
    raise OpenApiImportError("文档缺少 info 对象")
  if any(not isinstance(data["info"].get(key), str) for key in ("title", "version")):
    raise OpenApiImportError("info/title 和 info/version 必须是字符串")
  return data


def merged_parameters(
  schemas: OpenApiSchemas, path_item: dict, operation: dict
) -> list[dict]:
  merged = {}
  for label, parent in (("path", path_item), ("operation", operation)):
    parameters = parent.get("parameters", [])
    if not isinstance(parameters, list):
      raise ValueError(f"{label}/parameters：需要数组")
    seen = set()
    for index, value in enumerate(parameters):
      parameter = schemas.object(value, f"{label}/parameters/{index}")
      name, location = parameter.get("name"), parameter.get("in")
      if (
        not isinstance(name, str)
        or not name
        or location not in ("path", "query", "header")
      ):
        raise ValueError(
          f"{label}/parameters/{index}：仅支持有原名的 path/header/query 参数；"
          "cookie 未支持，请选择其他接口"
        )
      identity = (location, name.lower() if location == "header" else name)
      if identity in seen:
        raise ValueError(f"{label}/parameters：重复或冲突的参数 {location}.{name}")
      seen.add(identity)
      merged[identity] = parameter
  return list(merged.values())


def request_definition(
  schemas: OpenApiSchemas, path_item: dict, operation: dict
) -> dict:
  schema = {
    "$schema": DRAFT2020,
    "type": "object",
    "properties": {},
    "additionalProperties": False,
  }
  mappings = []
  required_groups = []
  for parameter in merged_parameters(schemas, path_item, operation):
    name, location = parameter["name"], parameter["in"]
    label = f"parameters/{location}/{name}"
    if "content" in parameter:
      raise ValueError(f"{label}/content：参数 content 未支持；请使用普通 schema 参数")
    if parameter.get("allowReserved", False) is not False:
      raise ValueError(
        f"{label}/allowReserved：特殊保留字符序列化未支持；请选择其他接口"
      )
    style = "form" if location == "query" else "simple"
    if parameter.get("style", style) != style:
      raise ValueError(f"{label}/style：仅支持 {style}；请改用受支持的序列化")
    if not isinstance(parameter.get("explode", location == "query"), bool):
      raise ValueError(f"{label}/explode：需要布尔值；请修正文档")
    required = parameter.get("required", False)
    if not isinstance(required, bool) or (location == "path" and not required):
      raise ValueError(f"{label}/required：路径参数必须显式为 true，其余须为布尔值")
    node = schemas.convert(parameter.get("schema"), label + "/schema")
    types = schema_types(node) - {"null"}
    if location == "query" and types == {"array"}:
      if not schema_types(node.get("items")) <= SCALAR_TYPES:
        raise ValueError(
          f"{label}/schema/items：query 数组仅支持非空标量元素；请选择其他接口"
        )
    elif not types or not types <= SCALAR_TYPES:
      raise ValueError(
        f"{label}/schema：{location} 仅支持普通标量，query 另支持标量数组；"
        "请选择其他接口"
      )
    for annotation in ("description", "example"):
      if annotation in parameter:
        node[annotation] = parameter[annotation]
    group_name = "headers" if location == "header" else location
    group = schema["properties"].setdefault(
      group_name,
      {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
      },
    )
    group["properties"][name] = node
    if required:
      group.setdefault("required", []).append(name)
      if group_name not in required_groups:
        required_groups.append(group_name)
    mappings.append(
      {
        "location": group_name,
        "input_name": name,
        "name": name,
        "style": parameter.get("style", "form" if location == "query" else "simple"),
        "explode": parameter.get("explode", location == "query"),
      }
    )
  if "requestBody" in operation:
    body = schemas.object(operation["requestBody"], "requestBody")
    content = inline_object(body.get("content"), "requestBody/content")
    if "application/json" not in content:
      raise ValueError(
        f"requestBody/content：仅支持 application/json，当前为 {', '.join(content)}；"
        "请选择 JSON 接口"
      )
    media = inline_object(
      content.get("application/json"), "requestBody/application/json"
    )
    if media.get("encoding"):
      raise ValueError("requestBody/encoding：不支持特殊请求体编码")
    schema["properties"]["body"] = schemas.convert(
      media.get("schema"), "requestBody/content/application~1json/schema"
    )
    for annotation in ("description",):
      if annotation in body:
        schema["properties"]["body"][annotation] = deepcopy(body[annotation])
    if "example" in media:
      schema["properties"]["body"]["example"] = deepcopy(media["example"])
    if not isinstance(body.get("required", False), bool):
      raise ValueError("requestBody/required：需要布尔值")
    if body.get("required"):
      required_groups.append("body")
  if required_groups:
    schema["required"] = required_groups
  return {"input_schema": schema, "parameters": mappings}


def output_preview(
  schemas: OpenApiSchemas, operation: dict
) -> tuple[dict | None, list[str]]:
  try:
    responses = inline_object(operation.get("responses", {}), "responses")
    success = [
      value for code, value in responses.items() if re.fullmatch(r"2\d\d", code)
    ]
    if not success or any(code.upper() == "2XX" for code in responses):
      raise ValueError("成功响应不是单一明确结构")
    success_schemas = []
    for value in success:
      response = schemas.object(value, "responses/success")
      content = inline_object(response.get("content"), "responses/success/content")
      if set(content) != {"application/json"}:
        raise ValueError("成功响应不是单一 application/json")
      media = inline_object(content["application/json"], "responses/application/json")
      success_schemas.append(schemas.convert(media.get("schema"), "responses/schema"))
    if any(schema != success_schemas[0] for schema in success_schemas[1:]):
      raise ValueError("成功响应存在多种不同结构")
    return {"$schema": DRAFT2020, **success_schemas[0]}, []
  except (ValueError, TypeError, AttributeError, RecursionError) as error:
    return None, [f"输出结构未声明：{error}；测试仍展示实际响应。"]


def preview_openapi(document: str) -> dict:
  parsed_document = read_document(document)
  operations = []
  for path, raw_path_item in parsed_document["paths"].items():
    if path.startswith("x-"):
      continue
    if not path.startswith("/") or not isinstance(raw_path_item, dict):
      raise OpenApiImportError(f"paths/{path}：需要以 / 开头的路径及对象")
    for method, raw_operation in raw_path_item.items():
      if method in {
        "summary",
        "description",
        "servers",
        "parameters",
      } or method.startswith("x-"):
        continue
      errors = []
      warnings = []
      configuration_errors = []
      definition = {
        "kind": "http",
        "method": method.upper(),
        "name": "",
        "display_name": "",
        "description": "",
        "url": "",
        "headers": {},
        "auth": [],
        "enabled": True,
        "timeout_seconds": 30,
        "input_schema": {
          "type": "object",
          "properties": {},
          "additionalProperties": False,
        },
        "parameters": [],
        "output_schema": None,
      }
      candidate = {
        "key": f"{method.upper()} {path}",
        "method": method.upper(),
        "path": path,
        "name_hint": f"{method}_{path}",
        "servers": [],
        "definition": definition,
        "errors": errors,
        "warnings": warnings,
        "configuration_errors": configuration_errors,
      }
      operations.append(candidate)
      schemas = OpenApiSchemas(parsed_document)
      definition["openapi_source"] = {
        "openapi": parsed_document["openapi"],
        "info": parsed_document["info"],
        "path": path,
        "method": method.upper(),
        "operation": raw_operation,
        "path_item": {
          key: value
          for key, value in raw_path_item.items()
          if key in ("summary", "description", "parameters", "servers", "$ref")
        },
        "references": schemas.references,
      }
      try:
        path_item = inline_object(raw_path_item, f"paths/{path}")
        operation = inline_object(raw_operation, candidate["key"])
        if method not in METHODS:
          raise ValueError(f"method：不支持 {method.upper()}")
        if "jsonSchemaDialect" in parsed_document and (
          not isinstance(parsed_document["jsonSchemaDialect"], str)
          or parsed_document["jsonSchemaDialect"] not in SUPPORTED_DIALECTS
        ):
          raise ValueError("jsonSchemaDialect：自定义方言尚未支持")
        name_hint = operation.get("operationId") or f"{method}_{path}"
        if not isinstance(name_hint, str):
          raise ValueError("operationId：需要字符串")
        candidate["name_hint"] = name_hint
        if any(
          not isinstance(operation.get(key, ""), str)
          for key in ("summary", "description")
        ):
          raise ValueError("summary 和 description：需要字符串")
        definition["display_name"] = operation.get("summary", "")
        definition["description"] = operation.get("description") or operation.get(
          "summary", ""
        )
        servers = operation.get(
          "servers", path_item.get("servers", parsed_document.get("servers", []))
        )
        if not isinstance(servers, list):
          raise ValueError("servers：需要数组")
        for server in servers:
          inline_object(server, "servers")
          if not isinstance(server.get("url"), str):
            raise ValueError("servers/url：需要字符串")
        candidate["servers"] = servers
        definition["url"] = (servers[0]["url"].rstrip("/") if servers else "") + path
        definition.update(request_definition(schemas, path_item, operation))
        if {
          mapping["name"]
          for mapping in definition["parameters"]
          if mapping["location"] == "path"
        } != set(re.findall(r"\{([^{}]+)\}", path)):
          raise ValueError(
            "parameters/path：路径占位符必须对应必填 path 参数；请补齐或修正映射"
          )
        output, output_warnings = output_preview(schemas, operation)
        definition["output_schema"] = output
        warnings.extend(output_warnings)
        definition["openapi_source"]["servers"] = servers
        now = datetime.now(UTC)
        preview_definition = {
          **definition,
          "id": "preview",
          "name": "preview",
          "display_name": "preview",
          "url": "https://openapi.invalid" + path,
          "created_at": now,
          "updated_at": now,
        }
        HttpToolDefinition.model_validate(preview_definition)
        options, security_source = security_options(schemas, operation)
        definition["openapi_source"].update(security_source)
        for option in options:
          if not option["errors"]:
            try:
              HttpToolDefinition.model_validate(
                {**preview_definition, "auth": option["auth"]}
              )
            except ValidationError as error:
              option["errors"].extend(
                f"security/{option['id']}：{item['msg']}；请修正认证目标或业务参数冲突"
                for item in error.errors(include_input=False)
              )
        candidate["security_options"] = options
        default_option = next(
          (option for option in options if not option["errors"]), None
        )
        candidate["security_option"] = default_option["id"] if default_option else None
        if default_option is None:
          raise ValueError(
            "；".join(reason for option in options for reason in option["errors"])
          )
        definition["auth"] = deepcopy(default_option["auth"])
        configuration_errors.extend(
          authentication_errors(default_option, definition["auth"])
        )
        try:
          HttpToolDefinition.validate_url(definition["url"])
          if servers and re.search(r"[{}]", servers[0]["url"]):
            raise ValueError("服务器地址变量需要补齐")
        except ValueError:
          configuration_errors.append(
            "请将服务器地址或变量补齐为有效的绝对 HTTP(S) 请求地址"
          )
        if not definition["display_name"]:
          configuration_errors.append("请补充页面名称")
        if not definition["description"]:
          configuration_errors.append("请补充用途说明")
      except (ValueError, TypeError, AttributeError, RecursionError) as error:
        if isinstance(error, ValidationError):
          errors.extend(
            f"{candidate['key']} {'/'.join(map(str, item['loc'])) or 'request'}："
            f"{item['msg']}；请修正此配置或取消选择"
            for item in error.errors(include_input=False)
          )
        else:
          errors.append(f"{candidate['key']} {error}；请修正文档或取消选择")
      warnings[:] = [f"{candidate['key']} {reason}" for reason in warnings]
      configuration_errors[:] = [
        f"{candidate['key']} {reason}" for reason in configuration_errors
      ]
  return {
    "openapi": parsed_document["openapi"],
    "title": parsed_document.get("info", {}).get("title", ""),
    "operations": operations,
  }


def selected_openapi_definitions(document: str, selections: list[dict]) -> list[dict]:
  candidates = {item["key"]: item for item in preview_openapi(document)["operations"]}
  keys = [item["operation_key"] for item in selections]
  if not keys or len(keys) != len(set(keys)):
    raise OpenApiImportError("请勾选不同的接口")
  definitions = []
  for item in selections:
    key = item["operation_key"]
    candidate = candidates.get(key)
    if candidate is None or candidate["errors"]:
      reason = "；".join(candidate["errors"]) if candidate else "不在当前文档中"
      raise OpenApiImportError(f"{key}：{reason}")
    definition = {
      **item["definition"],
      "openapi_source": candidate["definition"]["openapi_source"],
    }
    if definition.get("kind") != "http":
      raise OpenApiImportError(f"{key}：只能生成 HTTP 工具")
    selected_option = item.get("security_option") or candidate["security_option"]
    option = next(
      (
        option
        for option in candidate["security_options"]
        if option["id"] == selected_option
      ),
      None,
    )
    if option is None:
      raise OpenApiImportError(f"{key} security：请选择来源中的受支持认证方案")
    auth_errors = authentication_errors(option, definition.get("auth", []))
    if auth_errors:
      raise OpenApiImportError(f"{key}：{'；'.join(auth_errors)}")
    definition["openapi_source"] = {
      **definition["openapi_source"],
      "selected_security": selected_option,
    }
    url = definition.get("url")
    if isinstance(url, str):
      server_variables = {
        name
        for server in candidate["servers"]
        for name in re.findall(r"\{([^{}]+)\}", server["url"])
      }
      path_placeholders = Counter(re.findall(r"\{([^{}]+)\}", candidate["path"]))
      remaining = Counter(re.findall(r"\{([^{}]+)\}", url))
      if any(remaining[name] > path_placeholders[name] for name in server_variables):
        raise OpenApiImportError(f"{key}：请补齐服务器变量，不能作为业务路径参数保存")
    description = definition.get("description")
    if not isinstance(description, str) or not description.strip():
      raise OpenApiImportError(f"{key}：请补充用途说明")
    definitions.append(definition)
  return definitions
