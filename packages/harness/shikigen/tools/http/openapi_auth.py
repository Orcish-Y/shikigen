"""OpenAPI 认证备选方案；凭据仍使用 HTTP 定义的专属 auth 配置。"""

from copy import deepcopy

from shikigen.contracts.http_requests import check_header
from shikigen.tools.http.openapi_schema import OpenApiSchemas


def security_options(schemas: OpenApiSchemas, operation: dict) -> tuple[list, dict]:
  requirements = operation.get("security", schemas.document.get("security", []))
  if not isinstance(requirements, list):
    raise ValueError("security：需要备选方案数组；请修正文档")
  options = []
  sources = {}
  for index, requirement in enumerate(requirements or [{}]):
    option = {"id": f"security_{index}", "label": "", "auth": [], "errors": []}
    options.append(option)
    if not isinstance(requirement, dict):
      option["errors"].append(f"security/{index}：需要认证要求对象；请修正文档")
      continue
    option["label"] = " + ".join(requirement) or "无认证（来源允许）"
    targets = set()
    for binding_index, (name, scopes) in enumerate(requirement.items()):
      path = f"security/{index}/{name}"
      try:
        components = schemas.document.get("components", {})
        raw = components.get("securitySchemes", {}).get(name)
        sources[name] = deepcopy(raw)
        scheme = schemas.object(raw, f"components/securitySchemes/{name}")
        if scopes != []:
          raise ValueError("带 scope 的认证要求未支持")
        if (
          scheme.get("type") == "http"
          and str(scheme.get("scheme", "")).lower() == "bearer"
        ):
          binding = {"kind": "bearer", "location": "headers", "name": "Authorization"}
        elif scheme.get("type") == "apiKey" and scheme.get("in") in ("header", "query"):
          binding = {
            "kind": "api_key",
            "location": "headers" if scheme["in"] == "header" else "query",
            "name": scheme.get("name"),
          }
        else:
          raise ValueError("仅支持 Bearer 和 header/query API Key")
        if not isinstance(binding["name"], str) or not binding["name"]:
          raise ValueError("认证目标名称不能为空")
        target = (
          binding["location"],
          binding["name"].lower()
          if binding["location"] == "headers"
          else binding["name"],
        )
        if binding["location"] == "headers":
          check_header(binding["name"])
          if target[1] == "content-type":
            raise ValueError("认证不能覆盖 Content-Type")
        if target in targets:
          raise ValueError("同一方案认证目标冲突")
        targets.add(target)
        option["auth"].append(
          {"id": f"auth_{index}_{binding_index}", **binding, "value": ""}
        )
      except (ValueError, AttributeError) as error:
        option["errors"].append(f"{path}：{error}；请选择其他受支持方案或修正文档")
  return options, {"security": deepcopy(requirements), "securitySchemes": sources}


def authentication_errors(option: dict, auth) -> list[str]:
  """保存和预览共享的认证完整性检查；不能用删绑定降级为匿名。"""
  if option["errors"]:
    return option["errors"]
  if not isinstance(auth, list) or any(not isinstance(item, dict) for item in auth):
    return ["auth：需要认证绑定数组；请补齐所选方案"]

  def target(binding):
    name = binding.get("name")
    return (
      binding.get("kind"),
      binding.get("location"),
      name.lower()
      if isinstance(name, str) and binding.get("location") == "headers"
      else name,
    )

  expected = [target(binding) for binding in option["auth"]]
  actual = [target(binding) for binding in auth]
  if len(actual) != len(expected) or any(item not in actual for item in expected):
    return ["auth：绑定必须满足所选认证方案的全部目标；请恢复绑定或选择其他方案"]
  return [
    f"auth/{index}/value：请补齐 {binding.get('name')} 的认证值"
    for index, binding in enumerate(auth)
    if not isinstance(binding.get("value"), str) or not binding["value"].strip()
  ]
