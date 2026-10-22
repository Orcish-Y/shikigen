import json
import tempfile
import unittest
from pathlib import Path

import httpx
from shikigen.app_config import load_app_config
from shikigen.contracts.python_source import PythonSourceError, parse_python_source
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime

from app.server import create_app


class PythonSourceContractTests(unittest.TestCase):
  def test_shared_editor_samples_against_backend_authority(self):
    cases = json.loads(
      (Path(__file__).parent / "fixtures/python_source_cases.json").read_text(
        encoding="utf-8"
      )
    )
    for case in cases:
      with self.subTest(case=case["id"]):
        if "backend_error" in case:
          with self.assertRaises(PythonSourceError) as caught:
            parse_python_source(case["source"])
          self.assertEqual(caught.exception.code, case["backend_error"])
          continue
        result = parse_python_source(case["source"])
        actual = [
          [parameter["name"], parameter["type"], parameter["required"]]
          + (
            [parameter["default_expression"]]
            if "default_expression" in parameter
            else []
          )
          for parameter in result["parameters"]
        ]
        self.assertEqual(actual, case["parameters"])


class PythonToolApiTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.path = Path(self.directory.name) / "loaded-config.json"
    self.path.write_text(json.dumps({"model": {}, "mcp": {}}), encoding="utf-8")
    store = await ChatStore.open(Path(self.directory.name) / "tests.db")
    self.addAsyncCleanup(store.close)
    runtime = assemble_runtime(
      config=load_app_config(self.path), agent=None, chat_store=store
    )
    app = create_app(runtime=runtime)
    context = app.router.lifespan_context(app)
    await context.__aenter__()
    self.addAsyncCleanup(context.__aexit__, None, None, None)
    self.client = httpx.AsyncClient(
      transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    self.addAsyncCleanup(self.client.aclose)
    self.addAsyncCleanup(runtime.lifecycle.shutdown)

  def payload(self, source, **overrides):
    return {
      "kind": "python",
      "name": "calculate",
      "display_name": "计算",
      "source": source,
      **overrides,
    }

  async def create(self, source, **overrides):
    response = await self.client.post(
      "/api/tools", json=self.payload(source, **overrides)
    )
    self.assertEqual(response.status_code, 201, response.text)
    return (await self.client.get("/api/tools/" + response.json()["data"]["id"])).json()

  async def execute(self, saved, inputs):
    response = await self.client.post(
      f"/api/tools/{saved['data']['id']}/execute", json={"inputs": inputs}
    )
    self.assertEqual(response.status_code, 200, response.text)
    return response.json()["data"]

  async def test_parse_save_and_execute_named_parameters_and_function_defaults(self):
    source = (
      "def double(value):\n  return value * 2\n\n"
      "def main(quantity: int, price: float = 2.5, label: str = '订单', "
      "active: bool = True):\n"
      "  print('debug output')\n"
      "  return {'total': double(quantity) * price, 'label': label, 'active': active}\n"
    )
    saved = await self.create(source)
    schema = saved["data"]["input_schema"]
    self.assertEqual(schema["required"], ["quantity"])
    self.assertEqual(schema["properties"]["price"], {"type": "number", "default": 2.5})
    self.assertEqual(saved["data"]["source"], source)
    raw = json.loads(self.path.read_text(encoding="utf-8"))
    self.assertNotIn("source", raw["tool_library"]["tools"][0])
    self.assertFalse(Path(saved["data"]["code_path"]).is_absolute())
    self.assertEqual(
      (self.path.parent / saved["data"]["code_path"]).read_text(encoding="utf-8"),
      source,
    )
    result = await self.execute(saved, {"quantity": 3})
    self.assertEqual(result["status"], "success", result)
    self.assertEqual(result["data"], {"total": 15.0, "label": "订单", "active": True})
    self.assertEqual(result["details"]["stdout"].splitlines(), ["debug output"])
    self.assertEqual(result["details"]["exit_code"], 0)

  async def test_unknown_type_requires_completion_and_keeps_business_constraints(
    self,
  ):
    source = "def main(value): return value\n"
    incomplete = await self.client.post("/api/tools", json=self.payload(source))
    self.assertEqual(incomplete.status_code, 422, incomplete.text)
    schema = {
      "type": "object",
      "properties": {
        "value": {"type": "integer", "minimum": 2, "description": "至少两个"}
      },
      "required": ["value"],
      "additionalProperties": False,
    }
    saved = await self.create(source, input_schema=schema)
    self.assertEqual(saved["data"]["input_schema"], schema)
    self.assertEqual((await self.execute(saved, {"value": 3}))["data"], 3)
    self.assertEqual(
      (await self.execute(saved, {"value": 1}))["error"]["code"], "input_validation"
    )

  async def test_nested_containers_nullable_keyword_only_and_declared_extra_inputs(
    self,
  ):
    source = (
      "from typing import Optional\n"
      "def main(rows: list[dict[str, Optional[int]]], *, "
      "label: str = 'ok', **extras):\n"
      "  return {'rows': rows, 'label': label, 'extras': extras}\n"
    )
    schema = {
      "type": "object",
      "properties": {
        "rows": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": {"type": ["integer", "null"], "minimum": 0},
          },
        },
        "label": {"type": "string"},
        "flag": {"type": "boolean"},
      },
      "required": ["rows", "flag"],
      "additionalProperties": False,
    }
    saved = await self.create(source, input_schema=schema)
    result = await self.execute(saved, {"rows": [{"x": None, "y": 2}], "flag": True})
    self.assertEqual(result["status"], "success", result)
    self.assertEqual(
      result["data"],
      {"rows": [{"x": None, "y": 2}], "label": "ok", "extras": {"flag": True}},
    )
    for inputs in (
      {"rows": [], "flag": True, "unknown": 3},
      {"rows": [{"x": -1}], "flag": False},
      {"rows": []},
    ):
      self.assertEqual(
        (await self.execute(saved, inputs))["error"]["code"], "input_validation"
      )

  async def test_plain_containers_must_be_completed_or_explicitly_opened(self):
    source = "def main(rows: list, options: dict): return [rows, options]\n"
    pending = await self.client.post("/api/tools", json=self.payload(source))
    self.assertEqual(pending.status_code, 422, pending.text)
    schema = {
      "type": "object",
      "properties": {
        "rows": {"type": "array", "items": True},
        "options": {"type": "object", "additionalProperties": True},
      },
      "required": ["rows", "options"],
      "additionalProperties": False,
    }
    saved = await self.create(source, input_schema=schema)
    self.assertEqual(
      (await self.execute(saved, {"rows": [None, {"a": 1}], "options": {"x": []}}))[
        "data"
      ],
      [[None, {"a": 1}], {"x": []}],
    )

  async def test_source_contract_is_protected_in_save_draft_and_saved_execution(self):
    from copy import deepcopy

    source = "def main(value: list[int], *, label: str | None): return [value, label]\n"
    saved = await self.create(source)
    schema = saved["data"]["input_schema"]
    cases = []
    for change in (
      lambda s: s["properties"].pop("value"),
      lambda s: s.update(required=["value"]),
      lambda s: s.update(additionalProperties=True),
      lambda s: s["properties"]["value"].update(type="string"),
      lambda s: s["properties"]["value"].update(items=True),
      lambda s: s["properties"]["value"]["items"].update(type="number"),
      lambda s: s["properties"]["label"].update(type="string"),
      lambda s: s.update(properties={**s["properties"], "renamed": {"type": "string"}}),
    ):
      candidate = deepcopy(schema)
      change(candidate)
      cases.append(candidate)
    cases.extend(
      [
        None,
        "{broken",
        {
          "$ref": "#/definitions/hidden",
          "type": "object",
          "definitions": {"hidden": schema},
        },
      ]
    )
    for candidate in cases:
      definition = self.payload(source, input_schema=candidate)
      for method, url, body in (
        (
          "PUT",
          f"/api/tools/{saved['data']['id']}",
          {"definition": definition, "version": saved["version"]},
        ),
        (
          "POST",
          "/api/tools/tests",
          {
            "definition": definition,
            "tool_id": saved["data"]["id"],
            "inputs": {"value": [], "label": None},
          },
        ),
      ):
        with self.subTest(candidate=candidate, method=method):
          rejected = await self.client.request(method, url, json=body)
          self.assertEqual(rejected.status_code, 422, rejected.text)
      self.assertEqual(
        (await self.client.get(f"/api/tools/{saved['data']['id']}")).json(), saved
      )
    path = self.path.parent / saved["data"]["code_path"]
    path.write_text(source.replace("list[int]", "list[str]"), encoding="utf-8")
    self.assertEqual(
      (await self.execute(saved, {"value": [1], "label": None}))["error"]["code"],
      "python_schema",
    )

  async def test_typed_kwargs_apply_to_declared_and_arbitrary_business_fields(self):
    source = (
      "def main(*, active: bool = True, **extras: int): return [active, extras]\n"
    )
    saved = await self.create(source)
    self.assertEqual(
      (await self.execute(saved, {"count": 2}))["data"], [True, {"count": 2}]
    )
    self.assertEqual(
      (await self.execute(saved, {"count": "2"}))["error"]["code"], "input_validation"
    )
    schema = saved["data"]["input_schema"]
    schema["properties"]["count"] = {"type": "string"}
    rejected = await self.client.post(
      "/api/tools/tests",
      json={
        "definition": self.payload(source, input_schema=schema),
        "inputs": {"count": "2"},
      },
    )
    self.assertEqual(rejected.status_code, 422, rejected.text)

  async def test_compatible_source_and_schema_supplements_can_test_without_saving(self):
    schema = {
      "type": "object",
      "properties": {
        "value": {"type": ["integer", "null"], "minimum": 2, "examples": [2, None]},
      },
      "required": ["value"],
      "additionalProperties": False,
    }
    source = (
      "from typing import Optional\n"
      "def main(value: Optional['Unknown']): return value\n"
    )
    saved = await self.create(source, input_schema=schema)
    for inputs, status in (
      ({}, "error"),
      ({"value": None}, "success"),
      ({"value": 1}, "error"),
    ):
      self.assertEqual((await self.execute(saved, inputs))["status"], status)
    current = source.replace("return value", "return value + 1")
    draft = await self.client.post(
      "/api/tools/tests",
      json={
        "definition": self.payload(current, input_schema=schema),
        "tool_id": saved["data"]["id"],
        "inputs": {"value": 2},
      },
    )
    self.assertEqual(draft.status_code, 202, draft.text)
    result = await self.wait_test(draft.json()["data"]["test_id"])
    self.assertEqual(result["data"], 3, result)
    self.assertEqual(
      (await self.client.get(f"/api/tools/{saved['data']['id']}")).json(), saved
    )
    # 明确的新注解可接受兼容补充，不能沿用与新注解冲突的旧类型。
    for annotation, status in (("int", 202), ("str", 422)):
      definition = self.payload(
        current.replace("'Unknown'", annotation), input_schema=schema
      )
      tested = await self.client.post(
        "/api/tools/tests",
        json={
          "definition": definition,
          "tool_id": saved["data"]["id"],
          "inputs": {"value": 2},
        },
      )
      self.assertEqual(tested.status_code, status, tested.text)
      if status == 202:
        self.assertEqual(
          (await self.wait_test(tested.json()["data"]["test_id"]))["data"], 3
        )

  async def test_parse_and_save_do_not_run_imports_annotations_or_default_calls(self):
    marker = self.path.parent / "side-effect.txt"
    source = (
      "from pathlib import Path\n"
      f"def mark():\n  Path({str(marker)!r}).write_text('executed')\n  return 9\n"
      "def main(count: 'int' = mark()):\n  return count\n"
    )
    saved = await self.create(source)
    self.assertEqual(saved["data"]["input_schema"]["required"], [])
    self.assertEqual(
      saved["data"]["input_schema"]["properties"]["count"], {"type": "integer"}
    )
    self.assertFalse(marker.exists())
    invalid = await self.execute(saved, {"count": "9"})
    self.assertEqual(invalid["error"]["code"], "input_validation")
    self.assertFalse(marker.exists())
    result = await self.execute(saved, {})
    self.assertEqual(result["data"], 9)
    self.assertTrue(marker.exists())

  async def test_invalid_sources_and_forged_parameter_schema_never_replace_saved_tool(
    self,
  ):
    saved = await self.create("def main(count: int = None):\n  return count\n")
    self.assertEqual(saved["data"]["input_schema"]["required"], [])
    self.assertEqual((await self.execute(saved, {}))["data"], None)
    self.assertEqual(
      (await self.execute(saved, {"count": None}))["error"]["code"], "input_validation"
    )
    before = self.path.read_bytes()
    cases = [
      ("def main(:", "python_syntax"),
      ("def helper(): pass", "python_entry"),
      ("def main(): pass\ndef main(): pass", "python_entry"),
      ("async def main(): pass", "python_entry"),
      ("def main(): yield 1", "python_entry"),
      ("@wrapper\ndef main(): pass", "python_entry"),
      ("def main(a: int, /): pass", "python_signature"),
      ("def main(*args): pass", "python_signature"),
      ("def main(**kwargs): pass", "python_annotation"),
      ("def main(a): pass", "python_annotation"),
      ("def main(a: list): pass", "python_annotation"),
      ("def main(a: dict[int, str]): pass", "python_annotation"),
    ]
    for source, code in cases:
      with self.subTest(source=source):
        response = await self.client.put(
          f"/api/tools/{saved['data']['id']}",
          json={"definition": self.payload(source), "version": saved["version"]},
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], code)
        self.assertEqual(self.path.read_bytes(), before)
    forged = await self.client.post(
      "/api/tools",
      json=self.payload(
        "def main(count: int): return count", input_schema={"type": "object"}
      ),
    )
    self.assertEqual(forged.status_code, 422)
    self.assertEqual(forged.json()["detail"]["code"], "python_schema")

  async def test_missing_source_never_falls_back_for_draft_tests_or_saves(self):
    saved = await self.create("def main(): return 'saved'\n")
    tool_id = saved["data"]["id"]
    source_path = self.path.parent / saved["data"]["code_path"]
    config_before = self.path.read_bytes()
    source_before = source_path.read_bytes()
    for source_fields in ({}, {"source": None}, {"source": ""}, {"source": " \n"}):
      definition = {**self.payload(None), **source_fields}
      if not source_fields:
        del definition["source"]
      requests = (
        ("POST", "/api/tools", definition),
        ("POST", "/api/tools/tests", {"definition": definition, "inputs": {}}),
        (
          "POST",
          "/api/tools/tests",
          {"definition": definition, "inputs": {}, "tool_id": tool_id},
        ),
        (
          "PUT",
          f"/api/tools/{tool_id}",
          {"definition": definition, "version": saved["version"]},
        ),
      )
      for method, url, body in requests:
        with self.subTest(source_fields=source_fields, method=method, body=body):
          response = await self.client.request(method, url, json=body)
          self.assertEqual(response.status_code, 422, response.text)
          self.assertEqual(response.json()["detail"]["code"], "python_source_empty")
          self.assertEqual(self.path.read_bytes(), config_before)
          self.assertEqual(source_path.read_bytes(), source_before)
    self.assertEqual(list(source_path.parent.glob("*.py")), [source_path])

  async def test_python_edits_require_explicit_kind(self):
    saved = await self.create("def main(): return 'saved'\n")
    definition = self.payload("def main(): return 'draft'\n")
    del definition["kind"]
    before = self.path.read_bytes()
    draft = await self.client.post(
      "/api/tools/tests",
      json={"definition": definition, "inputs": {}, "tool_id": saved["data"]["id"]},
    )
    update = await self.client.put(
      f"/api/tools/{saved['data']['id']}",
      json={"definition": definition, "version": saved["version"]},
    )
    for response in (draft, update):
      self.assertEqual(response.status_code, 422, response.text)
      self.assertEqual(response.json()["detail"]["code"], "definition_invalid")
    self.assertEqual(self.path.read_bytes(), before)
    self.assertEqual(
      (await self.client.get(f"/api/tools/{saved['data']['id']}")).json(), saved
    )

  async def test_current_source_can_be_tested_and_saved_when_old_file_is_missing(self):
    saved = await self.create("def main(count: int): return count\n")
    tool_id = saved["data"]["id"]
    old_path = self.path.parent / saved["data"]["code_path"]
    old_path.unlink()
    before = self.path.read_bytes()
    source = "def main(label: str): return 'current:' + label\n"
    definition = self.payload(source)
    draft = await self.client.post(
      "/api/tools/tests",
      json={"definition": definition, "inputs": {"label": "draft"}, "tool_id": tool_id},
    )
    self.assertEqual(draft.status_code, 202, draft.text)
    result = await self.wait_test(draft.json()["data"]["test_id"])
    self.assertEqual(result["status"], "success", result)
    self.assertEqual(result["data"], "current:draft")
    self.assertEqual(self.path.read_bytes(), before)
    self.assertEqual(list(old_path.parent.glob("*.py")), [])

    update = await self.client.put(
      f"/api/tools/{tool_id}",
      json={"definition": definition, "version": saved["version"]},
    )
    self.assertEqual(update.status_code, 204, update.text)
    updated = (await self.client.get(f"/api/tools/{tool_id}")).json()["data"]
    self.assertEqual(updated["id"], tool_id)
    self.assertEqual(updated["created_at"], saved["data"]["created_at"])
    self.assertEqual(updated["input_schema"]["required"], ["label"])
    self.assertEqual(updated["source"], source)
    self.assertNotEqual(updated["code_path"], saved["data"]["code_path"])
    path = self.path.parent / updated["code_path"]
    self.assertEqual(path.read_text(encoding="utf-8"), source)

    # 已保存工具的测试仍显式读取持久源码，和提交草稿的链路分开。
    path.write_text("def main(label: str): return 'file:' + label\n", encoding="utf-8")
    stored = await self.client.post(
      f"/api/tools/{tool_id}/tests", json={"inputs": {"label": "saved"}}
    )
    self.assertEqual(stored.status_code, 202, stored.text)
    result = await self.wait_test(stored.json()["data"]["test_id"])
    self.assertEqual(result["status"], "success", result)
    self.assertEqual(result["data"], "file:saved")

  async def test_edit_constraints_are_checked_before_parsing_draft_source(self):
    saved = await self.create("def main(): return 'saved'\n")
    before = self.path.read_bytes()
    cases = (
      ("missing-tool", self.payload(None), 404, "not_found"),
      (saved["data"]["id"], self.payload("def main(:", id="forged"), 422, "read_only"),
      (saved["data"]["id"], self.payload("def main(:", kind="http"), 422, "read_only"),
    )
    for tool_id, definition, status, code in cases:
      for method, url, body in (
        (
          "POST",
          "/api/tools/tests",
          {"definition": definition, "inputs": {}, "tool_id": tool_id},
        ),
        (
          "PUT",
          f"/api/tools/{tool_id}",
          {"definition": definition, "version": saved["version"]},
        ),
      ):
        with self.subTest(tool_id=tool_id, definition=definition, method=method):
          response = await self.client.request(method, url, json=body)
          self.assertEqual(response.status_code, status, response.text)
          self.assertEqual(response.json()["detail"]["code"], code)
    self.assertEqual(self.path.read_bytes(), before)

  async def test_strict_returns_debug_output_limits_runtime_and_binding_failures(self):
    cases = [
      (
        "return [None, True, 2, 1.5, '中文', {'ok': False}]",
        [None, True, 2, 1.5, "中文", {"ok": False}],
        None,
      ),
      ("return float('nan')", None, "python_return"),
      ("return float('inf')", None, "python_return"),
      ("return {1: 'coerced'}", None, "python_return"),
      ("return (1, 2)", None, "python_return"),
      ("raise ValueError('business error')", None, "python_runtime"),
      ("return 'x' * (1024 * 1024)", None, "output_limit"),
    ]
    for index, (statement, expected, code) in enumerate(cases):
      with self.subTest(statement=statement):
        response = await self.client.post(
          "/api/tools/tests",
          json={
            "definition": {
              **self.payload(f"def main():\n  {statement}\n"),
              "name": f"case_{index}",
            },
            "inputs": {},
          },
        )
        self.assertEqual(response.status_code, 202, response.text)
        result = await self.wait_test(response.json()["data"]["test_id"])
        self.assertEqual(result["data"], expected)
        self.assertEqual(
          result["error"]["code"] if result["error"] else None, code, result
        )
    saved = await self.create(
      "import sys\ndef main():\n  print('x' * 70000)\n  print('TAIL')\n"
      "  print('stderr output', file=sys.stderr)\n  return {'ok': True}\n"
    )
    result = await self.execute(saved, {})
    self.assertEqual(result["status"], "success", result)
    details = result["details"]
    self.assertTrue(details["stdout_truncated"])
    self.assertLessEqual(
      len(details["stdout"].encode()) + len(details["stderr"].encode()), 65536
    )
    self.assertTrue(details["stdout"].rstrip().endswith("TAIL"))
    self.assertIn("stderr output", details["stderr"])
    source = (
      "def main(count: int): return count\n"
      "main.__signature__ = __import__('inspect').Signature()\n"
    )
    saved = await self.create_updated(saved, source)
    result = await self.execute(saved, {"count": 2})
    self.assertEqual(result["error"]["code"], "python_binding", result)

  async def wait_test(self, test_id):
    import asyncio

    for _ in range(200):
      snapshot = (await self.client.get(f"/api/tools/tests/{test_id}")).json()["data"]
      if snapshot["status"] != "running":
        return snapshot["result"]
      await asyncio.sleep(0.02)
    self.fail("Python test did not finish")

  async def create_updated(self, saved, source):
    response = await self.client.put(
      f"/api/tools/{saved['data']['id']}",
      json={
        "definition": self.payload(source),
        "version": saved["version"],
      },
    )
    self.assertEqual(response.status_code, 204, response.text)
    return (await self.client.get(f"/api/tools/{saved['data']['id']}")).json()

  async def test_saved_source_is_reread_and_paths_are_anchored_to_configuration(self):
    import os

    saved = await self.create("def main(count: int): return count + 1\n")
    source_path = self.path.parent / saved["data"]["code_path"]
    source_path.write_text(
      "def main(count: int): return count + 10\n", encoding="utf-8"
    )
    previous_cwd = Path.cwd()
    try:
      os.chdir(self.path.parent)
      result = await self.execute(saved, {"count": 2})
    finally:
      os.chdir(previous_cwd)
    self.assertEqual(result["data"], 12, result)
    source_path.write_text("def main(other: str): return other\n", encoding="utf-8")
    self.assertEqual(
      (await self.execute(saved, {"count": 2}))["error"]["code"], "python_schema"
    )
    source_path.unlink()
    self.assertEqual(
      (await self.execute(saved, {"count": 2}))["error"]["code"], "python_source_read"
    )
    response = await self.client.get(f"/api/tools/{saved['data']['id']}")
    self.assertEqual(response.status_code, 503)
    raw = json.loads(self.path.read_text(encoding="utf-8"))
    for invalid_path in (
      "../outside.py",
      str(self.path),
      "config/tools/../outside.py",
      "elsewhere.py",
    ):
      with self.subTest(path=invalid_path):
        raw["tool_library"]["tools"][0]["code_path"] = invalid_path
        self.path.write_text(json.dumps(raw), encoding="utf-8")
        result = await self.execute(saved, {"count": 2})
        self.assertEqual(result["error"]["code"], "python_path")

  async def test_saved_execution_uses_loaded_snapshot_when_file_changes_before_dispatch(
    self,
  ):
    from unittest.mock import patch

    from shikigen.contracts.tool_execution import PythonToolExecution
    from shikigen.tools.python.execution import PythonAdapter

    source = "def main(): return 'loaded'\n"
    saved = await self.create(source)
    path = self.path.parent / saved["data"]["code_path"]
    execute = PythonAdapter.execute

    async def change_file_before_execution(adapter, execution, inputs, *, context):
      self.assertIsInstance(execution, PythonToolExecution)
      self.assertEqual(execution.source, source)
      path.write_text("def main(): return 'changed'\n", encoding="utf-8")
      return await execute(adapter, execution, inputs, context=context)

    with patch.object(PythonAdapter, "execute", new=change_file_before_execution):
      result = await self.execute(saved, {})
    self.assertEqual(result["status"], "success", result)
    self.assertEqual(result["data"], "loaded")
    self.assertEqual((await self.execute(saved, {}))["data"], "changed")

  async def test_source_commit_order_cleanup_and_drafts_preserve_saved_definition(self):
    from unittest.mock import patch

    saved = await self.create("def main(): return 'old'\n")
    code_path = self.path.parent / saved["data"]["code_path"]
    user_file = code_path.parent / "user-example.py"
    user_file.write_text("# keep", encoding="utf-8")
    before = self.path.read_bytes()
    replacement = self.payload("def main(): return 'new'\n")
    draft = await self.client.post(
      "/api/tools/tests",
      json={
        "definition": replacement,
        "tool_id": saved["data"]["id"],
        "inputs": {},
      },
    )
    result = await self.wait_test(draft.json()["data"]["test_id"])
    self.assertEqual(result["data"], "new")
    self.assertEqual(self.path.read_bytes(), before)
    self.assertEqual((await self.execute(saved, {}))["data"], "old")
    with patch("os.replace", side_effect=OSError("write failed")):
      failed = await self.client.put(
        f"/api/tools/{saved['data']['id']}",
        json={
          "definition": replacement,
          "version": saved["version"],
        },
      )
    self.assertEqual(failed.status_code, 503)
    self.assertEqual(self.path.read_bytes(), before)
    self.assertEqual(
      code_path.read_text(encoding="utf-8"), "def main(): return 'old'\n"
    )
    updated = await self.create_updated(saved, replacement["source"])
    self.assertFalse(code_path.exists())
    self.assertTrue(user_file.exists())
    self.assertEqual((await self.execute(updated, {}))["data"], "new")
    deleted = await self.client.request(
      "DELETE",
      f"/api/tools/{saved['data']['id']}",
      json={"version": updated["version"]},
    )
    self.assertEqual(deleted.status_code, 204)
    self.assertEqual(list(user_file.parent.glob("*.py")), [user_file])

  async def test_independent_interpreter_temporary_directories_and_timeout_cleanup(
    self,
  ):
    import sys

    source = (
      "import os, sys\ndef main():\n"
      "  return {'cwd': os.getcwd(), 'python': sys.executable,"
      " 'pid': os.getpid(), 'stdin': sys.stdin.read()}\n"
    )
    saved = await self.create(source)
    first = await self.execute(saved, {})
    second = await self.execute(saved, {})
    self.assertEqual(first["data"]["stdin"], "")
    self.assertEqual(first["data"]["python"], sys.executable)
    self.assertNotEqual(first["data"]["cwd"], second["data"]["cwd"])
    self.assertNotEqual(first["data"]["pid"], second["data"]["pid"])
    self.assertFalse(Path(first["data"]["cwd"]).exists())
    timed = await self.client.post(
      "/api/tools/tests",
      json={
        "definition": self.payload(
          "import time\ndef main():\n"
          "  print('started', flush=True)\n  time.sleep(10)\n",
          timeout_seconds=1,
          name="timeout_tool",
        ),
        "inputs": {},
      },
    )
    result = await self.wait_test(timed.json()["data"]["test_id"])
    self.assertEqual(result["status"], "timeout", result)
    self.assertIn("started", result["details"]["stdout"])
    self.assertIsInstance(result["details"]["exit_code"], int)

  async def test_multibyte_debug_tail_stays_within_limit_and_character_boundaries(self):
    saved = await self.create(
      "import sys\ndef main():\n  sys.stdout.write('中' * 30000)\n  return True\n"
    )
    result = await self.execute(saved, {})
    self.assertEqual(result["status"], "success", result)
    self.assertTrue(result["details"]["stdout_truncated"])
    self.assertLessEqual(len(result["details"]["stdout"].encode("utf-8")), 65536)
    self.assertEqual(set(result["details"]["stdout"]), {"中"})
