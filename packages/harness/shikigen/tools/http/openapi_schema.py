"""按使用路径转换 OpenAPI 请求结构，保留引用来源，不修改文档。"""

from copy import deepcopy
from urllib.parse import unquote

from shikigen.contracts.input_schema import (
  ANNOTATIONS,
  DRAFT2020,
  SUPPORTED,
  validate_tool_schema,
)
from shikigen.contracts.schema_references import resolve_reference

SUPPORTED_DIALECTS = {DRAFT2020, "https://spec.openapis.org/oas/3.1/dialect/base"}


def inline_object(value, path: str) -> dict:
  if not isinstance(value, dict):
    raise ValueError(f"{path}：需要对象结构；请修正文档")
  if "$ref" in value:
    raise ValueError(f"{path}/$ref：此位置不支持引用；请改为内联定义")
  return value


class OpenApiSchemas:
  def __init__(self, document: dict):
    self.document = document
    self.version = document["openapi"]
    self.references: dict = {}

  def reference(self, node: dict, path: str, ancestors: frozenset[int]):
    reference = node["$ref"]
    if not isinstance(reference, str) or not reference.startswith("#/"):
      raise ValueError(f"{path}/$ref ({reference})：仅支持文档内部 #/... 引用；请内联")
    try:
      target = resolve_reference(self.document, unquote(reference))
    except ValueError:
      raise ValueError(f"{path}/$ref ({reference})：无法解析引用；请修正目标") from None
    if id(target) in ancestors:
      raise ValueError(f"{path}/$ref ({reference})：循环引用未支持；请改为有限结构")
    self.references[reference] = deepcopy(target)
    return target, f"{path}/$ref({reference})"

  def object(self, value, path: str, ancestors=frozenset()) -> dict:
    if not isinstance(value, dict):
      raise ValueError(f"{path}：需要对象结构；请修正文档")
    if "$ref" not in value:
      return value
    if set(value) - {"$ref", "summary", "description"}:
      raise ValueError(f"{path}/$ref：引用旁的扩展字段未支持；请移入引用目标")
    target, target_path = self.reference(value, path, ancestors | {id(value)})
    resolved = self.object(target, target_path, ancestors | {id(value)})
    # 3.1 Reference Object 允许 summary/description 覆盖；3.0 忽略同级字段。
    overrides = (
      {key: value[key] for key in ("summary", "description") if key in value}
      if self.version.startswith("3.1.")
      else {}
    )
    return {**resolved, **overrides}

  def convert(self, value, path: str, ancestors=frozenset()) -> dict:
    if not isinstance(value, dict):
      raise ValueError(f"{path}：需要普通 schema 对象；请修正文档")
    if id(value) in ancestors:
      raise ValueError(f"{path}：循环引用未支持；请改为有限结构")
    ancestors = ancestors | {id(value)}
    source = value
    if "$schema" in source:
      if (
        not self.version.startswith("3.1.")
        or not isinstance(source["$schema"], str)
        or source["$schema"] not in SUPPORTED_DIALECTS
      ):
        raise ValueError(f"{path}/$schema：自定义或不适用的方言未支持；请改用标准方言")
      source = {key: item for key, item in source.items() if key != "$schema"}
    if "$ref" in value:
      if set(source) - ANNOTATIONS - {"$ref"}:
        raise ValueError(f"{path}/$ref：引用旁的约束未支持；请移入引用目标")
      target, target_path = self.reference(value, path, ancestors)
      result = self.convert(target, target_path, ancestors)
      if self.version.startswith("3.1."):
        result.update(
          {key: deepcopy(value[key]) for key in ANNOTATIONS if key in value}
        )
      return result
    combinations = set(source) & {"oneOf", "anyOf", "allOf"}
    if combinations:
      key = next(iter(combinations))
      branches = source[key]
      if (
        self.version.startswith("3.1.")
        and len(combinations) == 1
        and key != "allOf"
        and isinstance(branches, list)
        and len(branches) == 2
        and not (set(source) - ANNOTATIONS - {key})
      ):
        converted_branches = [
          self.convert(branch, f"{path}/{key}/{index}", ancestors)
          for index, branch in enumerate(branches)
        ]
        nulls = [
          index
          for index, branch in enumerate(converted_branches)
          if isinstance(branch, dict)
          and branch.get("type") == "null"
          and not (set(branch) - ANNOTATIONS - {"type"})
        ]
        if len(nulls) == 1:
          result = converted_branches[1 - nulls[0]]
          value_type = result.get("type")
          types = [value_type] if isinstance(value_type, str) else value_type
          if (
            types
            and len(set(types) - {"null"}) == 1
            and "const" not in result
            and (key != "oneOf" or "null" not in types)
          ):
            result["type"] = list(dict.fromkeys([*types, "null"]))
            if "enum" in result and None not in result["enum"]:
              result["enum"].append(None)
            result.update(
              {k: deepcopy(v) for k, v in source.items() if k in ANNOTATIONS}
            )
            return result
      raise ValueError(f"{path}/{key}：通用组合未支持；请使用单一普通结构加 null")
    unsupported = set(source) - (
      SUPPORTED - {"$ref", "$defs", "definitions", "$schema"}
    )
    if self.version.startswith("3.0."):
      unsupported -= {"nullable"}
    if unsupported:
      raise ValueError(
        f"{path}：尚不支持 {', '.join(sorted(unsupported))}；请改为支持的普通结构"
      )
    if source.get("format") == "binary" or source.get("type") == "file":
      raise ValueError(f"{path}：文件／二进制请求未支持；请选择 JSON 数据接口")
    result = deepcopy(source)
    nullable = result.pop("nullable", False)
    if not isinstance(nullable, bool):
      raise ValueError(f"{path}/nullable：需要布尔值")
    if nullable:
      if not isinstance(result.get("type"), str):
        raise ValueError(f"{path}/nullable：需要明确的单一 type")
      result["type"] = [result["type"], "null"]
    if self.version.startswith("3.0."):
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
          name: self.convert(child, f"{path}/{key}/{name}", ancestors)
          for name, child in value[key].items()
        }
    for key in ("items", "additionalProperties", "propertyNames"):
      if key in result and not isinstance(result[key], bool):
        result[key] = self.convert(value[key], f"{path}/{key}", ancestors)
    try:
      validate_tool_schema(
        {"$schema": DRAFT2020, "type": "object", "properties": {"value": result}},
        inputs=True,
      )
    except ValueError as error:
      raise ValueError(f"{path}：{error}；请修正此处约束") from None
    return result
