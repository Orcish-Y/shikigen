"""从源码静态提取 main 的标量参数；不导入、执行或求值用户代码。"""

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
  if (
    arguments.posonlyargs or arguments.vararg or arguments.kwonlyargs or arguments.kwarg
  ):
    raise PythonSourceError(
      "python_signature", "当前仅支持普通具名参数；复杂签名由后续类型补齐功能支持"
    )

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
  types = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}
  for index, argument in enumerate(arguments.args):
    annotation = argument.annotation
    name = (
      annotation.id
      if isinstance(annotation, ast.Name)
      else annotation.value
      if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str)
      else None
    )
    if name not in types:
      raise PythonSourceError(
        "python_annotation",
        f"参数 {argument.arg} 的类型待补；当前支持 str、int、float、bool",
      )
    parameter = {
      "name": argument.arg,
      "type": types[name],
      "required": index < default_start,
    }
    schema = {"type": types[name]}
    if index < default_start:
      required.append(argument.arg)
    else:
      default = arguments.defaults[index - default_start]
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
  return {
    "input_schema": {
      "type": "object",
      "properties": properties,
      "required": required,
      "additionalProperties": False,
    },
    "parameters": parameters,
  }
