"""第 12 票：真实 Tauri 多请求逐项审批、metadata 确认与只读异常。"""

import json
import unittest

from message_drafts_acceptance import MessageDraftAcceptance
from sse_fixtures import parse_sse_frames
from window_acceptance import REPO, wait_until


class ApprovalResumeAcceptance(MessageDraftAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-12/native"

  def setUp(self):
    super().setUp()
    bootstrap = self.root / "app/desktop.py"
    bootstrap.write_text(
      bootstrap.read_text(encoding="utf-8").replace(
        "from runtime_fixtures import deterministic_agent",
        "from desktop_approval_fixtures import "
        "create_approval_workbench_agent as deterministic_agent",
      ),
      encoding="utf-8",
    )

  def instrument_sends(self):
    super().instrument_sends()
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source=r"""(() => {
      window.__approvalRequests=[];
      const original=window.fetch.bind(window);
      window.fetch=async (url,init)=> {
        if (String(url).includes('/api/')) window.__approvalRequests.push({
          url:String(url),method:init?.method??'GET',body:init?.body?JSON.parse(init.body):null});
        if (window.__rejectApproval && String(url).endsWith('/approval-decisions')) {
          window.__rejectApproval=false;
          return new Response('测试原始校验详情',{status:422});
        }
        const response=await original(url,init);
        if (window.__delayApprovalReception
          && String(url).endsWith('/approval-decisions')) {
          window.__delayApprovalReception=false;
          await new Promise(resolve=>window.__releaseApprovalReception=resolve);
        }
        return response;
      };
    })()""",
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__approvalRequests)"))
    wait_until(lambda: "从一个想法开始" in self.body())

  def read_approval_posts(self):
    return self.evaluate(
      "window.__approvalRequests.filter(request=>request.method==='POST'"
      " && request.url.endsWith('/approval-decisions'))"
    )

  def begin_approval(self):
    host, startup_snapshot, thread_id = self.start_empty()
    self.send("多 Interrupt 多动作逐项核对")
    wait_until(lambda: "审批请求已核实，等待处理。" in self.body())
    self.assertEqual(
      self.evaluate("document.querySelectorAll('.approval-action').length"), 4
    )
    self.assertEqual(
      self.evaluate(
        "document.querySelectorAll('.approval-options input:checked').length"
      ),
      0,
    )
    self.assertEqual(list(self.root.glob("approval-executed-*")), [])
    messages = self.client.get(
      startup_snapshot["base_url"] + f"/api/threads/{thread_id}/messages"
    ).json()["data"]
    return host, startup_snapshot, thread_id, messages[-1]["run_id"]

  def choose_decision(self, index, decision):
    self.assertTrue(
      self.evaluate(
        f"(() => {{const action=document.querySelectorAll('.approval-action')[{index}];"
        f"const input=action.querySelector('input[value={decision}]');"
        "if(input.disabled)return false; input.click(); return true;})()"
      )
    )

  def update_rejection_reason(self, index, text):
    self.evaluate(
      f"(() => {{const input=document.querySelectorAll('.approval-action')[{index}]"
      ".querySelector('textarea');Object.getOwnPropertyDescriptor("
      "HTMLTextAreaElement.prototype,'value').set"
      f".call(input,{json.dumps(text)}); "
      "input.dispatchEvent(new Event('input',{bubbles:true}));})()"
    )

  def select_all_decisions(self):
    for index in range(4):
      self.choose_decision(index, "approve" if index % 2 == 0 else "reject")
    self.update_rejection_reason(1, "  拒绝原因保留\n")

  def test_multi_interrupt_action_order_parameters_pending_and_same_run_resume(self):
    host, startup_snapshot, thread_id, run_id = self.begin_approval()
    self.assertIn("已选择 0 / 4 项", self.body())
    self.assertEqual(
      self.evaluate("document.querySelectorAll('.approval-parameters[open]').length"), 0
    )
    self.choose_decision(0, "reject")
    self.update_rejection_reason(0, "切换选择保留文字")
    self.choose_decision(0, "approve")
    self.assertEqual(
      self.evaluate("document.querySelector('.approval-action textarea')"), None
    )
    self.choose_decision(0, "reject")
    self.assertEqual(
      self.evaluate("document.querySelector('.approval-action textarea').value"),
      "切换选择保留文字",
    )
    self.select_all_decisions()
    self.assertIn("已选择 4 / 4 项", self.body())
    self.evaluate("document.querySelector('.approval-parameters summary').click()")
    self.assertTrue(
      self.evaluate(
        "(() => {const p=document.querySelector('.approval-parameters pre');"
        "return p.scrollHeight>p.clientHeight;})()"
      )
    )
    replay = self.client.get(
      startup_snapshot["base_url"] + f"/api/threads/{thread_id}/runs/{run_id}/stream"
    )
    request = next(
      frame["data"]["payload"]
      for frame in parse_sse_frames(replay.text)
      if frame["event"] == "event" and frame["data"]["event_type"] == "required"
    )
    self.assertEqual(
      self.evaluate(
        "[...document.querySelectorAll('.approval-interrupt h3')]"
        ".map(heading=>heading.textContent)"
      ),
      [
        f"来源：{interrupt['namespace'] or '主流程'}"
        for interrupt in request["interrupts"]
      ],
    )
    self.evaluate(
      "window.__approvalCopies=[];Object.defineProperty(navigator,'clipboard',"
      "{configurable:true,value:{writeText:async text=>"
      "window.__approvalCopies.push(text)}})"
    )
    self.evaluate(
      "document.querySelector('.approval-parameters [aria-label=复制]').click()"
    )
    wait_until(lambda: self.evaluate("window.__approvalCopies.length") == 1)
    parameter_text = self.evaluate("window.__approvalCopies[0]")
    self.assertEqual(
      json.loads(parameter_text),
      request["interrupts"][0]["value"]["action_requests"][0]["args"],
    )
    self.assertEqual(
      parameter_text,
      self.evaluate("document.querySelector('.approval-parameters pre').textContent"),
    )
    self.evaluate(
      "document.querySelector('.approval-parameters .content-actions button').click()"
    )
    wait_until(lambda: "仅供核对，不在此处审批" in self.body())
    self.assertEqual(
      self.evaluate("document.querySelector('dialog[open] textarea')"), None
    )
    self.assertIn(
      "参数第 79 行",
      self.evaluate("document.querySelector('dialog[open] pre').textContent"),
    )
    self.evaluate(
      "document.querySelector('dialog[open] [aria-label=复制完整内容]').click()"
    )
    wait_until(lambda: self.evaluate("window.__approvalCopies.length") == 2)
    self.assertEqual(self.evaluate("window.__approvalCopies[1]"), parameter_text)
    self.screenshot()
    (self.artifacts / "window.png").rename(self.artifacts / "parameters.png")
    self.evaluate("document.querySelector('dialog[open] [aria-label=关闭]').click()")
    self.assertIn("已选择 4 / 4 项", self.body())
    self.evaluate("window.__delayApprovalReception=true")
    self.click("提交决策")
    wait_until(lambda: self.evaluate("Boolean(window.__releaseApprovalReception)"))
    self.assertIn("正在确认审批提交", self.body())
    self.assertTrue(
      self.evaluate(
        "[...document.querySelectorAll('.approval-options')].every(fieldset=>fieldset.disabled)"
      )
    )
    self.assertTrue(
      self.evaluate(
        "[...document.querySelectorAll('button')].filter(button=>button.textContent==='取消运行').every(button=>button.disabled)"
      )
    )
    self.assertEqual(len(self.read_approval_posts()), 1)
    self.screenshot()
    (self.artifacts / "window.png").rename(self.artifacts / "pending.png")
    self.evaluate("window.__releaseApprovalReception()")
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "运行中"
      )
    )
    wait_until(lambda: "正在确认审批提交" not in self.body())
    self.assertTrue(
      self.evaluate(
        "[...document.querySelectorAll('.composer button')].some(button=>"
        "button.textContent==='取消运行' && !button.disabled)"
      )
    )
    self.assertEqual(len(list(self.root.glob("approval-executed-*"))), 2)
    body = self.read_approval_posts()[0]["body"]
    self.assertEqual(list(body), ["responses"])
    self.assertEqual(len(body["responses"]), 2)
    for response in body["responses"].values():
      self.assertEqual(response["decisions"][0], {"type": "approve"})
      self.assertEqual(response["decisions"][1]["type"], "reject")
    (self.root / "allow-approval-tools").touch()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已完成"
      )
    )
    wait_until(lambda: "实际决策：拒绝" in self.body())
    snapshot = self.client.get(
      startup_snapshot["base_url"] + f"/api/threads/{thread_id}/runs/{run_id}"
    ).json()["data"]
    self.assertEqual(snapshot["status"], "completed")
    messages = self.client.get(
      startup_snapshot["base_url"] + f"/api/threads/{thread_id}/messages"
    ).json()["data"]
    self.assertTrue(all(message["run_id"] == run_id for message in messages))
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      run_id=run_id,
      requests=self.read_approval_posts(),
      snapshot=snapshot,
      messages=messages,
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_422_preserves_choices_and_only_get_then_manual_resubmit(self):
    host, startup_snapshot, thread_id, run_id = self.begin_approval()
    self.select_all_decisions()
    self.evaluate("window.__rejectApproval=true")
    self.click("提交决策")
    wait_until(lambda: "已核实当前请求" in self.body())
    self.assertEqual(len(self.read_approval_posts()), 1)
    self.assertIn("已选择 4 / 4 项", self.body())
    self.assertEqual(list(self.root.glob("approval-executed-*")), [])
    self.assertEqual(
      self.evaluate("document.querySelector('.approval-reason-input textarea').value"),
      "  拒绝原因保留\n",
    )
    (self.root / "allow-approval-tools").touch()
    self.click("提交决策")
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已完成"
      )
    )
    self.assertEqual(len(self.read_approval_posts()), 2)
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      run_id=run_id,
      requests=self.read_approval_posts(),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_unsupported_group_read_only_and_confirmed_cancel_without_tools(self):
    self.fixture.env["DESKTOP_TEST_UNSUPPORTED_APPROVAL"] = "1"
    host, startup_snapshot, thread_id = self.start_empty()
    self.send("暂不支持的审批仍可取消")
    wait_until(lambda: "本组包含暂不支持的决策" in self.body())
    wait_until(lambda: "观察正常结束" in self.body())
    self.assertEqual(
      self.evaluate(
        "document.querySelectorAll('.approval-options input:not(:disabled)').length"
      ),
      0,
    )
    self.assertEqual(len(self.read_approval_posts()), 0)
    self.click("取消运行")
    wait_until(
      lambda: self.evaluate("document.activeElement.textContent") == "继续运行"
    )
    self.click("确认取消")
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已取消"
      )
    )
    self.assertNotIn("运行已取消，审批失效", self.body())
    self.click("读取审批记录")
    wait_until(lambda: "运行已取消，审批失效" in self.body())
    self.assertEqual(list(self.root.glob("approval-executed-*")), [])
    self.assertEqual(len(self.read_approval_posts()), 0)
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      requests=self.evaluate("window.__approvalRequests"),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_old_terminal_parameters_keep_history_label_after_new_run(self):
    host, startup_snapshot, thread_id, old_run_id = self.begin_approval()
    self.click("取消运行")
    wait_until(
      lambda: self.evaluate("document.activeElement.textContent") == "继续运行"
    )
    self.click("确认取消")
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已取消"
      )
    )
    new_task_text = "新运行不改变旧审批的历史身份"
    self.assertIn("尚未读取服务端审批处理记录", self.body())
    self.assertEqual(
      self.evaluate("document.querySelector('.approval-card h2').textContent"),
      "运行已结束，审批不可操作",
    )
    self.set_draft(new_task_text)
    wait_until(
      lambda: self.evaluate(
        "[...document.querySelectorAll('.composer button')].some(button=>"
        "button.textContent.includes('发送') && !button.disabled)"
      )
    )
    self.send(new_task_text)
    wait_until(lambda: "审批请求已核实，等待处理。" in self.body())
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('.approval-card').length") == 2
    )
    self.assertEqual(
      self.evaluate("document.querySelector('.approval-card h2').textContent"),
      "运行已结束，审批不可操作",
    )
    self.evaluate(
      "document.querySelector('.approval-card .approval-parameters summary').click()"
    )
    self.evaluate(
      "document.querySelector('.approval-card .approval-parameters "
      ".content-actions button').click()"
    )
    wait_until(lambda: "以下为历史内容" in self.body())
    self.assertIn("审批已处理或运行已结束", self.body())
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent"),
      "等待审批",
    )
    self.assertEqual(len(self.read_approval_posts()), 0)
    self.assertEqual(list(self.root.glob("approval-executed-*")), [])
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      old_run_id=old_run_id,
      body=self.body(),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  unittest.main()
