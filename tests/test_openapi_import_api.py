import json
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import httpx
import yaml
from shikigen.app_config import load_app_config
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime

from app.server import create_app


class OpenApiImportTests(unittest.IsolatedAsyncioTestCase):
  async def test_nullable_union_can_reference_both_value_and_null_schemas(self):
    for index, keyword in enumerate(("anyOf", "oneOf")):
      document = json.dumps(
        {
          "openapi": "3.1.2",
          "info": {"title": "Nullable refs", "version": "1"},
          "servers": [{"url": "https://example.test"}],
          "paths": {
            "/nullable": {
              "post": {
                "summary": "可空引用",
                "requestBody": {
                  "content": {
                    "application/json": {
                      "schema": {
                        keyword: [
                          {"$ref": "#/components/schemas/Value"},
                          {"$ref": "#/components/schemas/Null"},
                        ]
                      }
                    }
                  }
                },
              }
            }
          },
          "components": {
            "schemas": {
              "Value": {"type": "string", "minLength": 2, "enum": ["AB"]},
              "Null": {"type": "null"},
            }
          },
        }
      )
      candidate = (await self.preview(document))["operations"][0]
      self.assertEqual(candidate["errors"], [], candidate)
      self.assertEqual(
        candidate["definition"]["input_schema"]["properties"]["body"],
        {"type": ["string", "null"], "minLength": 2, "enum": ["AB", None]},
      )
      self.assertIn(
        "#/components/schemas/Null",
        candidate["definition"]["openapi_source"]["references"],
      )
      saved = await self.import_selection(document, [candidate], f"_nullref_{index}")
      self.assertEqual(saved.status_code, 201, saved.text)

  async def test_explicit_supported_dialects_are_distinct_from_custom_dialects(self):
    for index, dialect in enumerate(
      (
        "https://spec.openapis.org/oas/3.1/dialect/base",
        "https://json-schema.org/draft/2020-12/schema",
        "https://custom.invalid/dialect",
      )
    ):
      document = json.dumps(
        {
          "openapi": "3.1.2",
          "info": {"title": "Dialect", "version": "1"},
          "jsonSchemaDialect": dialect,
          "servers": [{"url": "https://example.test"}],
          "paths": {
            "/schema": {
              "post": {
                "summary": "方言",
                "requestBody": {
                  "content": {
                    "application/json": {
                      "schema": {
                        "$schema": dialect,
                        "type": "object",
                        "properties": {"value": {"type": "integer"}},
                      }
                    }
                  }
                },
              }
            }
          },
        }
      )
      candidate = (await self.preview(document))["operations"][0]
      if index == 2:
        self.assertIn("jsonSchemaDialect", " ".join(candidate["errors"]))
        continue
      self.assertEqual(candidate["errors"], [], candidate)
      saved = await self.import_selection(document, [candidate], f"_dialect_{index}")
      self.assertEqual(saved.status_code, 201, saved.text)

  async def test_security_overrides_anonymous_alternatives_and_target_conflicts(self):
    origin, requests = self.service()
    document = {
      "openapi": "3.1.2",
      "info": {"title": "Security", "version": "1"},
      "servers": [{"url": origin}],
      "security": [{"Header": []}],
      "components": {
        "securitySchemes": {
          "Header": {"type": "apiKey", "in": "header", "name": "X-Trace"},
          "Bearer": {"type": "http", "scheme": "bearer"},
          "DuplicateBearer": {"type": "http", "scheme": "bearer"},
          "OAuth": {"type": "oauth2", "flows": {}},
        }
      },
      "paths": {
        "/inherited": {
          "post": {
            "summary": "继承",
            "requestBody": {
              "content": {"application/json": {"schema": {"type": "object"}}}
            },
          }
        },
        "/alternatives": {
          "post": {"summary": "覆盖", "security": [{"OAuth": []}, {"Bearer": []}, {}]}
        },
        "/public": {"post": {"summary": "公开", "security": [{}]}},
        "/unsupported": {"post": {"summary": "未支持", "security": [{"OAuth": []}]}},
        "/combined_conflict": {
          "post": {
            "summary": "冲突",
            "security": [{"Bearer": [], "DuplicateBearer": []}],
          }
        },
        "/business_conflict": {
          "post": {
            "summary": "业务冲突",
            "parameters": [
              {"in": "header", "name": "x-trace", "schema": {"type": "string"}}
            ],
          }
        },
      },
    }
    text = yaml.safe_dump(document, sort_keys=False)
    inherited, alternatives, public, *blocked = (await self.preview(text))["operations"]
    self.assertEqual(inherited["definition"]["auth"][0]["name"], "X-Trace")
    self.assertEqual(alternatives["security_option"], "security_1")
    self.assertEqual(public["definition"]["auth"], [])
    for candidate in blocked:
      self.assertTrue(candidate["errors"], candidate)
      self.assertIn("security/", " ".join(candidate["errors"]))
    inherited["definition"]["auth"][0]["value"] = "header-secret"
    saved = await self.import_selection(text, [inherited])
    self.assertEqual(saved.status_code, 201, saved.text)
    tool_id = saved.json()["data"][0]["id"]
    result = await self.client.post(
      f"/api/tools/{tool_id}/execute", json={"inputs": {"body": {}}}
    )
    self.assertEqual(result.json()["data"]["status"], "success", result.text)
    self.assertEqual(requests[-1]["header"], "header-secret")
    selection = {
      "operation_key": alternatives["key"],
      "definition": {
        **alternatives["definition"],
        "name": "explicit_anonymous",
        "auth": [],
      },
    }
    before = (await self.client.get("/api/tools")).json()
    rejected = await self.client.post(
      "/api/tools/openapi/imports",
      json={
        "version": (await self.client.get("/api/tools")).json()["version"],
        "document": text,
        "tools": [{**selection, "security_option": "security_0"}],
      },
    )
    self.assertEqual(rejected.status_code, 422, rejected.text)
    self.assertEqual((await self.client.get("/api/tools")).json(), before)
    accepted = await self.client.post(
      "/api/tools/openapi/imports",
      json={
        "version": (await self.client.get("/api/tools")).json()["version"],
        "document": text,
        "tools": [{**selection, "security_option": "security_2"}],
      },
    )
    self.assertEqual(accepted.status_code, 201, accepted.text)

  async def test_nullable_unions_keep_constraints_and_only_accept_valid_requests(self):
    origin, requests = self.service()
    for index, (version, nullable) in enumerate(
      (
        ("3.0.4", {"type": "string", "nullable": True, "enum": ["A", None]}),
        ("3.1.2", {"type": ["string", "null"], "enum": ["A", None]}),
        ("3.1.2", {"anyOf": [{"type": "string", "enum": ["A"]}, {"type": "null"}]}),
        ("3.1.2", {"oneOf": [{"type": "string", "enum": ["A"]}, {"type": "null"}]}),
      )
    ):
      body = {
        "type": "object",
        "required": ["label", "score", "tags", "choice"],
        "minProperties": 4,
        "maxProperties": 5,
        "properties": {
          "label": {
            "type": "string",
            "minLength": 2,
            "maxLength": 4,
            "pattern": "^[A-Z]+$",
            "format": "email",
          },
          "score": {"type": "number", "minimum": 0, "maximum": 10, "multipleOf": 2},
          "tags": {
            "type": "array",
            "items": {"type": "integer", "minimum": 1},
            "minItems": 1,
            "maxItems": 2,
            "uniqueItems": True,
          },
          "choice": nullable,
        },
        "additionalProperties": {"type": "boolean"},
      }
      text = (json.dumps if index % 2 else yaml.safe_dump)(
        {
          "openapi": version,
          "info": {"title": "Nullable", "version": "1"},
          "servers": [{"url": origin}],
          "paths": {
            "/nullable": {
              "post": {
                "summary": "可空约束",
                "requestBody": {
                  "required": True,
                  "content": {"application/json": {"schema": body}},
                },
              }
            }
          },
        }
      )
      candidate = (await self.preview(text))["operations"][0]
      self.assertEqual(candidate["errors"], [], candidate)
      choice = candidate["definition"]["input_schema"]["properties"]["body"][
        "properties"
      ]["choice"]
      self.assertEqual(choice["type"], ["string", "null"])
      self.assertEqual(choice["enum"], ["A", None])
      saved = await self.import_selection(text, [candidate], f"_{index}")
      self.assertEqual(saved.status_code, 201, saved.text)
      tool_id = saved.json()["data"][0]["id"]
      good = {"label": "AB", "score": 4, "tags": [1], "choice": None}
      count = len(requests)
      invalid = [
        {},
        {"body": {}},
        *(
          {"body": {**good, **patch}}
          for patch in (
            {"label": "A"},
            {"label": "ABCDE"},
            {"label": "ab"},
            {"score": -2},
            {"score": 12},
            {"score": 3},
            {"score": "4"},
            {"tags": []},
            {"tags": [1, 2, 3]},
            {"tags": [1, 1]},
            {"tags": [0]},
            {"choice": "B"},
            {"extra": "wrong"},
            {"extra": True, "too_many": True},
          )
        ),
      ]
      for inputs in invalid:
        result = await self.client.post(
          f"/api/tools/{tool_id}/execute", json={"inputs": inputs}
        )
        self.assertEqual(result.json()["data"]["status"], "error", result.text)
      self.assertEqual(len(requests), count)
      result = await self.client.post(
        f"/api/tools/{tool_id}/execute", json={"inputs": {"body": good}}
      )
      self.assertEqual(result.json()["data"]["status"], "success", result.text)
      self.assertEqual(requests[-1]["body"], good)

  async def test_auth_alternatives_require_complete_selected_scheme_and_execute(self):
    origin, requests = self.service()
    document = json.dumps(
      {
        "openapi": "3.0.4",
        "info": {"title": "Auth", "version": "1"},
        "servers": [{"url": origin}],
        "security": [{"OAuth": []}, {"Token": [], "Key": []}],
        "components": {
          "securitySchemes": {
            "OAuth": {"type": "oauth2", "flows": {}},
            "Token": {"type": "http", "scheme": "bearer"},
            "Key": {"type": "apiKey", "in": "query", "name": "api_key"},
          }
        },
        "paths": {
          "/auth": {
            "post": {
              "summary": "认证接口",
              "parameters": [
                {"name": "business", "in": "query", "schema": {"type": "integer"}}
              ],
              "requestBody": {
                "content": {"application/json": {"schema": {"type": "object"}}}
              },
            }
          },
          "/public": {"post": {"summary": "公开接口", "security": []}},
        },
      }
    )
    secure, public = (await self.preview(document))["operations"]
    self.assertEqual(secure["errors"], [])
    self.assertEqual(secure["security_option"], "security_1")
    self.assertTrue(secure["security_options"][0]["errors"])
    self.assertEqual(len(secure["definition"]["auth"]), 2)
    self.assertEqual(public["definition"]["auth"], [])
    self.assertEqual(public["definition"]["openapi_source"]["security"], [])
    self.assertNotIn(
      "api_key",
      secure["definition"]["input_schema"]["properties"]["query"]["properties"],
    )
    before = (await self.client.get("/api/tools")).json()
    missing = await self.import_selection(document, [public, secure])
    self.assertEqual(missing.status_code, 422, missing.text)
    self.assertEqual((await self.client.get("/api/tools")).json(), before)
    for binding, secret in zip(
      secure["definition"]["auth"], ["Bearer token", "key value"], strict=True
    ):
      binding["value"] = secret
    saved = await self.import_selection(document, [secure])
    self.assertEqual(saved.status_code, 201, saved.text)
    tool_id = saved.json()["data"][0]["id"]
    executed = await self.client.post(
      f"/api/tools/{tool_id}/execute",
      json={"inputs": {"query": {"business": 7}, "body": {"ok": True}}},
    )
    self.assertEqual(executed.json()["data"]["status"], "success", executed.text)
    self.assertEqual(urlsplit(requests[0]["path"]).path, "/auth")
    self.assertEqual(
      parse_qs(urlsplit(requests[0]["path"]).query),
      {"business": ["7"], "api_key": ["key value"]},
    )
    self.assertEqual(requests[0]["authorization"], "Bearer token")
    self.assertEqual(requests[0]["body"], {"ok": True})
    secure["definition"]["auth"] = []
    downgrade = await self.import_selection(document, [secure], "_downgrade")
    self.assertEqual(downgrade.status_code, 422, downgrade.text)

  async def test_request_diagnostics_locate_unsupported_content_without_blocking_good(
    self,
  ):
    bad_schemas = {
      "external": ({"$ref": "https://never.invalid/schema"}, "$ref"),
      "missing": ({"$ref": "#/components/schemas/Missing"}, "Missing"),
      "cycle": ({"$ref": "#/components/schemas/Loop"}, "循环"),
      "union": ({"anyOf": [{"type": "string"}, {"type": "integer"}]}, "anyOf"),
      "intersection": ({"allOf": [{"type": "object"}]}, "allOf"),
      "overlapping_null": (
        {"oneOf": [{"type": ["string", "null"]}, {"type": "null"}]},
        "oneOf",
      ),
      "dialect": ({"$schema": "https://custom.invalid"}, "$schema"),
    }
    paths = {"/good": {"post": {"summary": "正常", "security": []}}}
    for name, (schema, _) in bad_schemas.items():
      paths["/" + name] = {
        "post": {
          "summary": name,
          "requestBody": {"content": {"application/json": {"schema": schema}}},
        }
      }
    for name, parameter in {
      "cookie": {"in": "cookie", "schema": {"type": "string"}},
      "object_query": {"in": "query", "schema": {"type": "object"}},
      "style": {"in": "query", "style": "spaceDelimited", "schema": {"type": "string"}},
      "reserved": {"in": "query", "allowReserved": True, "schema": {"type": "string"}},
      "content": {"in": "query", "content": {"application/json": {}}},
    }.items():
      paths["/" + name] = {
        "post": {"summary": name, "parameters": [{"name": "bad", **parameter}]}
      }
    paths["/form"] = {
      "post": {
        "summary": "表单",
        "requestBody": {
          "content": {"multipart/form-data": {"schema": {"type": "object"}}}
        },
      }
    }
    document = json.dumps(
      {
        "openapi": "3.1.0",
        "info": {"title": "Diagnostics", "version": "1"},
        "servers": [{"url": "https://example.test"}],
        "paths": paths,
        "components": {
          "schemas": {
            "Loop": {
              "type": "object",
              "properties": {"next": {"$ref": "#/components/schemas/Loop"}},
            }
          }
        },
      }
    )
    candidates = (await self.preview(document))["operations"]
    good = candidates[0]
    for candidate in candidates[1:]:
      with self.subTest(key=candidate["key"]):
        self.assertTrue(candidate["errors"], candidate)
        diagnostic = "；".join(candidate["errors"])
        self.assertIn(candidate["key"], diagnostic)
        self.assertIn("请", diagnostic)
        self.assertTrue("parameters/" in diagnostic or "requestBody/" in diagnostic)
        if candidate["path"][1:] in bad_schemas:
          self.assertIn(bad_schemas[candidate["path"][1:]][1], diagnostic)
        rejected = await self.import_selection(document, [good, candidate])
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual((await self.client.get("/api/tools")).json()["data"], [])
    accepted = await self.import_selection(document, [good])
    self.assertEqual(accepted.status_code, 201, accepted.text)

  async def test_internal_request_references_preserve_nested_constraints_and_source(
    self,
  ):
    document = {
      "openapi": "3.1.0",
      "info": {"title": "References", "version": "1"},
      "servers": [{"url": "https://example.test"}],
      "paths": {
        "/items/{id}": {
          "post": {
            "summary": "引用请求",
            "parameters": [{"$ref": "#/components/parameters/Id"}],
            "requestBody": {"$ref": "#/components/requestBodies/Create"},
          }
        }
      },
      "components": {
        "parameters": {
          "Id": {
            "name": "id",
            "in": "path",
            "required": True,
            "schema": {"type": "integer", "minimum": 1},
          }
        },
        "requestBodies": {
          "Create": {
            "required": True,
            "content": {
              "application/xml": {},
              "application/json": {
                "schema": {"$ref": "#/components/schemas/Item"},
                "example": {"children": [{"label": "AB"}]},
              },
            },
          }
        },
        "schemas": {
          "Item": {
            "type": "object",
            "required": ["children"],
            "properties": {
              "children": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {"$ref": "#/components/schemas/Child"},
              }
            },
            "additionalProperties": {"type": "integer", "minimum": 0},
          },
          "Child": {
            "type": "object",
            "required": ["label"],
            "properties": {
              "label": {
                "type": "string",
                "minLength": 2,
                "maxLength": 4,
                "pattern": "^[A-Z]+$",
                "format": "custom-format",
                "description": "名称",
                "examples": ["AB"],
              }
            },
            "additionalProperties": False,
          },
          "Unused": {"$ref": "https://never-fetched.invalid/schema"},
        },
      },
    }
    text = yaml.safe_dump(document, sort_keys=False)
    candidate = (await self.preview(text))["operations"][0]
    self.assertEqual(candidate["errors"], [])
    schema = candidate["definition"]["input_schema"]
    body = schema["properties"]["body"]
    self.assertEqual(schema["required"], ["path", "body"])
    self.assertEqual(body["additionalProperties"], {"type": "integer", "minimum": 0})
    self.assertEqual(
      body["properties"]["children"]["items"],
      document["components"]["schemas"]["Child"],
    )
    self.assertEqual(body["example"], {"children": [{"label": "AB"}]})
    self.assertEqual(
      candidate["definition"]["openapi_source"]["references"][
        "#/components/schemas/Item"
      ],
      document["components"]["schemas"]["Item"],
    )
    saved = await self.import_selection(text, [candidate])
    self.assertEqual(saved.status_code, 201, saved.text)

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
    document["paths"]["/items"]["post"]["responses"]["201"]["content"][
      "application/json"
    ]["schema"] = {"$schema": [], "type": "object"}
    unusable = (await self.preview(json.dumps(document)))["operations"][0]
    self.assertEqual(unusable["errors"], [])
    self.assertIsNone(unusable["definition"]["output_schema"])
    self.assertTrue(unusable["warnings"])

  async def import_selection(self, document, candidates, suffix=""):
    return await self.client.post(
      "/api/tools/openapi/imports",
      json={
        "version": (await self.client.get("/api/tools")).json()["version"],
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
        "version": (await self.client.get("/api/tools")).json()["version"],
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
        if self.headers.get("Authorization"):
          data["authorization"] = self.headers["Authorization"]
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
        "version": (await self.client.get("/api/tools")).json()["version"],
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
