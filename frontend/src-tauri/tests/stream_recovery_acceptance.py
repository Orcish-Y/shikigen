"""票据 05：真实 Tauri、公开传输故障与后台运行事实。

只在浏览器 fetch 网络边界制造断流／HTTP 读取故障，产品状态层无测试钩子。
共享 5173/9238/45200 夹具，必须与其他原生验收串行执行。
"""

import time
import unittest

from run_reconstruction_acceptance import ReconstructionAcceptance
from window_acceptance import REPO, wait_until


class StreamRecoveryAcceptance(ReconstructionAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-05/native"

  def instrument(self):
    self.call("Page.enable")
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source="""
      window.__requests = [];
      const original = window.fetch.bind(window);
      window.fetch = async (url, init) => {
        const path = new URL(String(url)).pathname;
        const method = init?.method || 'GET';
        window.__requests.push({path, method, at:performance.now()});
        if (method === 'GET' && path.endsWith('/stream') && window.__failGets > 0) {
          window.__failGets--;
          return new Response(JSON.stringify({detail:'验收读取故障'}), {
            status:window.__getStatus || 503,
            headers:{'Retry-After':'2'}
          });
        }
        const response = await original(url, init);
        if (method !== 'POST' || !path.endsWith('/stream') || !window.__dropPost)
          return response;
        window.__dropPost = false;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const body = new ReadableStream({async start(controller) {
          let buffer = '';
          try {
            while (true) {
              const {value, done} = await reader.read();
              if (done) throw new Error('metadata 前未返回完整帧');
              buffer += decoder.decode(value, {stream:true}).replace(/\\r\\n/g,'\\n');
              const end = buffer.indexOf('\\n\\n');
              if (end < 0) continue;
              const frame = buffer.slice(0,end+2);
              if (!frame.includes('event: metadata'))
                throw new Error('首帧不是 metadata');
              controller.enqueue(new TextEncoder().encode(frame));
              controller.close();
              await reader.cancel();
              break;
            }
          } catch (error) {controller.error(error);}
        }});
        return new Response(body,{headers:response.headers});
      };
      """,
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__requests)"))
    wait_until(lambda: "从一个想法开始" in self.body())

  def start_fault(self, status, failures):
    self.fixture.env["DESKTOP_TEST_RESIDENT_TASK"] = "1"
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.click("新建")
    wait_until(lambda: "从一个想法开始" in self.body())
    self.instrument()
    thread = self.evaluate(
      "document.querySelector('.session[aria-current=true]').title"
    ).split("会话 ID：")[-1]
    self.evaluate(
      f"window.__dropPost=true; window.__getStatus={status}; "
      f"window.__failGets={failures}"
    )
    self.send("第5票观察恢复原文")
    wait_until(lambda: "等待重连" in self.body())
    self.set_draft("保留下一条草稿")
    wait_until(lambda: "自动恢复已停止" in self.body(), timeout=20)
    return host, ready, thread

  def run_requests(self):
    return self.evaluate("window.__requests.filter(r=>r.path.endsWith('/stream'))")

  def test_bounded_get_recovery_then_manual_query_and_reconnect(self):
    host, ready, thread = self.start_fault(503, 3)
    requests = self.run_requests()
    self.assertEqual([r["method"] for r in requests], ["POST", "GET", "GET", "GET"])
    self.assertGreaterEqual(requests[1]["at"] - requests[0]["at"], 990)
    self.assertGreaterEqual(requests[2]["at"] - requests[1]["at"], 1990)
    self.assertGreaterEqual(requests[3]["at"] - requests[2]["at"], 4990)
    history_url = ready["base_url"] + f"/api/threads/{thread}/messages"
    history = self.client.get(history_url).json()["data"]
    users = [m for m in history if m["content"]["type"] == "human"]
    self.assertEqual(len(users), 1)
    run_id = users[0]["run_id"]
    snapshot = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/runs/{run_id}"
    ).json()["data"]
    self.assertEqual(snapshot["status"], "running")
    self.assertIn("连接异常不代表运行失败", self.body())
    self.assertIn("第5票观察恢复原文", self.body())
    self.assertNotIn("从一个想法开始", self.body())
    self.assertEqual(
      self.evaluate("document.getElementById('message-draft').value"), "保留下一条草稿"
    )
    self.screenshot()
    (self.artifacts / "recovery-stopped.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.click("查询状态")
    wait_until(lambda: "正在查询状态" not in self.body())
    self.assertEqual(len(self.run_requests()), 4)
    self.click("重新连接")
    # 第二次点击不可并发建立连接。
    self.evaluate(
      "document.querySelector('[aria-label=\"运行观察恢复\"] button')?.click()"
    )
    wait_until(lambda: "观察已建立" in self.body())
    self.assertEqual(len(self.run_requests()), 5)
    (self.root / "continue-task").touch()
    wait_until(lambda: "已完成" in self.body(), timeout=20)
    wait_until(lambda: "后台任务已完成" in self.body())
    self.assertIn("观察正常结束", self.body())
    final = self.client.get(history_url).json()["data"]
    self.assertEqual(len([m for m in final if m["content"]["type"] == "human"]), 1)
    self.assertEqual(
      self.evaluate("document.getElementById('message-draft').value"), "保留下一条草稿"
    )
    self.record(
      ready=ready,
      thread=thread,
      run_id=run_id,
      history=final,
      initial_requests=requests,
      requests=self.evaluate("window.__requests"),
      snapshot=snapshot,
      body=self.body(),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_protocol_http_400_stops_without_extra_get_or_run_error(self):
    host, ready, thread = self.start_fault(400, 1)
    self.assertIn("HTTP 400", self.body())
    time.sleep(1.1)
    self.assertEqual([r["method"] for r in self.run_requests()], ["POST", "GET"])
    history = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    self.assertTrue(history)
    self.assertEqual(history[-1]["run_status"], "running")
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent.trim()"),
      "运行中",
    )
    self.assertEqual(
      self.evaluate("document.getElementById('message-draft').value"), "保留下一条草稿"
    )
    self.record(
      ready=ready,
      thread=thread,
      history=history,
      requests=self.evaluate("window.__requests"),
      body=self.body(),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  names = [
    "test_bounded_get_recovery_then_manual_query_and_reconnect",
    "test_protocol_http_400_stops_without_extra_get_or_run_error",
  ]
  suite = unittest.TestSuite(StreamRecoveryAcceptance(name) for name in names)
  result = unittest.TextTestRunner(verbosity=2).run(suite)
  raise SystemExit(0 if result.wasSuccessful() else 1)
