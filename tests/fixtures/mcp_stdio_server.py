"""可控 JSON-RPC stdio 对端，用于公开 API/桌面验收，不访问公网。"""

import json
import os
import sys
import time
from pathlib import Path

if os.getenv("MCP_FIXTURE_PID_FILE"):
  Path(os.environ["MCP_FIXTURE_PID_FILE"]).write_text(str(os.getpid()))

calls = 0
schema = {
  "type": "object",
  "properties": {"query": {"type": "string"}},
  "required": ["query"],
  "additionalProperties": False,
}


def tools():
  if os.getenv("MCP_FIXTURE_TOOLS"):
    return json.loads(os.environ["MCP_FIXTURE_TOOLS"])
  return [
    {
      "name": name,
      "title": "本地 " + name,
      "description": "stdio " + name,
      "inputSchema": schema
      if name != "unsupported"
      else {"type": "object", "oneOf": [{"required": ["a"]}]},
      **(
        {
          "outputSchema": {
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
          }
        }
        if name == "invalid_output"
        else {}
      ),
      "annotations": {"readOnlyHint": True},
      "x-discovery-calls": calls,
    }
    for name in (
      "search",
      "blocks",
      "fail",
      "invalid_output",
      "slow",
      "huge",
      "unsupported",
    )
  ]


for line in sys.stdin:
  message = json.loads(line)
  if "id" not in message:
    continue
  method = message["method"]
  if os.getenv("MCP_INITIALIZE_DELAY"):
    time.sleep(float(os.environ["MCP_INITIALIZE_DELAY"]))
  if method == "initialize":
    result = {
      "protocolVersion": "2025-11-25",
      "capabilities": {"tools": {}},
      "serverInfo": {"name": "fixture", "version": "1"},
    }
  elif method == "tools/list":
    result = {"tools": tools(), "_meta": {"fixture": True}}
    if os.getenv("MCP_FIXTURE_PAGINATE"):
      if message.get("params", {}).get("cursor") == "second":
        result["tools"] = tools()[1:]
      else:
        result["tools"] = tools()[:1]
        result["nextCursor"] = "second"
  elif method == "tools/call":
    if os.getenv("MCP_CALL_DELAY"):
      time.sleep(float(os.environ["MCP_CALL_DELAY"]))
    calls += 1
    params = message["params"]
    name = params["name"]
    if name == "protocol":
      print(
        json.dumps(
          {
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32602, "message": "fixture protocol failure"},
          }
        ),
        flush=True,
      )
      continue
    if name == "slow":
      time.sleep(60)
    result = {
      "content": [
        {"type": "text", "text": "first"},
        {"type": "image", "mimeType": "image/png", "data": "aGVsbG8="},
      ],
      "_meta": {"source": "fixture"},
      "vendor": {"complete": True},
      "isError": name == "fail",
    }
    if name not in ("blocks", "fail"):
      result["structuredContent"] = {
        "arguments": params["arguments"],
        "calls": calls,
        "pid": os.getpid(),
        "mode": os.getenv("MODE"),
        "cwd": os.getcwd(),
      }
    if name == "blocks":
      result["structuredContent"] = None
    if name == "huge":
      result["content"] = [{"type": "text", "text": "x" * (1024 * 1024 + 1)}]
  else:
    result = {}
  print(
    json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True
  )
