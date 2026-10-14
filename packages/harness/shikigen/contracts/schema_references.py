"""本地 schema 引用解析；返回目标节点，不修改或展开原 schema。"""


def resolve_reference(root: dict, reference: str):
  """解析一次本地 JSON Pointer，返回它指向的 schema 节点。"""
  if reference != "#" and not reference.startswith("#/"):
    raise ValueError("Only local JSON Pointer schema references are supported")
  target = root
  try:
    for segment in reference[2:].split("/") if reference != "#" else []:
      key = segment.replace("~1", "/").replace("~0", "~")
      target = target[int(key)] if isinstance(target, list) else target[key]
  except (KeyError, IndexError, TypeError, ValueError):
    raise ValueError(f"Unresolved local schema reference: {reference}") from None
  if not isinstance(target, (dict, bool)):
    raise ValueError(f"Schema reference must point to a schema: {reference}")
  return target


def resolve_schema(root: dict, node):
  """沿节点的 $ref 链解析，拒绝循环；没有引用时返回原节点。"""
  seen = set()
  while isinstance(node, dict) and "$ref" in node:
    reference = node["$ref"]
    if reference in seen:
      raise ValueError("Circular schema references are not supported")
    seen.add(reference)
    node = resolve_reference(root, reference)
  return node
