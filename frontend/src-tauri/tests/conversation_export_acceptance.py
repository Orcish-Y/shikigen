"""第16票：真实 Tauri Blob 下载、公开事实、快照与中止记录。"""

import json
import re

import win32con
import win32gui
import win32process
from cancel_partial_acceptance import CancelPartialAcceptance
from desktop_cancel_fixtures import BODY as CANCEL_BODY
from desktop_failure_fixtures import BODY as FAILURE_BODY
from desktop_failure_fixtures import ERROR
from failure_partial_acceptance import FailurePartialAcceptance
from tool_records_acceptance import ToolRecordsAcceptance
from window_acceptance import REPO, wait_until


class ExportEvidence:
  def prepare_download(self, behavior="allow", is_delayed=False):
    self.download_root = self.artifacts / "downloads"
    self.download_root.mkdir(exist_ok=True)
    self.call(
      "Browser.setDownloadBehavior",
      behavior=behavior,
      downloadPath=str(self.download_root),
      eventsEnabled=True,
    )
    self.evaluate(
      """(() => {
      window.__exports=[];
      const createUrl=URL.createObjectURL.bind(URL);
      const performClick=HTMLAnchorElement.prototype.click;
      const exportBlobs=new Map();
      URL.createObjectURL=blob=>{
        const url=createUrl(blob);exportBlobs.set(url,blob);return url;
      };
      HTMLAnchorElement.prototype.click=function(){
        if(!this.download)return performClick.call(this);
        const anchor=this;
        const exportRequest={filename:anchor.download,
          href:anchor.href,capturedAtMs:performance.now()};
        window.__exports.push(exportRequest);
        exportRequest.readText=exportBlobs.get(anchor.href).text()
          .then(text=>exportRequest.text=text);
        if(window.__isExportDelayed){window.__releaseExport=()=>{
          document.body.append(anchor);performClick.call(anchor);anchor.remove();};return;}
        return performClick.call(anchor);
      };
      })()"""
    )
    self.evaluate("window.__isExportDelayed=" + json.dumps(is_delayed))

  def request_export(self):
    self.click("导出")
    wait_until(lambda: self.evaluate("window.__exports.at(-1)?.text !== undefined"))
    return self.evaluate("window.__exports.at(-1)")

  def read_download(self, export_request):
    destination = self.download_root / export_request["filename"]
    self.assertEqual(destination.parent, self.download_root)
    wait_until(lambda: destination.exists())
    wait_until(
      lambda: destination.read_bytes() == export_request["text"].encode("utf-8")
    )
    return destination.read_text(encoding="utf-8")

  def assert_complete_records(self, markdown, history):
    json_blocks = [
      json.loads(match[1])
      for match in re.findall(r"^(`{3,})json\n([\s\S]*?)\n\1(?=\n|$)", markdown, re.M)
    ]
    message_records = [
      block for block in json_blocks if isinstance(block, dict) and "seq" in block
    ]
    self.assertEqual(
      [message_record["seq"] for message_record in message_records],
      [message_record["seq"] for message_record in history],
    )
    for original_message, message_fields in zip(history, message_records, strict=True):
      # SSE 已提交消息可能尚没有 DB 外层 id/category，刷新后核对完整 HTTP 字段。
      expected_fields = {
        **original_message,
        "content": {
          key: value
          for key, value in original_message["content"].items()
          if key != "content"
        },
      }
      self.assertEqual(message_fields, expected_fields)
      body = original_message["content"]["content"]
      if isinstance(body, str):
        self.assertIn("\n" + body + "\n", markdown)
      else:
        self.assertIn(body, json_blocks)
    self.assertIn(f"消息数：{len(history)}", markdown)
    self.assertIn("不代表服务端全部历史", markdown)
    self.assertNotIn("尚未提交的秘密草稿", markdown)

  def read_history(self, backend_snapshot, thread):
    response = self.client.get(
      backend_snapshot["base_url"] + f"/api/threads/{thread}/messages"
    )
    response.raise_for_status()
    return response.json()["data"]

  def refresh_records(self):
    self.click("刷新数据")
    wait_until(
      lambda: (
        not self.evaluate(
          "[...document.querySelectorAll('button')].find(b=>b.textContent==='刷新数据')?.disabled"
        )
      )
    )


class DownloadEventRecorder:
  """在真实 WebView 下载开始事件到达时取消同一 GUID，保存原始协议证据。"""

  def __init__(self, acceptance):
    self.acceptance = acceptance
    self.download_events = []
    self.download_commands = []
    self.download_responses = []
    self.download_guid = None
    self.cancel_request_id = None

  def send_command(self, method, params):
    self.acceptance.sequence += 1
    request_id = self.acceptance.sequence
    command = {"id": request_id, "method": method, "params": params}
    self.download_commands.append(command)
    self.acceptance.ws.send(json.dumps(command, ensure_ascii=False))
    return request_id

  def call(self, method, **params):
    request_id = self.send_command(method, params)
    while True:
      response = json.loads(self.acceptance.ws.recv(timeout=10))
      event_name = response.get("method")
      if event_name in ("Browser.downloadWillBegin", "Browser.downloadProgress"):
        self.download_events.append(response)
        if event_name == "Browser.downloadWillBegin" and self.download_guid is None:
          self.download_guid = response["params"]["guid"]
          self.cancel_request_id = self.send_command(
            "Browser.cancelDownload", {"guid": self.download_guid}
          )
      if "id" in response:
        self.download_responses.append(response)
      if response.get("id") == request_id:
        self.acceptance.assertNotIn("error", response)
        self.acceptance.assertNotIn("exceptionDetails", response.get("result", {}))
        return response.get("result", {})


class ConversationExportAcceptance(ExportEvidence, ToolRecordsAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-16/native"

  def test_actual_utf8_download_complete_tool_records_and_click_snapshot(self):
    host, backend_snapshot, thread = self.start_records()
    self.refresh_records()
    history = self.history(backend_snapshot, thread)
    self.set_draft("尚未提交的秘密草稿")
    self.prepare_download(is_delayed=True)
    export_request = self.request_export()
    self.assertFalse(list(self.download_root.iterdir()))
    # 保存派发延迟期间真实新 Run 提交，不得混入已经生成的 Blob。
    self.send("点击之后的新消息不混入")
    wait_until(
      lambda: any(
        message_record["content"]["type"] == "human"
        and message_record["content"]["content"] == "点击之后的新消息不混入"
        for message_record in self.history(backend_snapshot, thread)
      )
    )
    self.evaluate("window.__releaseExport()")
    markdown = self.read_download(export_request)
    self.assert_complete_records(markdown, history)
    self.assertNotIn("点击之后的新消息不混入", markdown)
    self.assertEqual(self.evaluate("window.__sends.length"), 2)
    self.assertGreater(len(self.history(backend_snapshot, thread)), len(history))
    self.record(
      export=export_request,
      history=history,
      path=str(self.download_root / export_request["filename"]),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_empty_and_sync_failure_keep_draft_history_and_run(self):
    host, backend_snapshot, thread = self.start_empty()
    self.prepare_download()
    self.set_draft("尚未提交的秘密草稿")
    self.click("导出")
    wait_until(lambda: "暂无已提交内容可导出" in self.body())
    self.assertEqual(self.evaluate("window.__exports.length"), 0)
    self.assertEqual(self.read_history(backend_snapshot, thread), [])
    self.send("开始有事实的会话")
    wait_until(lambda: "工具记录已产生" in self.body())
    self.refresh_records()
    history = self.read_history(backend_snapshot, thread)
    self.set_draft("尚未提交的秘密草稿")
    self.evaluate("URL.createObjectURL=()=>{throw new Error('真实下载派发拒绝夹具');}")
    self.click("导出")
    wait_until(lambda: "真实下载派发拒绝夹具" in self.body())
    self.assertEqual(self.read_history(backend_snapshot, thread), history)
    self.assertEqual(self.draft(), "尚未提交的秘密草稿")
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent"), "已完成"
    )
    self.assertFalse(list(self.download_root.iterdir()))
    self.record(history=history, failure=self.body())
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_webview_download_denied_does_not_modify_facts_then_manual_download(self):
    host, backend_snapshot, thread = self.start_records()
    self.refresh_records()
    history = self.history(backend_snapshot, thread)
    self.set_draft("尚未提交的秘密草稿")
    self.prepare_download(behavior="deny")
    denied_request = self.request_export()
    self.assertFalse(list(self.download_root.iterdir()))
    self.assertEqual(self.history(backend_snapshot, thread), history)
    self.assertEqual(self.draft(), "尚未提交的秘密草稿")
    self.assertNotIn(
      "已保存",
      self.evaluate("document.querySelector('[aria-label=会话导出]').textContent"),
    )
    self.call(
      "Browser.setDownloadBehavior",
      behavior="allow",
      downloadPath=str(self.download_root),
      eventsEnabled=True,
    )
    export_request = self.request_export()
    self.assert_complete_records(self.read_download(export_request), history)
    self.assertEqual(self.history(backend_snapshot, thread), history)
    self.record(
      denied_export_request=denied_request,
      accepted_export_request=export_request,
      history=history,
      limit="CDP 在真实 WebView 下载边界 deny；不等同于点击原生保存弹窗取消",
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_actual_webview_download_cancel_keeps_facts_and_draft(self):
    host, backend_snapshot, thread = self.start_records()
    self.refresh_records()
    history = self.history(backend_snapshot, thread)
    self.set_draft("尚未提交的秘密草稿")
    recorder = DownloadEventRecorder(self)
    self.call = recorder.call
    self.prepare_download(is_delayed=True)
    export_request = self.request_export()
    self.assertFalse(list(self.download_root.iterdir()))
    self.evaluate("window.__releaseExport()")

    def read_cancel_event():
      self.evaluate("0")
      return next(
        (
          event["params"]
          for event in recorder.download_events
          if event["method"] == "Browser.downloadProgress"
          and event["params"]["guid"] == recorder.download_guid
          and event["params"]["state"] == "canceled"
        ),
        None,
      )

    cancel_event = wait_until(read_cancel_event, timeout=10)

    def read_cancel_response():
      self.evaluate("0")
      return next(
        (
          response
          for response in recorder.download_responses
          if response.get("id") == recorder.cancel_request_id
        ),
        None,
      )

    cancel_response = wait_until(read_cancel_response, timeout=10)
    self.assertNotIn("error", cancel_response)
    self.assertEqual(cancel_response["result"], {})
    starting_event = next(
      event["params"]
      for event in recorder.download_events
      if event["method"] == "Browser.downloadWillBegin"
      and event["params"]["guid"] == recorder.download_guid
    )
    self.assertEqual(starting_event["url"], export_request["href"])
    self.assertEqual(starting_event["suggestedFilename"], export_request["filename"])
    self.assertEqual(
      cancel_event["totalBytes"], len(export_request["text"].encode("utf-8"))
    )
    self.assertEqual(cancel_event["receivedBytes"], 0)
    self.assertFalse(list(self.download_root.iterdir()))
    self.assertEqual(self.history(backend_snapshot, thread), history)
    self.assertEqual(self.draft(), "尚未提交的秘密草稿")
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent"), "已完成"
    )
    self.assertNotIn(
      "已保存",
      self.evaluate("document.querySelector('[aria-label=会话导出]').textContent"),
    )
    self.record(
      export=export_request,
      history=history,
      download_commands=recorder.download_commands,
      download_responses=recorder.download_responses,
      download_events=recorder.download_events,
      limit="真实 WebView 下载 GUID 取消；不代表默认保存 UI 或物理用户操作",
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


class CancelExportAcceptance(ExportEvidence, CancelPartialAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-16/native"

  def test_preview_excluded_then_actual_cancelled_body_downloaded(self):
    host, backend_snapshot, thread = self.begin()
    self.set_draft("尚未提交的秘密草稿")
    self.prepare_download()
    preview_request = self.request_export()
    preview_markdown = self.read_download(preview_request)
    self.assertNotIn(CANCEL_BODY, preview_markdown)
    self.assertIn("消息数：1", preview_markdown)
    self.confirm()
    wait_until(lambda: "因取消中止" in self.body())
    self.refresh_records()
    history = self.read_history(backend_snapshot, thread)
    export_request = self.request_export()
    markdown = self.read_download(export_request)
    self.assert_complete_records(markdown, history)
    self.assertIn(CANCEL_BODY, markdown)
    self.assertIn("因取消中止", markdown)
    self.assertRegex(markdown, r"`{3,}markdown\n")
    self.assertEqual(self.draft(), "尚未提交的秘密草稿")
    self.assertEqual(self.read_history(backend_snapshot, thread), history)
    self.record(
      preview_export=preview_request, cancelled_export=export_request, history=history
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


class FailureExportAcceptance(ExportEvidence, FailurePartialAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-16/native"

  def test_actual_failed_body_and_reason_download_without_changing_run(self):
    host, backend_snapshot, thread = self.start_empty()
    self.send("导出失败前的完整正文")
    wait_until(lambda: (self.root / "failure-text-ready").exists())
    (self.root / "allow-failure-model").touch()
    wait_until(lambda: "因失败中止" in self.body())
    self.refresh_records()
    history = self.read_history(backend_snapshot, thread)
    self.set_draft("尚未提交的秘密草稿")
    self.prepare_download()
    export_request = self.request_export()
    markdown = self.read_download(export_request)
    self.assert_complete_records(markdown, history)
    self.assertIn(FAILURE_BODY, markdown)
    self.assertIn("因失败中止", markdown)
    self.assertIn(json.dumps(ERROR, ensure_ascii=False)[1:-1], markdown)
    self.assertEqual(self.read_history(backend_snapshot, thread), history)
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent"), "运行失败"
    )
    self.record(export=export_request, history=history, error=ERROR)
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


class NativeSaveCancelExportAcceptance(ExportEvidence, ToolRecordsAcceptance):
  """默认保存 UI 的额外探针；特定 SaveAs 窗口假设尚未在当前环境成立。"""

  artifact_root = REPO / ".scratch/frontend-completion/ticket-16/native"

  def setUp(self):
    super().setUp()
    self.download_root = self.artifacts / "native-save-downloads"
    self.download_root.mkdir()
    # 仅本例全新隔离 profile，默认目录也在本例产物内，不使用用户 Downloads。
    preferences_root = self.root / "webview/EBWebView/Default"
    preferences_root.mkdir(parents=True)
    (preferences_root / "Preferences").write_text(
      json.dumps(
        {
          "download": {
            "default_directory": str(self.download_root),
            "prompt_for_download": True,
            "directory_upgrade": True,
          }
        }
      ),
      encoding="utf-8",
    )

  def find_owned_save_dialog(self, host, main_window):
    dialogs = []

    def collect_window(window, _context):
      if (
        not win32gui.IsWindowVisible(window)
        or win32gui.GetClassName(window) != "#32770"
      ):
        return
      title = win32gui.GetWindowText(window)
      if "另存为" not in title and "save as" not in title.lower():
        return
      owner = win32gui.GetWindow(window, win32con.GW_OWNER)
      if (
        win32process.GetWindowThreadProcessId(window)[1] == host.pid
        or owner == main_window
      ):
        dialogs.append(window)

    win32gui.EnumWindows(collect_window, None)
    self.assertLessEqual(len(dialogs), 1)
    return dialogs[0] if dialogs else None

  def test_actual_default_save_dialog_cancel_keeps_facts_and_draft(self):
    host, backend_snapshot, thread = self.start_records()
    self.refresh_records()
    history = self.history(backend_snapshot, thread)
    self.set_draft("尚未提交的秘密草稿")
    main_window = self.window(host)
    profile_preferences = json.loads(
      (self.root / "webview/EBWebView/Default/Preferences").read_text(encoding="utf-8")
    )
    self.assertEqual(
      profile_preferences["download"]["default_directory"], str(self.download_root)
    )
    self.assertIs(profile_preferences["download"]["prompt_for_download"], True)
    # 不用 Browser.setDownloadBehavior：通过本例 profile 的真实默认保存 UI。
    export_position = self.evaluate("""(() => {
      const button=document.querySelector('[aria-label=导出当前会话]');
      const bounds=button.getBoundingClientRect();
      return {x:bounds.x+bounds.width/2,y:bounds.y+bounds.height/2};
    })()""")
    # 用可信 WebView 输入排除 JS click 的用户激活差异；不预判默认 UI 的形态。
    for input_type in ("mousePressed", "mouseReleased"):
      self.call(
        "Input.dispatchMouseEvent",
        type=input_type,
        button="left",
        clickCount=1,
        **export_position,
      )
    dialog = wait_until(
      lambda: self.find_owned_save_dialog(host, main_window), timeout=15
    )
    cancel_button = win32gui.GetDlgItem(dialog, win32con.IDCANCEL)
    self.assertTrue(cancel_button and win32gui.IsWindowEnabled(cancel_button))
    controls = []
    win32gui.EnumChildWindows(
      dialog,
      lambda control, _context: controls.append(
        {
          "class": win32gui.GetClassName(control),
          "text": win32gui.GetWindowText(control),
        }
      ),
      None,
    )
    dialog_evidence = {
      "window": dialog,
      "owner": win32gui.GetWindow(dialog, win32con.GW_OWNER),
      "pid": win32process.GetWindowThreadProcessId(dialog)[1],
      "title": win32gui.GetWindowText(dialog),
      "controls": controls,
    }
    # 分发真实系统 Cancel 控件；不调用应用内部取消逻辑或下载策略 deny。
    win32gui.PostMessage(cancel_button, win32con.BM_CLICK, 0, 0)
    wait_until(
      lambda: not win32gui.IsWindow(dialog) or not win32gui.IsWindowVisible(dialog)
    )
    self.assertFalse(list(self.download_root.iterdir()))
    self.assertEqual(self.history(backend_snapshot, thread), history)
    self.assertEqual(self.draft(), "尚未提交的秘密草稿")
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent"), "已完成"
    )
    self.assertNotIn(
      "已保存",
      self.evaluate("document.querySelector('[aria-label=会话导出]').textContent"),
    )
    self.record(
      save_dialog=dialog_evidence,
      history=history,
      download_root=str(self.download_root),
      limit="实际系统取消控件；WebView截图只记录取消后应用，不代表物理鼠标/键盘",
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
