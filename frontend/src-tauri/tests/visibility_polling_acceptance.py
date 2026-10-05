"""第 06 票：真 Tauri 显隐桥接、隐藏时运行继续和草稿恢复。

与其他原生验收串行，沿用独立临时后端及原生 Win32／托盘边界。
"""

import time
import unittest

import win32con
import win32gui
from message_drafts_acceptance import MessageDraftAcceptance
from window_acceptance import REPO, wait_until


class VisibilityAcceptance(MessageDraftAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-06/native"

  def visibility(self):
    return self.evaluate(
      "window.__TAURI_INTERNALS__.invoke('get_workspace_visibility')"
    )

  def visible_state(self, expected):
    def matching():
      value = self.visibility()
      return value if value["visible"] == expected else None

    return wait_until(matching)

  def test_hidden_task_continues_and_show_recovers_facts_without_resending(self):
    self.fixture.env["DESKTOP_TEST_RESIDENT_TASK"] = "1"
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    initial = self.visibility()
    self.assertTrue(initial["visible"])
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.click("新建")
    wait_until(lambda: "从一个想法开始" in self.body())
    self.instrument_fetch()
    self.send("第6票后台任务原文")
    wait_until(lambda: "观察已建立" in self.body())
    self.set_draft("隐藏期间保留草稿")
    thread = self.evaluate(
      "document.querySelector('.session[aria-current=true]').title"
    ).split("会话 ID：")[-1]
    history_url = ready["base_url"] + f"/api/threads/{thread}/messages"
    wait_until(lambda: self.client.get(history_url).json()["data"])
    before = self.client.get(history_url).json()["data"]
    run_id = before[-1]["run_id"]
    hwnd = self.window(host)
    win32gui.PostMessage(hwnd, win32con.WM_KILLFOCUS, 0, 0)
    self.assertEqual(self.visibility(), initial, "失焦不改变 visible／revision")
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(hwnd))
    # 在测试主动查询之前证明 hide 事件已经让前端撤销读取。
    wait_until(
      lambda: self.evaluate(
        "window.__requests.some(r=>r.url.endsWith('/stream') && r.aborted)"
      )
    )
    hidden = self.visible_state(False)
    self.assertGreater(hidden["revision"], initial["revision"])
    time.sleep(0.2)
    frozen = len(self.evaluate("window.__requests"))
    # 通过独立公开 GET 查后台，不使用应用内部状态。
    snapshot_url = ready["base_url"] + f"/api/threads/{thread}/runs/{run_id}"
    self.assertEqual(self.client.get(snapshot_url).json()["data"]["status"], "running")
    (self.root / "continue-task").touch()
    wait_until(
      lambda: self.client.get(snapshot_url).json()["data"]["status"] == "completed"
    )
    time.sleep(5.2)
    self.assertEqual(len(self.evaluate("window.__requests")), frozen)
    self.assertEqual(host.poll(), None)
    self.tray_menu(host, "打开主窗口", native_command=True)
    wait_until(lambda: win32gui.IsWindowVisible(hwnd))
    # show 事件自行恢复，不靠本测试的 query 引发更新。
    wait_until(lambda: "后台任务已完成" in self.body())
    shown = self.visible_state(True)
    self.assertGreater(shown["revision"], hidden["revision"])
    self.assertEqual(self.visibility(), shown, "重复查询不增加 revision")
    wait_until(lambda: "观察正常结束" in self.body())
    self.assertIn("观察正常结束", self.body())
    self.assertNotIn("观察已暂停", self.body())
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent.trim()"),
      "已完成",
    )
    self.assertEqual(self.draft(), "隐藏期间保留草稿")
    requests = self.evaluate("window.__requests")
    writes = [request for request in requests if request["method"] != "GET"]
    self.assertEqual(len(writes), 1)
    self.assertEqual(writes[0]["method"], "POST")
    recovered = requests[frozen:]
    self.assertEqual(len([r for r in recovered if "/messages" in r["url"]]), 1)
    final = self.client.get(history_url).json()["data"]
    self.assertEqual(len([m for m in final if m["content"]["type"] == "human"]), 1)
    self.record(
      initial=initial,
      hidden=hidden,
      shown=shown,
      frozen=frozen,
      requests=requests,
      history=final,
      run_id=run_id,
      body=self.body(),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  suite = unittest.TestSuite(
    [
      VisibilityAcceptance(
        "test_hidden_task_continues_and_show_recovers_facts_without_resending"
      )
    ]
  )
  result = unittest.TextTestRunner(verbosity=2).run(suite)
  raise SystemExit(0 if result.wasSuccessful() else 1)
