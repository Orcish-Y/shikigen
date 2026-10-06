"""第 07 票：真实 Tauri 正文、复制、只读前景与受控原生命令。"""

import json
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from desktop_markdown_fixtures import CODE, CONTENT, TOOL_TEXT
from message_drafts_acceptance import MessageDraftAcceptance
from window_acceptance import REPO, wait_until


class MarkdownAcceptance(MessageDraftAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-07/native"

  def setUp(self):
    super().setUp()
    bootstrap = self.root / "app/desktop.py"
    bootstrap.write_text(
      bootstrap.read_text(encoding="utf-8").replace(
        "from runtime_fixtures import deterministic_agent",
        "from desktop_markdown_fixtures import markdown_agent as deterministic_agent",
      ),
      encoding="utf-8",
    )

  def capture_clipboard(self, fail=False):
    self.evaluate(
      "Object.defineProperty(navigator, 'clipboard', {configurabl"
      "e:true, value:{"
      "writeText:async text=>{window.__copied=text;"
      + ("throw new Error('clipboard denied');" if fail else "")
      + "}}})"
    )

  def test_real_messages_full_copy_drawer_and_single_foreground(self):
    host, ready, thread = self.start_empty()
    original = "  **用户原文**\n# 用户不渲染标题\n"
    self.send(original)
    wait_until(lambda: "数组最后一块" in self.body())
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已完成"
      )
    )
    history = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    self.assertEqual(history[-1]["content"]["content"], CONTENT)
    # Compare the exact public persisted representation. Persistence may reorder
    # object keys; the producer fixture's insertion order is not the wire format.
    complete_text = json.dumps(
      history[-1]["content"]["content"], ensure_ascii=False, indent=2
    )
    self.assertEqual(
      self.evaluate("document.querySelector('.user .plain-content').textContent"),
      original,
    )
    self.assertEqual(
      self.evaluate("document.querySelector('.tool .plain-content').textContent"),
      TOOL_TEXT,
    )
    self.assertEqual(
      self.evaluate(
        "document.querySelector('.assistant .message-text h1').textContent"
      ),
      "Agent 正文标题",
    )
    self.assertFalse(self.evaluate("Boolean(window.__injected)"))
    self.assertEqual(
      self.evaluate(
        "document.querySelectorAll('.message-text script,.message-t"
        "ext iframe,.message-text form,.message-text img').length"
      ),
      0,
    )
    self.assertTrue(
      self.evaluate("document.querySelector('.message-text input').disabled")
    )
    self.assertTrue(
      self.evaluate(
        "document.querySelector('.markdown-table').scrollWidth > do"
        "cument.querySelector('.markdown-table').clientWidth"
      )
    )
    self.assertEqual(
      self.evaluate(
        "new Set([...document.querySelectorAll('.message-text [id]'"
        ")].map(e=>e.id)).size"
      ),
      self.evaluate("document.querySelectorAll('.message-text [id]').length"),
    )
    self.assertTrue(
      self.evaluate(
        "document.querySelector('.content-block pre[aria-label=\"scr"
        "ipts/main.py · python\"]').scrollHeight > 320"
      )
    )
    self.assertLessEqual(
      self.evaluate(
        "document.querySelector('.content-block pre[aria-label=\"scr"
        "ipts/main.py · python\"]').clientHeight"
      ),
      320,
    )
    self.capture_clipboard()
    self.evaluate(
      "document.querySelector('.content-block pre[aria-label=\"scr"
      "ipts/main.py · python\"]').parentElement.querySelector('[ar"
      "ia-label=复制]').click()"
    )
    wait_until(lambda: self.evaluate("window.__copied") == CODE)
    self.set_draft("关闭详情仍保留草稿")
    self.instrument_fetch()
    wait_until(lambda: "数组最后一块" in self.body())
    self.capture_clipboard()
    self.evaluate(
      "(() => {const b=document.querySelector('.content-block pre"
      '[aria-label="scripts/main.py · python"]\').parentElement.qu'
      "erySelector('button'); window.__viewTrigger=b; b.focus(); b.click();})()"
    )
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('dialog[open]'))"))
    self.assertEqual(
      self.evaluate("document.querySelector('dialog[open] pre').textContent"), CODE
    )
    self.assertEqual(
      self.evaluate(
        "Math.round(document.querySelector('dialog[open]').getBound"
        "ingClientRect().width)"
      ),
      400,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key="k",
      code="KeyK",
      modifiers=2,
      windowsVirtualKeyCode=75,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyUp",
      key="k",
      code="KeyK",
      modifiers=2,
      windowsVirtualKeyCode=75,
    )
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 1
    )
    self.assertEqual(
      self.evaluate("document.querySelector('dialog[open] h2').textContent"),
      "scripts/main.py · python",
    )
    self.screenshot()
    (self.artifacts / "desktop-drawer.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key="Escape",
      code="Escape",
      windowsVirtualKeyCode=27,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyUp",
      key="Escape",
      code="Escape",
      windowsVirtualKeyCode=27,
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    self.assertEqual(
      self.evaluate("document.activeElement.textContent.trim()"), "查看完整内容"
    )
    self.assertTrue(
      self.evaluate(
        "window.__viewTrigger.isConnected && "
        "document.activeElement === window.__viewTrigger"
      )
    )
    self.assertEqual(self.draft(), "关闭详情仍保留草稿")
    self.assertFalse(
      any(
        r["url"].endswith("/stream") or r["method"] != "GET"
        for r in self.evaluate("window.__requests")
      )
    )
    self.capture_clipboard(fail=True)
    self.evaluate(
      "document.querySelector('.assistant:last-child .message-con"
      'tent-actions [aria-label="复制完整内容"]\').click()'
    )
    wait_until(lambda: "复制失败，可手动选择" in self.body())
    copied = self.evaluate("window.__copied")
    self.record(history=history, copied=copied, expected=complete_text)
    self.assertEqual(json.loads(copied), CONTENT)
    self.assertEqual(copied, complete_text)
    self.call(
      "Emulation.setDeviceMetricsOverride",
      width=390,
      height=780,
      deviceScaleFactor=1,
      mobile=False,
    )
    self.evaluate(
      "(() => {const b=document.querySelector('.assistant:last-ch"
      "ild .message-content-actions button'); b.focus(); b.click("
      ");})()"
    )
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('dialog[open]'))"))
    self.assertEqual(
      self.evaluate("document.querySelector('dialog[open] pre').textContent"),
      complete_text,
    )
    self.assertEqual(
      self.evaluate(
        "Math.round(document.querySelector('dialog[open]').getBound"
        "ingClientRect().width)"
      ),
      390,
    )
    self.assertEqual(
      self.evaluate(
        "Math.round(document.querySelector('dialog[open]').getBound"
        "ingClientRect().height)"
      ),
      624,
    )
    # CDP: Shift=8 (Alt=1). Include multiple full forward/backward cycles so
    # a native WebView cannot briefly send focus outside the modal at the ends.
    for modifiers in (0, 8, 0, 0, *([0] * 8), *([8] * 8)):
      self.call(
        "Input.dispatchKeyEvent",
        type="keyDown",
        key="Tab",
        code="Tab",
        windowsVirtualKeyCode=9,
        modifiers=modifiers,
      )
      self.call(
        "Input.dispatchKeyEvent",
        type="keyUp",
        key="Tab",
        code="Tab",
        windowsVirtualKeyCode=9,
        modifiers=modifiers,
      )
      self.assertTrue(
        self.evaluate("Boolean(document.activeElement.closest('dialog[open]'))")
      )
    # Native DPI can quantize outline widths/offsets to fractional CSS pixels.
    # Check the declarations and exact parity with the existing button.
    focus_styles = self.evaluate("""(() => {
      const pre = document.querySelector('dialog[open] pre');
      const close = document.querySelector('dialog[open] [aria-label=关闭]');
      const snapshot = element => {
        const offsets = [];
        const outlines = [];
        const visit = rules => {
          for (const rule of rules) {
            if (rule instanceof CSSMediaRule && !matchMedia(rule.conditionText).matches)
              continue;
            if (rule instanceof CSSSupportsRule && !CSS.supports(rule.conditionText))
              continue;
            if (rule instanceof CSSStyleRule && element.matches(rule.selectorText)
                && rule.style.outlineOffset)
              offsets.push(rule.style.outlineOffset);
            if (rule instanceof CSSStyleRule && element.matches(rule.selectorText)
                && rule.style.outline)
              outlines.push(rule.style.outline);
            if (rule.cssRules) visit(rule.cssRules);
          }
        };
        for (const sheet of document.styleSheets) visit(sheet.cssRules);
        const style = getComputedStyle(element);
        return {
          active: document.activeElement === element,
          visible: element.matches(':focus-visible'),
          declaredOffsets: offsets,
          declaredOutlines: outlines,
          resolved: [style.outlineColor, style.outlineWidth, style.outlineOffset],
        };
      };
      const content = snapshot(pre);
      close.focus({preventScroll: true});
      const button = snapshot(close);
      pre.focus({preventScroll: true});
      return {content, button, restored: snapshot(pre)};
    })()""")
    self.record(focus_styles=focus_styles)
    for style in focus_styles.values():
      self.assertTrue(style["active"])
      self.assertTrue(style["visible"])
      self.assertEqual(style["declaredOffsets"], ["3px"])
      self.assertEqual(style["declaredOutlines"], ["2px solid var(--accent)"])
      self.assertEqual(style["resolved"][0], "rgb(79, 70, 229)")
    self.assertEqual(focus_styles["content"], focus_styles["button"])
    self.assertEqual(focus_styles["content"], focus_styles["restored"])
    self.screenshot()
    (self.artifacts / "narrow-content.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.evaluate("document.querySelector('dialog[open] [aria-label=关闭]').click()")
    self.call("Emulation.clearDeviceMetricsOverride")
    self.record(
      history=history,
      copied=self.evaluate("window.__copied"),
      expected=complete_text,
      focus_styles=focus_styles,
      body=self.body(),
      requests=self.evaluate("window.__requests"),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_native_rejects_unsafe_urls_and_frontend_reports_open_failure(self):
    host, ready, thread = self.start_empty()
    self.send("受控网页入口")
    wait_until(lambda: "数组最后一块" in self.body())
    before = self.evaluate("location.href")
    rejected = []
    for raw in [
      "file:///C:/secret.txt",
      "javascript:alert(1)",
      "mailto:a@example.org",
      "https://",
    ]:
      result = self.evaluate(
        "window.__TAURI_INTERNALS__.invoke('open_web_url', {url:"
        + json.dumps(raw)
        + "}).then(()=>({accepted:true}),error=>error)"
      )
      self.assertEqual(result["code"], "invalid_web_url")
      rejected.append(result)
    permission = self.evaluate(
      "window.__TAURI_INTERNALS__.invoke('plugin:opener|open_url'"
      ", {url:'https://example.org'}).then(()=>({accepted:true}),"
      "error=>String(error))"
    )
    self.assertIsInstance(permission, str)
    self.assertIn("not allowed", permission)

    # Real opener success against a local, inert page; no external network.
    class Page(BaseHTTPRequestHandler):
      def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
          "<title>Shikigen 网页打开验收</title><p>可以关闭此页面。</p>".encode()
        )

      def log_message(self, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
      web_url = f"http://127.0.0.1:{server.server_port}/acceptance"
      accepted = self.evaluate(
        "window.__TAURI_INTERNALS__.invoke('open_web_url', {url:"
        + json.dumps(web_url)
        + "}).then(value=>({accepted:value}),error=>({error}))"
      )
      self.assertEqual(accepted, {"accepted": True})
      self.assertEqual(self.evaluate("location.href"), before)
    finally:
      server.shutdown()
      server.server_close()
    # Native IPC is the external boundary. Force a system failure to verify
    # local UI feedback, and record that modified clicks use the same command.
    self.evaluate("""
      (() => {
        // Tauri's invoke is immutable. Inject only at its HTTP IPC boundary;
        // real invoke/runCallback must process the structured error.
        const original = window.fetch.bind(window);
        window.__webCalls = [];
        window.fetch = (url, init) => {
          if (String(url) !== 'http://ipc.localhost/open_web_url')
            return original(url, init);
          window.__webCalls.push({command:'open_web_url', args:JSON.parse(init.body)});
          return Promise.resolve(new Response(JSON.stringify({
            code:'web_open_failed', message:'系统拒绝打开'
          }), {status:200, headers:{
            'Content-Type':'application/json', 'Tauri-Response':'error'
          }}));
        };
      })()
    """)
    self.evaluate(
      "document.querySelector('.markdown-link[title=\"https://exam"
      "ple.org/test\"]').dispatchEvent(new MouseEvent('click',{ctr"
      "lKey:true,shiftKey:true,bubbles:true,cancelable:true}))"
    )
    wait_until(lambda: "打开失败：系统拒绝打开" in self.body())
    self.assertEqual(
      self.evaluate("window.__webCalls"),
      [{"command": "open_web_url", "args": {"url": "https://example.org/test"}}],
    )
    self.assertEqual(self.evaluate("location.href"), before)
    self.assertEqual(
      self.evaluate(
        "document.querySelectorAll('.message-text a[href],.message-"
        "text img[src]').length"
      ),
      0,
    )
    self.record(
      rejected=rejected,
      accepted=accepted,
      plugin_permission=permission,
      calls=self.evaluate("window.__webCalls"),
      body=self.body(),
      ready=ready,
      thread=thread,
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  names = [
    "test_real_messages_full_copy_drawer_and_single_foreground",
    "test_native_rejects_unsafe_urls_and_frontend_reports_open_failure",
  ]
  result = unittest.TextTestRunner(verbosity=2).run(
    unittest.TestSuite(MarkdownAcceptance(name) for name in names)
  )
  raise SystemExit(0 if result.wasSuccessful() else 1)
