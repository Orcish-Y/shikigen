"""显式支持的 JSON Schema 方言及输入子集；未知约束不会被忽略执行。"""

from jsonschema import Draft7Validator, Draft202012Validator
from jsonschema.exceptions import SchemaError

from shikigen.contracts.schema_references import resolve_reference

DRAFT7 = "http://json-schema.org/draft-07/schema#"
DRAFT2020 = "https://json-schema.org/draft/2020-12/schema"
ANNOTATIONS = {
  "title",
  "description",
  "default",
  "examples",
  "example",
  "format",
  "readOnly",
  "writeOnly",
  "deprecated",
  "$comment",
}
SUPPORTED = ANNOTATIONS | {
  "$schema",
  "$ref",
  "$defs",
  "definitions",
  "type",
  "enum",
  "const",
  "properties",
  "required",
  "additionalProperties",
  "patternProperties",
  "propertyNames",
  "minProperties",
  "maxProperties",
  "items",
  "minItems",
  "maxItems",
  "uniqueItems",
  "minimum",
  "maximum",
  "exclusiveMinimum",
  "exclusiveMaximum",
  "multipleOf",
  "minLength",
  "maxLength",
  "pattern",
}


def get_schema_validator_class(schema: dict):
  dialect = schema.get("$schema", DRAFT7)
  if dialect in (DRAFT7, "https://json-schema.org/draft-07/schema#"):
    return Draft7Validator
  if dialect == DRAFT2020:
    return Draft202012Validator
  raise ValueError(f"Unsupported JSON Schema dialect: {dialect}")


def validate_tool_schema(schema: dict, *, inputs: bool) -> None:
  """校验方言、约束和引用；不修改 schema，也不展开或替换 $ref。"""
  validator_class = get_schema_validator_class(schema)
  try:
    validator_class.check_schema(schema)
  except SchemaError as error:
    raise ValueError(f"Invalid JSON schema: {error.message}") from None
  if inputs and schema.get("type") != "object":
    raise ValueError("Tool inputs must use an object schema")

  def visit(node, path: str, ancestors: frozenset[int]):
    if isinstance(node, bool):
      return
    if id(node) in ancestors:
      raise ValueError(f"Circular schema reference at {path}")
    ancestors = ancestors | {id(node)}
    if inputs:
      unsupported = set(node) - SUPPORTED
      if unsupported:
        raise ValueError(
          f"Unsupported input schema keywords at {path}: "
          f"{', '.join(sorted(unsupported))}"
        )
      if "$schema" in node and node is not schema:
        raise ValueError(f"Nested schema dialects are not supported at {path}")
      value_type = node.get("type")
      if isinstance(value_type, list) and len(set(value_type) - {"null"}) > 1:
        raise ValueError(
          f"Only a single type with optional null is supported at {path}"
        )
      if isinstance(node.get("items"), list):
        raise ValueError(f"Tuple array schemas are not supported at {path}")
      if (
        "$ref" in node
        and validator_class is Draft7Validator
        and set(node) - ANNOTATIONS - {"$ref"}
      ):
        raise ValueError(
          f"draft-07 ignores constraints beside $ref at {path}; "
          "place them in its target"
        )
    if "$ref" in node:
      visit(resolve_reference(schema, node["$ref"]), path + "/$ref", ancestors)
    for key in ("properties", "patternProperties", "definitions", "$defs"):
      for name, child in node.get(key, {}).items():
        visit(child, f"{path}/{key}/{name}", ancestors)
    for key in ("items", "additionalProperties", "propertyNames"):
      if key in node and isinstance(node[key], (dict, bool)):
        visit(node[key], f"{path}/{key}", ancestors)

  visit(schema, "#", frozenset())
