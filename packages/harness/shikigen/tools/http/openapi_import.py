"""OpenAPI 基础导入：只转换明确支持的内联请求，不访问网络。"""

import json
import re
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime

import yaml
from pydantic import ValidationError

from shikigen.contracts.input_schema import DRAFT2020, SUPPORTED, validate_tool_schema
from shikigen.contracts.tool_definitions import HttpToolDefinition

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
  if any(
    not isinstance(data["info"].get(key), str) for key in ("title", "version")
  ):
    raise OpenApiImportError("info/title 和 info/version 必须是字符串")
  return data


def inline_object(value, path: str) -> dict:
  if not isinstance(value, dict):
    raise ValueError(f"{path}：需要对象结构")
  if "$ref" in value:
    raise ValueError(f"{path}/$ref：引用尚未支持，请使用内联定义")
  return value


def convert_schema(value, version: str, path: str) -> dict:
  source = inline_object(value, path)
  unsupported = set(source) - (SUPPORTED - {"$ref", "$defs", "definitions", "$schema"})
  if version.startswith("3.0."):
    unsupported -= {"nullable"}
  if unsupported:
    raise ValueError(f"{path}：尚不支持 {', '.join(sorted(unsupported))}")
  result = deepcopy(source)
  nullable = result.pop("nullable", False)
  if not isinstance(nullable, bool):
    raise ValueError(f"{path}/nullable：需要布尔值")
  if nullable:
    if not isinstance(result.get("type"), str):
      raise ValueError(f"{path}/nullable：需要明确的单一 type")
    result["type"] = [result["type"], "null"]
  if version.startswith("3.0."):
    for bound in ("minimum", "maximum"):
      exclusive = "exclusive" + bound.capitalize()
      if exclusive in result:
        flag = result.pop(exclusive)
        if not isinstance(flag, bool) or (flag and bound not in result):
          raise ValueError(f"{path}/{exclusive}：需要布尔值及对应范围")
        if flag:
          result[exclusive] = result.pop(bound)
  for key in ("properties", "patternProperties"):
    if key in result:
      if not isinstance(result[key], dict):
        raise ValueError(f"{path}/{key}：需要对象")
      result[key] = {
        name: convert_schema(child, version, f"{path}/{key}/{name}")
        for name, child in result[key].items()
      }
  for key in ("items", "additionalProperties", "propertyNames"):
    if key in result and not isinstance(result[key], bool):
      result[key] = convert_schema(result[key], version, f"{path}/{key}")
  # 使用相同的输入子集检查，输出预填也仅接受可明确理解的简单结构。
  validate_tool_schema(
    {"$schema": DRAFT2020, "type": "object", "properties": {"value": result}},
    inputs=True,
  )
  return result


def merged_parameters(path_item: dict, operation: dict) -> list[dict]:
  merged = {}
  for label, parent in (("path", path_item), ("operation", operation)):
    parameters = parent.get("parameters", [])
    if not isinstance(parameters, list):
      raise ValueError(f"{label}/parameters：需要数组")
    seen = set()
    for index, value in enumerate(parameters):
      parameter = inline_object(value, f"{label}/parameters/{index}")
      name, location = parameter.get("name"), parameter.get("in")
      if (
        not isinstance(name, str)
        or not name
        or location not in ("path", "query", "header")
      ):
        raise ValueError(f"{label}/parameters/{index}：需要原名及受支持的位置")
      identity = (location, name.lower() if location == "header" else name)
      if identity in seen:
        raise ValueError(f"{label}/parameters：重复或冲突的参数 {location}.{name}")
      seen.add(identity)
      merged[identity] = parameter
  return list(merged.values())


def request_definition(document: dict, path_item: dict, operation: dict) -> dict:
  security = operation.get("security", document.get("security", []))
  if not isinstance(security, list) or any(item != {} for item in security):
    raise ValueError("security：当前仅支持无认证接口，请选择显式无认证的接口")
  version = document["openapi"]
  schema = {
    "$schema": DRAFT2020,
    "type": "object",
    "properties": {},
    "additionalProperties": False,
  }
  mappings = []
  required_groups = []
  for parameter in merged_parameters(path_item, operation):
    name, location = parameter["name"], parameter["in"]
    label = f"parameters/{location}/{name}"
    if "content" in parameter or parameter.get("allowReserved", False):
      raise ValueError(f"{label}：不支持 content 或 allowReserved 序列化")
    required = parameter.get("required", False)
    if not isinstance(required, bool) or (location == "path" and not required):
      raise ValueError(f"{label}/required：路径参数必须显式为 true，其余须为布尔值")
    node = convert_schema(parameter.get("schema"), version, label + "/schema")
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
    body = inline_object(operation["requestBody"], "requestBody")
    content = inline_object(body.get("content"), "requestBody/content")
    media = inline_object(
      content.get("application/json"), "requestBody/application/json"
    )
    if media.get("encoding"):
      raise ValueError("requestBody/encoding：不支持特殊请求体编码")
    schema["properties"]["body"] = convert_schema(
      media.get("schema"), version, "requestBody/schema"
    )
    if not isinstance(body.get("required", False), bool):
      raise ValueError("requestBody/required：需要布尔值")
    if body.get("required"):
      required_groups.append("body")
  if required_groups:
    schema["required"] = required_groups
  return {"input_schema": schema, "parameters": mappings}


def output_preview(operation: dict, version: str) -> tuple[dict | None, list[str]]:
  try:
    responses = inline_object(operation.get("responses", {}), "responses")
    success = [
      value for code, value in responses.items() if re.fullmatch(r"2\d\d", code)
    ]
    if not success or any(code.upper() == "2XX" for code in responses):
      raise ValueError("成功响应不是单一明确结构")
    schemas = []
    for value in success:
      response = inline_object(value, "responses/success")
      content = inline_object(response.get("content"), "responses/success/content")
      if set(content) != {"application/json"}:
        raise ValueError("成功响应不是单一 application/json")
      media = inline_object(content["application/json"], "responses/application/json")
      schemas.append(convert_schema(media.get("schema"), version, "responses/schema"))
    if any(schema != schemas[0] for schema in schemas[1:]):
      raise ValueError("成功响应存在多种不同结构")
    return {"$schema": DRAFT2020, **schemas[0]}, []
  except ValueError as error:
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
      try:
        path_item = inline_object(raw_path_item, f"paths/{path}")
        operation = inline_object(raw_operation, candidate["key"])
        if method not in METHODS:
          raise ValueError(f"method：不支持 {method.upper()}")
        if "jsonSchemaDialect" in parsed_document:
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
        definition.update(request_definition(parsed_document, path_item, operation))
        output, output_warnings = output_preview(operation, parsed_document["openapi"])
        definition["output_schema"] = output
        warnings.extend(output_warnings)
        definition["openapi_source"] = {
          "openapi": parsed_document["openapi"],
          "info": parsed_document.get("info", {}),
          "path": path,
          "method": method.upper(),
          "servers": servers,
          "path_item": {
            key: value
            for key, value in path_item.items()
            if key in ("summary", "description", "parameters", "servers")
          },
          "operation": operation,
        }
        now = datetime.now(UTC)
        HttpToolDefinition.model_validate(
          {
            **definition,
            "id": "preview",
            "name": "preview",
            "display_name": "preview",
            "url": "https://openapi.invalid" + path,
            "created_at": now,
            "updated_at": now,
          }
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
      except (ValueError, TypeError, AttributeError) as error:
        if isinstance(error, ValidationError):
          errors.extend(
            f"{'.'.join(map(str, item['loc']))}：{item['msg']}"
            for item in error.errors(include_input=False)
          )
        else:
          errors.append(str(error))
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
