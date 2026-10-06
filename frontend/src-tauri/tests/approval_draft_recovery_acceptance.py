"""第 13 票：真实 Tauri 重开恢复审批输入，未知提交只读核实。"""

import base64
import json
import unittest

from approval_resume_acceptance import ApprovalResumeAcceptance
from sse_fixtures import parse_sse_frames
from window_acceptance import REPO, wait_until


class ApprovalDraftRecoveryAcceptance(ApprovalResumeAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-13/native"

  def setUp(self):
    super().setUp()
    # 本票验证进程重开；父类 memory checkpoint 会在进程退出后丢失审批。
    self.fixture.config["checkpointer"] = {
      "type": "sqlite",
      "path": str(self.root / "checkpoints.db"),
    }
    self.fixture.write_config()
    self.addCleanup(self.record_recovery_diagnostics)

  def record_recovery_diagnostics(self):
    if self.ws is None:
      return
    try:
      diagnostics = self.evaluate(
        "({url:location.href,readyState:document.readyState,body:document.body.innerText,"
        "requests:window.__approvalRequests,hasHeldGet:Boolean(window.__releaseApprovalGet),"
        "messageDrafts:localStorage.getItem('shikigen.message-drafts.v1'),"
        "approvalDrafts:localStorage.getItem('shikigen.approval-drafts.v1')})"
      )
      diagnostics["backend"] = self.snapshot()
      (self.artifacts / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
      )
      screenshot_payload = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / "diagnostic.png").write_bytes(
        base64.b64decode(screenshot_payload)
      )
    except Exception as error:
      (self.artifacts / "diagnostic-error.txt").write_text(str(error), encoding="utf-8")

  def connect(self):
    super().connect()
    self.install_recovery_transport()

  def instrument_sends(self):
    # connect 在每个原生进程的新页面安装一次；不叠加父类请求计数包装。
    wait_until(lambda: self.evaluate("Array.isArray(window.__approvalRequests)"))

  def wait_verified_approval(self):
    wait_until(lambda: "审批请求已核实，等待处理。" in self.body())
    wait_until(lambda: "观察正常结束" in self.body())

  def restart_host(self, host):
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
    self.ws.close()
    self.ws = None
    reopened_host = self.launch()
    self.connect()
    return reopened_host, self.state("ready")

  def install_recovery_transport(self):
    self.call("Page.enable")
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source=r"""(() => {
        window.__approvalRequests=[];
        const sendRequest=window.fetch.bind(window);
        window.fetch=async(url,init)=> {
          const path=String(url),method=init?.method??'GET';
          if(path.includes('/api/'))window.__approvalRequests.push({url:path,method,
            body:init?.body?JSON.parse(init.body):null});
          if(method==='POST'&&path.endsWith('/approval-decisions')&&window.__holdApprovalBeforeSend)
            await new Promise(resolve=>window.__releaseApprovalBeforeSend=resolve);
          if(method==='GET'&&path.endsWith('/messages')&&localStorage.getItem('test-approval-history-404'))
            return new Response('测试会话暂不可读',{status:404});
          const response=await sendRequest(url,init);
          if(method==='GET'&&path.endsWith('/stream')&&localStorage.getItem('test-hold-approval-get'))
            await new Promise(resolve=>window.__releaseApprovalGet=resolve);
          return response;
        };
      })()""",
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__approvalRequests)"))

  def read_saved_backup(self):
    return self.evaluate(
      "JSON.parse(localStorage.getItem('shikigen.approval-drafts.v1'))"
    )["records"][0]

  def assert_read_only_choices(self):
    self.assertTrue(
      self.evaluate(
        "[...document.querySelectorAll('.approval-options')].every(fieldset=>fieldset.disabled)"
      )
    )
    self.assertEqual(len(self.read_approval_posts()), 0)

  def test_choices_and_raw_reason_survive_native_restart_then_full_get(self):
    host, startup_snapshot, thread_id, run_id = self.begin_approval()
    self.wait_verified_approval()
    self.choose_decision(0, "reject")
    self.update_rejection_reason(0, "  重开保留原因\n")
    self.choose_decision(2, "approve")
    original_backup = self.read_saved_backup()
    self.assertEqual(original_backup["draft"]["runId"], run_id)
    self.evaluate("localStorage.setItem('test-hold-approval-get','1')")
    reopened_host, reopened_snapshot = self.restart_host(host)
    wait_until(lambda: self.evaluate("Boolean(window.__releaseApprovalGet)"))
    self.assert_read_only_choices()
    self.assertIn("本地审批输入已保留", self.body())
    self.evaluate(
      "localStorage.removeItem('test-hold-approval-get');window.__releaseApprovalGet()"
    )
    wait_until(lambda: "审批请求已核实，等待处理。" in self.body())
    self.assertEqual(
      self.evaluate(
        "document.querySelectorAll('.approval-options input:checked').length"
      ),
      2,
    )
    self.assertEqual(
      self.evaluate("document.querySelector('.approval-reason-input textarea').value"),
      "  重开保留原因\n",
    )
    self.assertEqual(self.read_saved_backup()["draft"], original_backup["draft"])
    self.assertEqual(len(self.read_approval_posts()), 0)
    self.assertEqual(list(self.root.glob("approval-executed-*")), [])
    replay_response = self.client.get(
      reopened_snapshot["base_url"] + f"/api/threads/{thread_id}/runs/{run_id}/stream"
    )
    self.assertEqual(replay_response.status_code, 200)
    events = [
      frame["data"]
      for frame in parse_sse_frames(replay_response.text)
      if frame["event"] == "event"
    ]
    self.assertFalse(any(event["event_type"] == "resolved" for event in events))
    self.screenshot()
    self.record(
      original_backup=original_backup,
      reopened_backup=self.read_saved_backup(),
      requests=self.evaluate("window.__approvalRequests"),
      startup=startup_snapshot,
      reopened_snapshot=reopened_snapshot,
    )
    self.quit(reopened_host)
    self.assertEqual(reopened_host.wait(timeout=15), 0)

  def test_pending_restart_verifies_before_manual_same_run_resubmission(self):
    host, _, thread_id, run_id = self.begin_approval()
    self.wait_verified_approval()
    self.select_all_decisions()
    self.evaluate("window.__holdApprovalBeforeSend=true")
    self.click("提交决策")
    wait_until(lambda: self.evaluate("Boolean(window.__releaseApprovalBeforeSend)"))
    original_backup = self.read_saved_backup()
    self.assertEqual(original_backup["submission"]["status"], "pending")
    self.assertFalse(
      self.evaluate(
        "[...document.querySelectorAll('button')].find(button=>"
        "button.textContent==='取消运行'&&!button.disabled) !== undefined"
      )
    )
    reopened_host, reopened_snapshot = self.restart_host(host)
    wait_until(lambda: "先前请求仍可能迟到生效" in self.body())
    self.assertEqual(self.read_saved_backup()["submission"]["status"], "unknown")
    self.assertEqual(
      self.read_saved_backup()["submission"]["responses"],
      original_backup["submission"]["responses"],
    )
    self.assertEqual(len(self.read_approval_posts()), 0)
    self.assertEqual(list(self.root.glob("approval-executed-*")), [])
    self.screenshot()
    (self.artifacts / "window.png").rename(self.artifacts / "unknown-pending.png")
    (self.root / "allow-approval-tools").touch()
    self.click("提交决策")
    wait_until(lambda: "已完成" in self.body())
    self.assertEqual(len(self.read_approval_posts()), 1)
    self.assertEqual(
      self.read_approval_posts()[0]["body"]["responses"],
      original_backup["submission"]["responses"],
    )
    history = self.client.get(
      reopened_snapshot["base_url"] + f"/api/threads/{thread_id}/messages"
    ).json()["data"]
    self.assertEqual(history[-1]["run_id"], run_id)
    self.assertEqual(len(list(self.root.glob("approval-executed-*"))), 2)
    self.assertEqual(
      self.evaluate(
        "JSON.parse(localStorage.getItem('shikigen.approval-drafts.v1')).records.length"
      ),
      0,
    )
    self.record(
      original_backup=original_backup,
      requests=self.evaluate("window.__approvalRequests"),
      history=history,
    )
    self.quit(reopened_host)
    self.assertEqual(reopened_host.wait(timeout=15), 0)

  def test_history_404_keeps_copyable_local_choices_then_get_recovers(self):
    host, _, _, _ = self.begin_approval()
    self.wait_verified_approval()
    self.choose_decision(0, "reject")
    self.update_rejection_reason(0, "404 仍保留全文\n")
    original_backup = self.read_saved_backup()
    self.evaluate("localStorage.setItem('test-approval-history-404','1')")
    self.call("Page.reload")
    wait_until(lambda: "会话不存在；草稿和提交原文仍保留" in self.body())
    self.assert_read_only_choices()
    self.assertIn("本地审批输入已保留", self.body())
    self.evaluate(
      "document.querySelector('[aria-label=\"本地审批草稿核对\"] summary').click()"
    )
    retained_text = self.evaluate(
      "document.querySelector('[aria-label=\"本地审批草稿核对\"] pre').textContent"
    )
    self.assertEqual(
      json.loads(retained_text)["choices"], original_backup["draft"]["choices"]
    )
    self.screenshot()
    self.evaluate("localStorage.removeItem('test-approval-history-404')")
    self.click("刷新数据")
    wait_until(lambda: "审批请求已核实，等待处理。" in self.body())
    self.assertEqual(
      self.evaluate("document.querySelector('.approval-reason-input textarea').value"),
      "404 仍保留全文\n",
    )
    self.assertEqual(len(self.read_approval_posts()), 0)
    self.record(
      original_backup=original_backup,
      retained_text=retained_text,
      requests=self.evaluate("window.__approvalRequests"),
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  unittest.main(verbosity=2)
