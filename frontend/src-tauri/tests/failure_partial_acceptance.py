"""第 11 票：真实 Tauri 失败保存、完整原因、重开和草稿。"""

import unittest

from desktop_failure_fixtures import BODY, ERROR
from message_drafts_acceptance import MessageDraftAcceptance
from window_acceptance import REPO, wait_until


class FailurePartialAcceptance(MessageDraftAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-11/native"

  def setUp(self):
    super().setUp()
    bootstrap = self.root / "app/desktop.py"
    bootstrap.write_text(
      bootstrap.read_text(encoding="utf-8").replace(
        "from runtime_fixtures import deterministic_agent",
        "from desktop_failure_fixtures import failure_agent as deterministic_agent",
      ),
      encoding="utf-8",
    )

  def test_failure_saves_original_body_and_reason_across_native_restart(self):
    host, ready, thread = self.start_empty()
    self.send("实际执行失败也需要完整保存")
    wait_until(lambda: (self.root / "failure-text-ready").exists())
    wait_until(lambda: "最后一段失败前已接入正文" in self.body())
    self.set_draft("失败时的下一条草稿")
    self.assertIn("运行中", self.body())
    before = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    self.assertEqual(len(before), 1)
    self.assertNotIn("因失败中止", self.body())
    (self.root / "allow-failure-model").touch()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge')?.textContent")
        == "运行失败"
      )
    )
    wait_until(lambda: "因失败中止" in self.body())
    self.assertEqual(
      self.evaluate(
        "getComputedStyle(document.querySelector('.generation-error')).color"
      ),
      "rgb(185, 28, 28)",
    )
    wait_until(lambda: "末尾错误原文" in self.body())
    history = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    self.assertEqual(len(history), 2)
    ai = history[-1]
    self.assertEqual(ai["content"]["content"], BODY)
    self.assertEqual(ai["content"]["generation_status"], "error")
    self.assertEqual(ai["content"]["tool_calls"], [])
    self.assertEqual(history[0]["content"], before[0]["content"])
    self.assertEqual(self.draft(), "失败时的下一条草稿")
    self.assertEqual(self.evaluate("window.__sends.length"), 1)
    self.assertNotIn("生成中 · 尚未保存", self.body())
    self.assertNotIn("因取消中止", self.body())
    run_id = ai["run_id"]
    snapshot = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/runs/{run_id}"
    ).json()["data"]
    self.assertEqual(snapshot["error"], ERROR)
    self.assertEqual(snapshot["error_code"], "execution_failed")
    self.assertEqual(
      self.evaluate("document.querySelector('[aria-label=失败原因]').textContent"),
      ERROR,
    )
    self.assertTrue(
      self.evaluate(
        "(() => { const p=document.querySelector('[aria-label=失败原因]');"
        " return p.scrollHeight > p.clientHeight; })()"
      )
    )
    self.evaluate(
      "Object.defineProperty(navigator,'clipboard',{configurable:true,value:{"
      "writeText:async text=>{window.__copied=text}}})"
    )
    self.evaluate(
      "document.querySelector('[aria-label=运行失败原因]"
      " .block-heading button[aria-label=复制]').click()"
    )
    wait_until(lambda: self.evaluate("window.__copied") == ERROR)
    self.evaluate(
      "document.querySelector('[aria-label=运行失败原因]"
      " .block-heading button').click()"
    )
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('dialog[open]'))"))
    self.assertEqual(
      self.evaluate(
        "document.querySelector('dialog[open] .content-viewer pre').textContent"
      ),
      ERROR,
    )
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 1
    )
    self.screenshot()
    (self.artifacts / "window.png").rename(self.artifacts / "failure-reason.png")
    self.evaluate("document.querySelector('dialog[open] [aria-label=关闭]').click()")
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
    assert self.ws is not None
    self.ws.close()
    self.ws = None
    second = self.launch()
    self.connect()
    reopened = self.state("ready")
    wait_until(lambda: "因失败中止" in self.body())
    wait_until(lambda: "末尾错误原文" in self.body())
    current = self.client.get(
      reopened["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    self.assertEqual(current, history)
    self.assertEqual(self.draft(), "失败时的下一条草稿")
    self.assertEqual(
      self.evaluate("document.querySelector('[aria-label=失败原因]').textContent"),
      ERROR,
    )
    self.record(
      ready=ready,
      reopened=reopened,
      thread=thread,
      history=history,
      snapshot=snapshot,
      draft=self.draft(),
    )
    self.quit(second)
    self.assertEqual(second.wait(timeout=15), 0)


if __name__ == "__main__":
  suite = unittest.TestSuite(
    FailurePartialAcceptance(name)
    for name in FailurePartialAcceptance.__dict__
    if name.startswith("test_")
  )
  result = unittest.TextTestRunner(verbosity=2).run(suite)
  raise SystemExit(0 if result.wasSuccessful() else 1)
