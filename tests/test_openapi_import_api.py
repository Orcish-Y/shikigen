import json
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx
import yaml
from shikigen.app_config import load_app_config
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime

from app.server import create_app


class OpenApiImportTests(unittest.IsolatedAsyncioTestCase):
  async def test_server_variable_cannot_be_mistaken_for_operation_path_parameter(self):
    document = json.dumps(
      {
        "openapi": "3.1.0",
        "info": {"title": "Variables", "version": "1"},
        "servers": [{"url": "https://example.test/{id}"}],
        "paths": {
          "/items/{id}": {
            "get": {
              "summary": "商品",
              "parameters": [
                {
                  "in": "path",
                  "name": "id",
                  "required": True,
                  "schema": {"type": "string"},
                }
              ],
            }
          }
        },
      }
    )
    candidate = (await self.preview(document))["operations"][0]
    rejected = await self.import_selection(document, [candidate])
    self.assertEqual(rejected.status_code, 422, rejected.text)
    self.assertIn("服务器变量", rejected.text)
    self.assertEqual((await self.client.get("/api/tools")).json()["data"], [])
    candidate["definition"]["url"] = "https://example.test/resolved/items/{id}"
    accepted = await self.import_selection(document, [candidate])
    self.assertEqual(accepted.status_code, 201, accepted.text)

  async def test_output_prefill_requires_one_distinct_success_schema(self):
    response = {
      "description": "ok",
      "content": {
        "application/json": {
          "schema": {"type": "object", "properties": {"id": {"type": "integer"}}}
        }
      },
    }
    document = {
      "openapi": "3.1.0",
      "info": {"title": "Outputs", "version": "1"},
      "paths": {
        "/items": {
          "post": {"summary": "商品", "responses": {"200": response, "201": response}}
        }
      },
    }
    same = (await self.preview(json.dumps(document)))["operations"][0]
    self.assertEqual(
      same["definition"]["output_schema"]["properties"], {"id": {"type": "integer"}}
    )
    document["paths"]["/items"]["post"]["responses"]["201"] = {
      "description": "other",
      "content": {"application/json": {"schema": {"type": "string"}}},
    }
    different = (await self.preview(json.dumps(document)))["operations"][0]
    self.assertIsNone(different["definition"]["output_schema"])
    self.assertTrue(different["warnings"])

  async def import_selection(self, document, candidates, suffix=""):
    return await self.client.post(
      "/api/tools/openapi/imports",
      json={
        "document": document,
        "tools": [
          {
            "operation_key": item["key"],
            "definition": {
              **item["definition"],
              "name": f"selected_{index}{suffix}",
            },
          }
          for index, item in enumerate(candidates)
        ],
      },
    )

  async def test_yaml_versions_servers_overrides_arrays_and_reimport(self):
    origin, requests = self.service()
    for index, version in enumerate(("3.0.4", "3.1.2")):
      nullable = (
        {"type": "string", "nullable": True}
        if index == 0
        else {"type": ["string", "null"]}
      )
      document = yaml.safe_dump(
        {
          "openapi": version,
          "info": {"title": "YAML", "version": "1"},
          "servers": [{"url": origin + "/root"}],
          "paths": {
            "/root": {"post": {"summary": "根级", "responses": {}}},
            "/path": {
              "servers": [{"url": origin + "/path-server"}],
              "post": {"summary": "路径级"},
            },
            "/selected": {
              "servers": [{"url": "https://ignored.invalid"}],
              "parameters": [
                {
                  "name": "limit",
                  "in": "query",
                  "required": True,
                  "schema": {"type": "integer"},
                }
              ],
              "post": {
                "summary": "接口级",
                "servers": [
                  {"url": origin + "/operation"},
                  {"url": origin + "/alternative"},
                ],
                "parameters": [
                  {"name": "limit", "in": "query", "schema": nullable},
                  {
                    "name": "tags",
                    "in": "query",
                    "explode": False,
                    "schema": {"type": "array", "items": {"type": "string"}},
                  },
                ],
                "requestBody": {
                  "content": {"application/json": {"schema": {"type": "object"}}}
                },
              },
            },
          },
        },
        sort_keys=False,
      )
      preview = await self.preview(document)
      root, path, selected = preview["operations"]
      self.assertEqual(root["definition"]["url"], origin + "/root/root")
      self.assertEqual(path["definition"]["url"], origin + "/path-server/path")
      self.assertEqual(selected["definition"]["url"], origin + "/operation/selected")
      self.assertEqual(len(selected["servers"]), 2)
      query = selected["definition"]["input_schema"]["properties"]["query"]
      self.assertNotIn("required", query)
      self.assertEqual(query["properties"]["limit"]["type"], ["string", "null"])
      first = await self.import_selection(document, [selected], f"_{index}")
      self.assertEqual(first.status_code, 201, first.text)
      before = (await self.client.get("/api/tools")).json()["data"]
      again = await self.import_selection(document, [selected], f"_{index}_again")
      self.assertEqual(again.status_code, 201, again.text)
      self.assertNotEqual(first.json()["data"][0]["id"], again.json()["data"][0]["id"])
      after = (await self.client.get("/api/tools")).json()["data"]
      self.assertEqual(after[:-1], before)
      executed = await self.client.post(
        f"/api/tools/{first.json()['data'][0]['id']}/execute",
        json={"inputs": {"query": {"limit": "q", "tags": ["a", "b"]}, "body": {}}},
      )
      self.assertEqual(executed.json()["data"]["status"], "success", executed.text)
      self.assertEqual(requests[-1]["path"], "/operation/selected?limit=q&tags=a%2Cb")

  async def test_only_selected_supported_operations_save_and_failed_batch_is_atomic(
    self,
  ):
    basic = {"summary": "普通接口", "description": "用途", "responses": {}}
    document = json.dumps(
      {
        "openapi": "3.1.0",
        "info": {"title": "Scope", "version": "1"},
        "servers": [{"url": "https://example.test"}],
        "security": [{"key": []}],
        "paths": {
          "/good": {"get": {**basic, "security": []}},
          "/secure": {"get": basic},
          "/ref": {
            "get": {
              **basic,
              "security": [],
              "parameters": [{"$ref": "#/components/parameters/id"}],
            }
          },
          "/duplicate": {
            "get": {
              **basic,
              "security": [],
              "parameters": [
                {"in": "query", "name": "id", "schema": {"type": "string"}}
              ]
              * 2,
            }
          },
          "/complex": {
            "get": {
              **basic,
              "security": [],
              "parameters": [
                {
                  "in": "query",
                  "name": "id",
                  "schema": {"oneOf": [{"type": "string"}, {"type": "number"}]},
                }
              ],
            }
          },
        },
      }
    )
    candidates = (await self.preview(document))["operations"]
    self.assertEqual(candidates[0]["errors"], [])
    for item in candidates[1:]:
      self.assertTrue(item["errors"], item)
    before = (await self.client.get("/api/tools")).json()
    for invalid in candidates[1:]:
      response = await self.import_selection(document, [candidates[0], invalid])
      self.assertEqual(response.status_code, 422, response.text)
      self.assertEqual((await self.client.get("/api/tools")).json(), before)
    # 后一个工具违反名称约束时，前一个也不能写入。
    selections = [
      {
        "operation_key": candidates[0]["key"],
        "definition": {**candidates[0]["definition"], "name": "duplicate"},
      }
    ]
    other = json.loads(document)
    other["paths"]["/second"] = other["paths"]["/good"]
    response = await self.client.post(
      "/api/tools/openapi/imports",
      json={
        "document": json.dumps(other),
        "tools": selections + [{**selections[0], "operation_key": "GET /second"}],
      },
    )
    self.assertEqual(response.status_code, 409, response.text)
    self.assertEqual((await self.client.get("/api/tools")).json(), before)
    response = await self.import_selection(document, [candidates[0]])
    self.assertEqual(response.status_code, 201, response.text)
    self.assertEqual(len((await self.client.get("/api/tools")).json()["data"]), 1)

  async def test_document_errors_and_address_completion(self):
    for document in (
      "invalid: [",
      "https://example.test/openapi.json",
      "openapi: 2.0\npaths: {}",
      "openapi: 3.2.0\npaths: {}",
      "openapi: 3.0.3\npaths: {}\npaths: {}",
      "openapi: 3.1.0\ninfo: []\npaths: {}",
    ):
      response = await self.client.post(
        "/api/tools/openapi/preview", json={"document": document}
      )
      self.assertEqual(response.status_code, 422, response.text)
    for server in ("/relative", "https://{host}/v1", "https://example.test/{region}"):
      document = json.dumps(
        {
          "openapi": "3.0.3",
          "info": {"title": "Incomplete", "version": "1"},
          "servers": [{"url": server}],
          "paths": {"/items": {"get": {"summary": "商品"}}},
        }
      )
      candidate = (await self.preview(document))["operations"][0]
      self.assertEqual(candidate["errors"], [])
      self.assertTrue(candidate["configuration_errors"])
      rejected = await self.import_selection(document, [candidate])
      self.assertEqual(rejected.status_code, 422, rejected.text)
      candidate["definition"]["url"] = "https://example.test/v1/items"
      accepted = await self.import_selection(document, [candidate], str(len(server)))
      self.assertEqual(accepted.status_code, 201, accepted.text)

  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    config = Path(directory.name) / "config.json"
    config.write_text('{"model":{},"mcp":{}}', encoding="utf-8")
    store = await ChatStore.open(Path(directory.name) / "test.db")
    self.addAsyncCleanup(store.close)
    runtime = assemble_runtime(
      config=load_app_config(config), agent=None, chat_store=store
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

  def service(self):
    requests = []

    class Handler(BaseHTTPRequestHandler):
      def do_POST(self):
        data = {
          "path": self.path,
          "header": self.headers.get("X-Trace"),
          "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
        }
        requests.append(data)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

      def log_message(self, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    self.addCleanup(server.server_close)
    self.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_port}", requests

  async def preview(self, document):
    response = await self.client.post(
      "/api/tools/openapi/preview", json={"document": document}
    )
    self.assertEqual(response.status_code, 200, response.text)
    return response.json()["data"]

  async def test_json_import_edit_and_execute_preserve_parameter_identity(self):
    origin, requests = self.service()
    document = json.dumps(
      {
        "openapi": "3.0.3",
        "info": {"title": "Store", "version": "1"},
        "servers": [{"url": origin}],
        "paths": {
          "/orders/{id}": {
            "post": {
              "operationId": "create-order",
              "summary": "创建订单",
              "description": "提交商品",
              "parameters": [
                {
                  "name": "id",
                  "in": "path",
                  "required": True,
                  "schema": {"type": "integer"},
                },
                {
                  "name": "id",
                  "in": "query",
                  "schema": {"type": "string", "example": "q"},
                },
                {"name": "X-Trace", "in": "header", "schema": {"type": "string"}},
              ],
              "requestBody": {
                "required": True,
                "content": {
                  "application/json": {
                    "schema": {
                      "type": "object",
                      "properties": {
                        "items": {
                          "type": "array",
                          "items": {
                            "type": "object",
                            "properties": {
                              "sku": {"type": "string", "description": "商品"}
                            },
                            "required": ["sku"],
                          },
                        }
                      },
                      "required": ["items"],
                    }
                  }
                },
              },
              "responses": {
                "200": {
                  "description": "ok",
                  "content": {
                    "application/json": {
                      "schema": {
                        "type": "object",
                        "properties": {"unknown": {"type": "string"}},
                        "required": ["unknown"],
                      }
                    }
                  },
                }
              },
            }
          }
        },
      }
    )
    preview = await self.preview(document)
    candidate = preview["operations"][0]
    self.assertEqual(candidate["name_hint"], "create-order")
    self.assertEqual(candidate["errors"], [])
    self.assertEqual(candidate["definition"]["url"], origin + "/orders/{id}")
    self.assertEqual((await self.client.get("/api/tools")).json()["data"], [])
    self.assertEqual(requests, [])
    definition = {**candidate["definition"], "name": "create_order"}
    response = await self.client.post(
      "/api/tools/openapi/imports",
      json={
        "document": document,
        "tools": [{"operation_key": candidate["key"], "definition": definition}],
      },
    )
    self.assertEqual(response.status_code, 201, response.text)
    tool_id = response.json()["data"][0]["id"]
    saved = (await self.client.get(f"/api/tools/{tool_id}")).json()
    self.assertEqual(saved["data"]["kind"], "http")
    self.assertEqual(
      saved["data"]["openapi_source"]["operation"]["summary"], "创建订单"
    )
    self.assertEqual(requests, [])
    definition.update(display_name="修改后的订单", name="renamed_order")
    definition.pop("openapi_source")
    updated = await self.client.put(
      f"/api/tools/{tool_id}",
      json={"definition": definition, "version": saved["version"]},
    )
    self.assertEqual(updated.status_code, 204, updated.text)
    reread = (await self.client.get(f"/api/tools/{tool_id}")).json()["data"]
    self.assertEqual(reread["openapi_source"], saved["data"]["openapi_source"])
    result = await self.client.post(
      f"/api/tools/{tool_id}/execute",
      json={
        "inputs": {
          "path": {"id": 42},
          "query": {"id": "query-value"},
          "headers": {"X-Trace": "trace"},
          "body": {"items": [{"sku": "A"}]},
        }
      },
    )
    self.assertEqual(result.json()["data"]["status"], "success", result.text)
    self.assertEqual(
      requests,
      [
        {
          "path": "/orders/42?id=query-value",
          "header": "trace",
          "body": {"items": [{"sku": "A"}]},
        }
      ],
    )
    self.assertEqual(
      (await self.client.get(f"/api/tools/{tool_id}")).json()["data"]["name"],
      "renamed_order",
    )
