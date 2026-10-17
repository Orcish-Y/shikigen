"""补齐 Python 输入结构，并保护源码决定的参数契约；不修改传入对象。"""

from copy import deepcopy

from shikigen.contracts.input_schema import validate_tool_schema
from shikigen.contracts.python_source import PythonSourceError, parse_python_source
from shikigen.contracts.schema_references import resolve_reference

JSON_TYPES = {"string", "integer", "number", "boolean", "object", "array", "null"}


def prepare_python_input_schema(source: object, supplied: object = ...) -> dict:
  """按当前源码复核最终 schema；未补齐或改写源码契约均拒绝保存和执行。"""
  parsed = parse_python_source(source)
  expected = parsed["input_schema"]
  schema = deepcopy(expected if supplied is ... else supplied)
  if not isinstance(schema, dict):
    raise PythonSourceError("python_schema", "输入结构必须是 JSON Schema 对象")
  try:
    validate_tool_schema(schema, inputs=True)
  except ValueError as error:
    raise PythonSourceError("python_schema", str(error)) from None

  def reject(path: str, message: str, code: str = "python_schema"):
    raise PythonSourceError(code, f"{path}：{message}")

  def check(field, constraint: dict, path: str, *, allow_open: bool = False):
    if isinstance(field, bool):
      if allow_open and not constraint:
        return
      reject(path, "请补齐类型，或在开放容器中明确允许任意 JSON", "python_annotation")
    if "$ref" in field:
      field = resolve_reference(schema, field["$ref"])
      return check(field, constraint, path, allow_open=allow_open)
    actual = field.get("type")
    actual_types = set(actual if isinstance(actual, list) else [actual])
    source_type = constraint.get("type")
    source_types = set(source_type if isinstance(source_type, list) else [source_type])
    unknown = source_type is None or source_type == ["null"]
    if unknown:
      if not actual_types <= JSON_TYPES or not actual_types:
        reject(path, "类型待补", "python_annotation")
      nullable = source_type == ["null"]
      if ("null" in actual_types) != nullable or len(actual_types - {"null"}) != 1:
        reject(path, "请选择一个 JSON 类型；允许 null 须与源码注解一致")
    elif actual_types != source_types:
      reject(path, "不能改写源码确定的类型或 null 许可")
    if "array" in actual_types:
      if "items" not in field:
        reject(path, "数组元素待补，或明确设置 items: true 开放", "python_annotation")
      check(
        field["items"], constraint.get("items", {}), path + "/items", allow_open=True
      )
    if "object" in actual_types:
      if "additionalProperties" not in field:
        reject(path, "对象结构待补，请声明 additionalProperties", "python_annotation")
      value_constraint = constraint.get("additionalProperties", {})
      for name, child in field.get("properties", {}).items():
        check(child, value_constraint, path + "/" + name, allow_open=True)
      for name, child in field.get("patternProperties", {}).items():
        check(
          child, value_constraint, path + "/patternProperties/" + name, allow_open=True
        )
      additional = field["additionalProperties"]
      if additional is not False:
        check(
          additional, value_constraint, path + "/additionalProperties", allow_open=True
        )

  if "$ref" in schema or schema.get("patternProperties"):
    reject("input_schema", "顶层参数须直接声明，不能以引用或 patternProperties 改写")
  properties = schema.get("properties", {})
  required = set(schema.get("required", []))
  names = set(expected["properties"])
  extra_schema = parsed["extra_schema"]
  if not names <= set(properties) or required & names != set(expected["required"]):
    reject("input_schema", "不能改写源码确定的名称和必填性")
  if not required <= set(properties):
    reject("input_schema", "必填业务字段必须在 properties 中声明")
  if extra_schema is None:
    if (
      set(properties) != names or schema.get("additionalProperties", True) is not False
    ):
      reject("input_schema", "main 未声明 **kwargs，不能新增参数或允许附加属性")
  else:
    if "additionalProperties" not in schema:
      reject(
        "input_schema", "请声明 **kwargs 的字段或明确允许附加属性", "python_annotation"
      )
    for name in set(properties) - names:
      check(properties[name], extra_schema, name, allow_open=True)
    if schema["additionalProperties"] is not False:
      check(schema["additionalProperties"], extra_schema, "**kwargs", allow_open=True)
  for name, constraint in expected["properties"].items():
    check(properties[name], constraint, name)
  return schema
