"""第 3 票：真实 Tauri 发送、刷新与审批全量重建。

先构建 frontend/dist。只复用逐字节匹配的既有 5173 静态服务；若端口空闲则
由共享夹具创建并清理服务。9238/45200 必须空闲，数据库与 Agent 使用临时目录。
"""

import json
import re
import socket
import unittest
from urllib.parse import urlsplit

import httpx
from client_acceptance import ClientAcceptance
from window_acceptance import REPO, WindowAcceptance, wait_until


class ReconstructionAcceptance(ClientAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-03/native"

  @classmethod
  def setUpClass(cls):
    for port in (9238, 45200):
      with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
          raise RuntimeError(f"测试端口 {port} 已占用，不能干扰既有进程")
    with httpx.Client(trust_env=False, timeout=2) as client:
      try:
        response = client.get("http://127.0.0.1:5173")
      except httpx.ConnectError:
        WindowAcceptance.setUpClass.__func__(cls)
        return
      response.raise_for_status()
      index = (REPO / "frontend/dist/index.html").read_bytes()
      if response.content != index:
        raise RuntimeError("5173 不是当前 dist，保留既有服务并停止实机验收")
      # 读取 index 中所有脚本/样式引用，避免旧服务冒充本次构建。
      for asset in re.findall(rb'(?:src|href)="(/assets/[^\"]+)"', index):
        path = asset.decode()
        if (
          client.get("http://127.0.0.1:5173" + path).content
          != (REPO / "frontend/dist" / path.lstrip("/")).read_bytes()
        ):
          raise RuntimeError(f"静态资源 {path} 与本次构建不一致")

  def test_interrupted_get_replay_verifies_identity_without_any_post(self):
    self.fixture.env["DESKTOP_TEST_APPROVAL"] = "1"
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    url = ready["base_url"]
    thread = self.client.post(url + "/api/threads").json()["thread_id"]
    sent = self.client.post(
      url + f"/api/threads/{thread}/stream",
      json={"message": "第3票审批恢复验收"},
      timeout=30,
    )
    sent.raise_for_status()
    frames = [
      json.loads(line[6:])
      for line in sent.text.splitlines()
      if line.startswith("data: ")
    ]
    run_id = frames[0]["run_id"]
    required = next(frame for frame in frames if frame.get("event_type") == "required")
    self.instrument_fetch()
    wait_until(lambda: "审批请求已核实，等待处理。" in self.body(), timeout=15)
    self.assertIn("等待审批", self.body())
    self.assertNotIn("审批尚未恢复", self.body())
    requests = self.evaluate("window.__requests")
    self.assertTrue(requests)
    self.assertTrue(all(item["method"] == "GET" for item in requests))
    observations = [
      item for item in requests if urlsplit(item["url"]).path.endswith("/stream")
    ]
    self.assertEqual(len(observations), 1)
    self.assertEqual(
      urlsplit(observations[0]["url"]).path,
      f"/api/threads/{thread}/runs/{run_id}/stream",
    )
    self.assertEqual(urlsplit(observations[0]["url"]).query, "")
    self.assertEqual(
      self.evaluate(
        "[...document.querySelectorAll('.message-text')]"
        ".filter(e => e.textContent.includes('第3票审批恢复验收')).length"
      ),
      1,
    )
    history = self.client.get(url + f"/api/threads/{thread}/messages").json()["data"]
    self.assertTrue(all(message["run_status"] == "interrupted" for message in history))
    self.record(
      ready=ready,
      thread=thread,
      run_id=run_id,
      required=required,
      requests=requests,
      history=history,
      body=self.body(),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  names = [
    "test_page_reads_persisted_messages_and_run_then_sends_only_on_click",
    "test_interrupted_get_replay_verifies_identity_without_any_post",
    "test_replayed_pause_cannot_override_current_resumed_run_status",
  ]
  suite = unittest.TestSuite(ReconstructionAcceptance(name) for name in names)
  result = unittest.TextTestRunner(verbosity=2).run(suite)
  raise SystemExit(0 if result.wasSuccessful() else 1)
