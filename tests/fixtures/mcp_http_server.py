"""可控 Streamable HTTP JSON-RPC 对端，支持 JSON/SSE 与会话终止。"""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from uuid import uuid4


class McpHttpServer:
  def __init__(self):
    self.requests: list[dict] = []
    self.sessions: set[str] = set()
    self.calls = 0
    self.authorization: str | None = None
    self.slow_started = Event()
    self.release_slow = Event()
    self.slow_delete = False
    self.stop = Event()
    self.pending_results: dict[str, dict] = {}
    fixture = self

    class Handler(BaseHTTPRequestHandler):
      protocol_version = "HTTP/1.1"

      def handle(self):
        try:
          super().handle()
        except (ConnectionResetError, ConnectionAbortedError):
          # 超时/取消测试会主动断开本次 TCP 连接。
          pass

      def reply(
        self,
        status,
        data=None,
        *,
        session=None,
        sse=False,
        content_type=None,
        event_id=None,
      ):
        body = json.dumps(data).encode() if data is not None else b""
        if sse:
          body = b"event: message\ndata: " + body + b"\n\n"
          if event_id:
            body = b"id: " + event_id.encode() + b"\n" + body
        self.send_response(status)
        self.send_header(
          "Content-Type",
          content_type or ("text/event-stream" if sse else "application/json"),
        )
        self.send_header("Content-Length", str(len(body)))
        if session:
          self.send_header("Mcp-Session-Id", session)
        self.end_headers()
        try:
          self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
          pass

      def record(self, message=None):
        fixture.requests.append(
          {
            "method": self.command,
            "path": self.path,
            "message": message,
            "session": self.headers.get("Mcp-Session-Id"),
            "authorization": self.headers.get("Authorization"),
            "last_event_id": self.headers.get("Last-Event-ID"),
          }
        )

      def do_GET(self):
        self.record()
        if self.path == "/resume" and self.headers.get("Last-Event-ID") == "recover":
          result = fixture.pending_results.pop(self.headers.get("Mcp-Session-Id"))
          self.reply(200, result, sse=True)
          return
        self.reply(405)

      def do_DELETE(self):
        self.record()
        fixture.sessions.discard(self.headers.get("Mcp-Session-Id"))
        if not fixture.slow_delete:
          self.reply(204)
          return
        self.send_response(200)
        self.send_header("Content-Length", "40")
        self.end_headers()
        try:
          for _ in range(40):
            self.wfile.write(b"x")
            self.wfile.flush()
            if fixture.stop.wait(0.1):
              break
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
          pass

      def do_POST(self):
        message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.record(message)
        if (
          fixture.authorization
          and self.headers.get("Authorization") != fixture.authorization
        ):
          self.reply(401, {"error": "authorization required"})
          return
        if self.path == "/unavailable":
          self.reply(503, {"error": "offline"})
          return
        if self.path in ("/malformed", "/html"):
          self.reply(
            200,
            {"unexpected": "not JSON-RPC"},
            content_type="text/html" if self.path == "/html" else None,
          )
          return
        if "id" not in message:
          self.reply(202)
          return
        method = message["method"]
        if self.path == "/protocol":
          self.reply(
            200,
            {
              "jsonrpc": "2.0",
              "id": message["id"],
              "error": {
                "code": -32600,
                "message": "fixture initialization protocol failure",
              },
            },
          )
          return
        session = self.headers.get("Mcp-Session-Id")
        if method == "initialize":
          if self.path == "/slow":
            time.sleep(2)
          session = str(uuid4())
          fixture.sessions.add(session)
          result = {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "http-fixture", "version": "1"},
          }
        elif method == "tools/list":
          if self.path == "/resume":
            fixture.pending_results[session] = {
              "jsonrpc": "2.0",
              "id": message["id"],
              "result": {"tools": []},
            }
            self.reply(
              200,
              {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"},
              sse=True,
              event_id="recover",
            )
            return
          if self.path == "/sse-eof":
            self.reply(
              200,
              {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"},
              sse=True,
            )
            return
          result = {
            "tools": [
              {
                "name": name,
                "description": "远程 " + name,
                "inputSchema": {
                  "type": "object",
                  "properties": {"query": {"type": "string"}},
                  "required": ["query"],
                  "additionalProperties": False,
                },
                "x-business-calls": fixture.calls,
              }
              for name in ("search", "blocks", "fail", "protocol", "slow", "huge")
            ]
          }
        elif method == "tools/call":
          fixture.calls += 1
          params = message["params"]
          name = params["name"]
          if name == "protocol":
            self.reply(
              200,
              {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": -32602, "message": "fixture protocol failure"},
              },
            )
            return
          if name == "slow":
            fixture.slow_started.set()
            fixture.release_slow.wait(5)
          result = {
            "content": [
              {"type": "text", "text": "first"},
              {"type": "image", "mimeType": "image/png", "data": "aGVsbG8="},
            ],
            "_meta": {"source": "http-fixture"},
            "vendor": {"complete": True},
            "isError": name == "fail",
          }
          if name not in ("blocks", "fail"):
            result["structuredContent"] = {
              "arguments": params["arguments"],
              "session": session,
            }
          if name == "huge":
            result["content"] = [{"type": "text", "text": "x" * (1024 * 1024 + 1)}]
        else:
          result = {}
        self.reply(
          200,
          {"jsonrpc": "2.0", "id": message["id"], "result": result},
          session=session if method == "initialize" else None,
          sse=self.path == "/sse",
        )

      def log_message(self, format, *args):
        pass

    self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    self.thread = Thread(target=self.server.serve_forever, daemon=True)
    self.thread.start()
    self.url = f"http://127.0.0.1:{self.server.server_port}"

  def close(self):
    self.stop.set()
    self.release_slow.set()
    self.server.shutdown()
    self.server.server_close()
    self.thread.join()
