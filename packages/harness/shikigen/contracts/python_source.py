"""静态提取 main 的参数契约；未知类型保留待补，不执行用户代码。"""

import ast
import math
from typing import Any, TypedDict


class PythonSourceError(ValueError):
  def __init__(self, code: str, message: str, status: int = 422):
    super().__init__(message)
    self.code = code
    self.status = status


class ParsedPythonSource(TypedDict):
  input_schema: dict[str, Any]
  parameters: list[dict[str, Any]]
  extra_schema: dict[str, Any] | None


def _annotation_name(node: ast.expr) -> str | None:
  if isinstance(node, ast.Name):
    return node.id
  if (
    isinstance(node, ast.Attribute)
    and isinstance(node.value, ast.Name)
    and node.value.id == "typing"
  ):
    return node.attr
  return None


def annotation_schema(node: ast.expr | None, depth: int = 0) -> dict[str, Any]:
  """只识别约定的注解语法，不解析导入、别名或自定义对象构造。"""
  if node is None or depth > 30:
    return {}
  if isinstance(node, ast.Constant):
    if node.value is None:
      return {"type": "null"}
    if isinstance(node.value, str):
      try:
        return annotation_schema(ast.parse(node.value, mode="eval").body, depth + 1)
      except (SyntaxError, ValueError):
        return {}
  name = _annotation_name(node)
  types = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "List": "array",
    "dict": "object",
    "Dict": "object",
  }
  if name in types:
    return {"type": types[name]}
  if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
    members = [
      annotation_schema(node.left, depth + 1),
      annotation_schema(node.right, depth + 1),
    ]
  elif isinstance(node, ast.Subscript):
    name = _annotation_name(node.value)
    if name in ("list", "List"):
      return {"type": "array", "items": annotation_schema(node.slice, depth + 1)}
    if (
      name in ("dict", "Dict")
      and isinstance(node.slice, ast.Tuple)
      and len(node.slice.elts) == 2
    ):
      if annotation_schema(node.slice.elts[0], depth + 1) != {"type": "string"}:
        raise PythonSourceError("python_annotation", "字典注解仅支持 dict[str, T]")
      return {
        "type": "object",
        "additionalProperties": annotation_schema(node.slice.elts[1], depth + 1),
      }
    if name == "Optional":
      members = [annotation_schema(node.slice, depth + 1), {"type": "null"}]
    elif (
      name == "Union"
      and isinstance(node.slice, ast.Tuple)
      and len(node.slice.elts) == 2
    ):
      members = [annotation_schema(item, depth + 1) for item in node.slice.elts]
    else:
      return {}
  else:
    return {}
  non_null = [item for item in members if item.get("type") != "null"]
  if len(non_null) != 1:
    return {}
  value = non_null[0]
  value_type = value.get("type")
  nullable_types = (
    value_type
    if isinstance(value_type, list)
    else ([value_type] if isinstance(value_type, str) else [])
  )
  return {
    **value,
    "type": list(dict.fromkeys([*nullable_types, "null"])),
  }


def parse_python_source(source: object) -> ParsedPythonSource:
  if not isinstance(source, str) or not source.strip():
    raise PythonSourceError("python_source_empty", "Python 源码不能为空")
  try:
    tree = ast.parse(source)
    compile(tree, "<tool>", "exec")
  except (SyntaxError, ValueError) as error:
    raise PythonSourceError("python_syntax", str(error)) from None
  entries = [
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "main"
  ]
  if len(entries) != 1:
    raise PythonSourceError("python_entry", "需要唯一的顶层同步函数 main")
  entry = entries[0]
  if isinstance(entry, ast.AsyncFunctionDef) or entry.decorator_list:
    raise PythonSourceError("python_entry", "main 不支持异步函数或装饰器")
  arguments = entry.args
  if arguments.posonlyargs or arguments.vararg:
    raise PythonSourceError("python_signature", "不支持仅位置参数或可变位置参数 *args")

  class GeneratorChecker(ast.NodeVisitor):
    generator = False

    def visit_FunctionDef(self, node):
      pass

    def visit_AsyncFunctionDef(self, node):
      pass

    def visit_Lambda(self, node):
      pass

    def visit_Yield(self, node):
      self.generator = True

    def visit_YieldFrom(self, node):
      self.generator = True

  checker = GeneratorChecker()
  for statement in entry.body:
    checker.visit(statement)
  if checker.generator:
    raise PythonSourceError("python_entry", "main 不支持生成器入口")
  properties = {}
  required = []
  parameters = []
  default_start = len(arguments.args) - len(arguments.defaults)
  defaults = [None] * default_start + list(arguments.defaults)
  pairs = list(zip(arguments.args, defaults, strict=True)) + list(
    zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
  )
  for argument, default in pairs:
    schema = annotation_schema(argument.annotation)
    parameter = {
      "name": argument.arg,
      "type": schema.get("type"),
      "required": default is None,
      "schema": dict(schema),
    }
    if default is None:
      required.append(argument.arg)
    else:
      parameter["default_expression"] = ast.get_source_segment(source, default)
      # Display scalar literals; calls and other expressions stay unevaluated.
      try:
        value = ast.literal_eval(default)
      except (ValueError, TypeError, SyntaxError):
        value = ...
      if value is None or type(value) in (str, int, float, bool):
        if not isinstance(value, float) or math.isfinite(value):
          parameter["default"] = value
          # A default of None permits omission, but does not make int nullable.
          if value is not None:
            schema["default"] = value
    properties[argument.arg] = schema
    parameters.append(parameter)
  extra_schema = (
    annotation_schema(arguments.kwarg.annotation) if arguments.kwarg else None
  )
  return {
    "input_schema": {
      "type": "object",
      "properties": properties,
      "required": required,
      **(
        {"additionalProperties": False}
        if extra_schema is None
        else {"additionalProperties": extra_schema}
        if extra_schema
        else {}
      ),
    },
    "parameters": parameters,
    "extra_schema": extra_schema,
  }
