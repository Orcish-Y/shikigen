"""第14票：真实 Tauri / Graph / 文件 / GET 与图片布局生命周期。"""

import json
import struct
import unittest
import zlib

import win32con
import win32gui
from chat_reading_acceptance import ChatReadingAcceptance
from window_acceptance import REPO, wait_until


def png_bytes(width=400, height=800):
  def chunk(kind, content):
    return (
      struct.pack(">I", len(content))
      + kind
      + content
      + struct.pack(">I", zlib.crc32(kind + content))
    )

  pixels = b"".join(
    b"\x00" + bytes((203, 213, 225, 255)) * width for _ in range(height)
  )
  return (
    b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    + chunk(b"IDAT", zlib.compress(pixels))
    + chunk(b"IEND", b"")
  )


class WorkspaceImageAcceptance(ChatReadingAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-14/native"

  def setUp(self):
    super().setUp()
    bootstrap = self.root / "app/desktop.py"
    bootstrap.write_text(
      bootstrap.read_text(encoding="utf-8").replace(
        "from desktop_reading_fixtures import reading_agent as deterministic_agent",
        "from desktop_workspace_image_fixtures import "
        "workspace_image_agent as deterministic_agent",
      ),
      encoding="utf-8",
    )
    self.workspace = self.root / "workspace"
    (self.workspace / "images").mkdir(parents=True)
    (self.workspace / "notes").mkdir()
    (self.workspace / "images/tall.png").write_bytes(png_bytes())
    (self.workspace / "images/inert.svg").write_text(
      '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="100">'
      "<script>window.__svgExecuted=true</script>"
      '<rect width="240" height="100" fill="#cbd5e1"/></svg>',
      encoding="utf-8",
    )
    (self.workspace / "notes/report.txt").write_text("只读文件引用", encoding="utf-8")
    (self.root / "outside.png").write_bytes(png_bytes(1, 1))
    self.fixture.config["workspace_root"] = str(self.workspace)
    self.fixture.write_config()

  def instrument_images(self):
    self.call("Page.enable")
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source="""
      window.__imageRequests=[]; window.__imageAborts=[];
      window.__urls=[]; window.__revoked=[];
      const createObjectUrl=URL.createObjectURL.bind(URL);
      const revokeObjectUrl=URL.revokeObjectURL.bind(URL);
      URL.createObjectURL=blob=>{
        const url=createObjectUrl(blob);window.__urls.push(url);return url;
      };
      URL.revokeObjectURL=url=>{window.__revoked.push(url);revokeObjectUrl(url);};
      const fetchResource=window.fetch.bind(window);
      window.fetch=async(url,options)=>{
        if (!String(url).includes('/api/workspace')) return fetchResource(url,options);
        window.__imageRequests.push({url:String(url),method:options?.method??'GET'});
        options?.signal?.addEventListener('abort',()=>window.__imageAborts.push(String(url)),{once:true});
        const response=await fetchResource(url,options);
        if (String(url).endsWith('/image') && window.__holdImages) {
          await new Promise(resolve=>(window.__releaseImages??=[]).push(resolve));
        }
        return response;
      };
    """,
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__imageRequests)"))
    wait_until(lambda: "从一个想法开始" in self.body())

  def loaded_count(self):
    return self.evaluate(
      "[...document.querySelectorAll('.workspace-image > img')]"
      ".filter(e=>e.complete&&e.naturalWidth>0).length"
    )

  def test_auto_preview_full_view_copy_and_only_explicit_agent_references(self):
    host, ready, thread = self.start_empty()
    self.instrument_images()
    self.send("![用户原文不读取](images/user-only.png)")
    wait_until(lambda: "图片正文结束" in self.body())
    wait_until(lambda: self.loaded_count() == 4)
    wait_until(lambda: "HTTP 404" in self.body() and "HTTP 403" in self.body())
    requests = self.evaluate("window.__imageRequests")
    self.assertTrue(all(request["method"] == "GET" for request in requests))
    self.assertEqual(sum(request["url"].endswith("/image") for request in requests), 2)
    self.assertFalse(
      any(
        name in request["url"]
        for request in requests
        for name in ("user-only", "code-only", "json-only", "never-load", "report.txt")
      )
    )
    self.assertFalse(self.evaluate("Boolean(window.__svgExecuted)"))
    self.assertEqual(
      self.evaluate(
        "[...document.querySelectorAll('.message-text svg,.message-text script,"
        ".message-text object,.message-text iframe')].filter(e=>e.tagName !== 'svg'"
        " || !e.closest('button,.block-heading')).length"
      ),
      0,
    )
    self.assertTrue(
      self.evaluate(
        "[...document.querySelectorAll('.workspace-image > img')]"
        ".every(e=>e.src.startsWith('blob:'))"
      )
    )
    dimensions = self.evaluate(
      "[...document.querySelectorAll('.workspace-image > img')].map(e=>({"
      "height:e.clientHeight,width:e.clientWidth,parent:e.parentElement.clientWidth,"
      "natural:e.naturalWidth/e.naturalHeight}))"
    )
    self.assertTrue(
      all(
        size["height"] <= 320 and size["width"] <= size["parent"] for size in dimensions
      )
    )
    for size in dimensions:
      self.assertAlmostEqual(
        size["width"] / size["height"], size["natural"], delta=0.02
      )
    self.evaluate(
      "Object.defineProperty(navigator,'clipboard',{configurable:true,"
      "value:{writeText:async text=>window.__copied=text}})"
    )
    self.evaluate(
      "(() => {const trigger=document.querySelector("
      "'.workspace-image .content-actions button');trigger.focus();trigger.click();})()"
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 1
    )
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.image-viewer img').naturalHeight")
        == 800
      )
    )
    self.assertEqual(
      self.evaluate("document.querySelector('.image-viewer img').naturalHeight"), 800
    )
    self.assertIn(str(self.workspace / "images/tall.png"), self.body())
    self.click("复制实际路径")
    wait_until(
      lambda: (
        self.evaluate("window.__copied") == str(self.workspace / "images/tall.png")
      )
    )
    self.screenshot()
    self.evaluate("document.querySelector('dialog[open] [aria-label=关闭]').click()")
    self.assertEqual(
      self.evaluate("document.activeElement.textContent"), "查看完整图片"
    )
    run = self.client.get(ready["base_url"] + f"/api/threads/{thread}/messages").json()[
      "data"
    ][-1]
    self.assertEqual(run["run_status"], "completed")
    self.record(
      requests=requests,
      dimensions=dimensions,
      messages=run,
      copied=self.evaluate("window.__copied"),
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_delayed_image_preserves_paragraph_anchor_then_switch_hide_release_urls(self):
    host, ready, thread = self.start_empty()
    self.instrument_images()
    self.evaluate("window.__holdImages=true")
    self.send("长会话图片布局验收")
    wait_until(lambda: "图片正文结束" in self.body())
    wait_until(lambda: self.evaluate("(window.__releaseImages??[]).length") == 2)
    self.home()
    self.evaluate(
      "(() => {const t=document.querySelector('.timeline');"
      "const p=[...document.querySelectorAll('.assistant p')]"
      ".find(e=>e.textContent.startsWith('阅读段落 12'));"
      "t.scrollTop+=p.getBoundingClientRect().top-t.getBoundingClientRect().top+12;})()"
    )
    wait_until(lambda: self.geometry()["scrollTop"] > 500)
    anchor = self.geometry()
    self.evaluate(
      "window.__holdImages=false;window.__releaseImages.splice(0).forEach(resolve=>resolve())"
    )
    wait_until(lambda: self.loaded_count() == 4)
    self.assert_anchor(anchor)
    original_urls = self.evaluate("window.__urls.slice()")
    self.click("新建")
    wait_until(lambda: "从一个想法开始" in self.body())
    wait_until(
      lambda: all(url in self.evaluate("window.__revoked") for url in original_urls)
    )
    self.evaluate(
      "[...document.querySelectorAll('.session')].find(e=>e.title.includes("
      + json.dumps(thread)
      + ")).click()"
    )
    wait_until(lambda: self.loaded_count() == 4)
    self.assert_anchor(anchor)
    urls = self.evaluate("window.__urls.slice()")
    win32gui.PostMessage(self.window(host), win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(self.window(host)))
    wait_until(lambda: all(url in self.evaluate("window.__revoked") for url in urls))
    self.tray_menu(host, "打开主窗口", native_command=True)
    wait_until(lambda: self.loaded_count() == 4)
    self.assert_anchor(anchor)
    self.screenshot()
    self.record(
      anchor=anchor,
      current=self.geometry(),
      requests=self.evaluate("window.__imageRequests"),
      urls=self.evaluate("window.__urls"),
      revoked=self.evaluate("window.__revoked"),
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_hidden_pending_binary_is_aborted_and_late_result_never_creates_url(self):
    host, ready, thread = self.start_empty()
    self.instrument_images()
    self.evaluate("window.__holdImages=true")
    self.send("隐藏未完成图片验收")
    wait_until(lambda: self.evaluate("(window.__releaseImages??[]).length") == 2)
    win32gui.PostMessage(self.window(host), win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(self.window(host)))
    wait_until(
      lambda: (
        self.evaluate("window.__imageAborts.filter(url=>url.endsWith('/image')).length")
        == 2
      )
    )
    self.evaluate(
      "window.__holdImages=false;window.__releaseImages.splice(0).forEach(resolve=>resolve())"
    )
    self.assertEqual(self.evaluate("window.__urls.length"), 0)
    self.tray_menu(host, "打开主窗口", native_command=True)
    wait_until(lambda: self.loaded_count() == 4)
    self.assertEqual(self.evaluate("window.__urls.length"), 2)
    self.record(
      requests=self.evaluate("window.__imageRequests"),
      aborts=self.evaluate("window.__imageAborts"),
      urls=self.evaluate("window.__urls"),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_ready_lease_rotation_closes_image_view_and_reacquires_current_file(self):
    host, ready, thread = self.start_empty()
    self.instrument_images()
    self.send("图片详情租约轮换验收")
    wait_until(lambda: self.loaded_count() == 4)
    before_run = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"][-1]["run_id"]
    self.evaluate(
      "(() => {const trigger=document.querySelector("
      "'.workspace-image .content-actions button');trigger.focus();trigger.click();})()"
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 1
    )
    previous_urls = self.evaluate("window.__urls.slice()")
    # Emit a test frame at the public native bridge: preserve the real HTTP
    # runtime and Run, simulate a batched ready→ready address lease replacement.
    # This is not evidence that the real BackendManager restarted its process.
    lease_frame = {
      **ready,
      "startup_id": "image-lease-rotation-fixture",
      "revision": ready["revision"] + 100,
    }
    self.evaluate(
      "window.__TAURI_INTERNALS__.invoke('plugin:event|emit', "
      + json.dumps({"event": "backend-state-changed", "payload": lease_frame})
      + ")"
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0,
      timeout=5,
    )
    wait_until(lambda: self.loaded_count() == 4)
    self.assertTrue(
      all(url in self.evaluate("window.__revoked") for url in previous_urls)
    )
    self.assertTrue(
      self.evaluate(
        "[...document.querySelectorAll('.workspace-image > img')]"
        ".every(e=>!window.__revoked.includes(e.src))"
      )
    )
    requests = self.evaluate("window.__imageRequests")
    self.assertEqual(sum(request["url"].endswith("/image") for request in requests), 4)
    after_run = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"][-1]["run_id"]
    self.assertEqual(before_run, after_run)
    self.record(
      bridge_frame=lease_frame,
      frame_scope="公开Tauri桥接测试帧；非实际后端进程重启",
      requests=requests,
      previous_urls=previous_urls,
      revoked=self.evaluate("window.__revoked"),
      run_id=after_run,
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  suite = unittest.TestSuite(
    WorkspaceImageAcceptance(name)
    for name in WorkspaceImageAcceptance.__dict__
    if name.startswith("test_")
  )
  result = unittest.TextTestRunner(verbosity=2).run(suite)
  raise SystemExit(0 if result.wasSuccessful() else 1)
