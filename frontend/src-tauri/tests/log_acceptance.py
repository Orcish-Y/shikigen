"""Startup logs through the real Windows host, Python stderr and WebView UI."""

import json
import unittest

import win32con
import win32event
from window_acceptance import REPO, WindowAcceptance, wait_until


class LogAcceptance(WindowAcceptance):
  artifact_root = REPO / ".scratch/windows-backend-lifecycle/log-acceptance"

  def body(self):
    return self.evaluate("document.body.innerText")

  def click(self, label):
    self.assertTrue(
      self.evaluate(
        "(() => { const button = [...document.querySelectorAll('button')]"
        f".find(b => b.textContent.trim() === {json.dumps(label)});"
        "if (!button || button.disabled) return false;"
        "button.click(); return true; })()"
      )
    )

  def invalid_config(self):
    self.fixture.env["DESKTOP_LOG_SECRET"] = "fixture-secret-must-not-appear"
    self.fixture.config["mcp"] = {
      "servers": {"broken": {"transport": "$DESKTOP_LOG_SECRET"}}
    }
    self.fixture.write_config()

  def instrument_logs(self, mode):
    # Tauri's invoke property is immutable. Delay/fail only the IPC transport
    # response; actual Rust snapshots still supply the successful log content.
    self.evaluate("""
      window.__originalFetch = window.fetch.bind(window);
      window.__logRequests = 0;
      window.fetch = async (input, init) => {
        const response = await window.__originalFetch(input, init);
        if (!String(input).endsWith('/get_backend_logs')) return response;
        window.__logRequests++;
        let result = await response.json();
        let status = 'ok';
        if (window.__logMode === 'hold' && !window.__heldLogs) {
          window.__heldLogs = true;
          await new Promise(resolve => window.__releaseLogs = resolve);
          window.__oldDelivered = true;
        } else if (window.__logMode === 'wrong') {
          result = {...result, startup_id:'wrong-startup', text:'WRONG_LOG_RESULT'};
        } else if (window.__logMode === 'fail') {
          result = 'injected IPC failure'; status = 'error';
        } else if (window.__logMode === 'pending') {
          await new Promise(() => {});
        }
        return new Response(JSON.stringify(result), {
          headers: {'Content-Type':'application/json', 'Tauri-Response':status}
        });
      };
    """)
    self.evaluate(f"window.__logMode = {json.dumps(mode)}")

  def test_startup_error_has_on_demand_traceback_and_retry_clears_logs(self):
    self.invalid_config()
    host = self.launch()
    self.connect()
    failed = self.state("failed")
    wait_until(lambda: "重试启动后端" in self.body())
    self.assertEqual(failed["error"]["code"], "AppConfigError")
    self.assertNotIn("Traceback", self.body())
    self.instrument_logs("pass")
    self.assertEqual(self.evaluate("window.__logRequests"), 0)
    self.click("查看本次启动日志")
    wait_until(lambda: "Traceback" in self.body())
    self.assertIn("Invalid transport", self.body())
    self.assertIn(failed["startup_id"], self.body())
    self.assertNotIn("fixture-secret-must-not-appear", self.body())
    self.screenshot()
    self.fixture.config["mcp"] = {}
    self.fixture.write_config()
    self.click("重试启动后端")
    ready = self.state("ready")
    logs = self.evaluate("window.__TAURI_INTERNALS__.invoke('get_backend_logs')")
    self.assertEqual(logs["startup_id"], ready["startup_id"])
    self.assertNotEqual(ready["startup_id"], failed["startup_id"])
    self.assertNotIn("Invalid transport", logs["text"])
    self.assertNotIn("Traceback", self.body())
    self.record(failed=failed, ready=ready, logs=logs)
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_late_query_and_wrong_startup_cannot_replace_the_current_error_logs(self):
    self.invalid_config()
    host = self.launch()
    self.connect()
    first = self.state("failed")
    self.instrument_logs("hold")
    self.click("查看本次启动日志")
    wait_until(lambda: self.evaluate("window.__heldLogs"))
    self.fixture.config["mcp"] = {}
    self.fixture.config["model"] = {"default": []}
    self.fixture.write_config()
    self.click("重试启动后端")
    wait_until(lambda: self.snapshot()["startup_id"] != first["startup_id"])
    second = self.state("failed")
    wait_until(lambda: "查看本次启动日志" in self.body())
    self.click("查看本次启动日志")
    wait_until(lambda: "Traceback" in self.body())
    self.assertIn("model.default", self.body())
    self.evaluate("window.__releaseLogs()")
    wait_until(lambda: self.evaluate("window.__oldDelivered"))
    self.assertIn(second["startup_id"], self.body())
    self.assertNotIn(first["startup_id"], self.body())
    self.assertNotIn("Invalid transport", self.body())
    self.evaluate("window.__logMode = 'wrong'")
    self.click("刷新日志")
    wait_until(lambda: "启动已变化，请重新读取日志" in self.body())
    self.assertNotIn("WRONG_LOG_RESULT", self.body())
    self.assertEqual(self.snapshot()["error"], second["error"])
    self.record(first=first, second=second, body=self.body())
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_failed_and_pending_log_queries_do_not_block_retry_or_exit(self):
    self.invalid_config()
    host = self.launch()
    self.connect()
    failed = self.state("failed")
    self.instrument_logs("fail")
    self.click("查看本次启动日志")
    wait_until(lambda: "无法读取本次启动日志" in self.body())
    self.assertEqual(self.snapshot()["error"], failed["error"])
    self.evaluate("window.__logMode = 'pending'")
    self.click("刷新日志")
    wait_until(lambda: "正在读取日志" in self.body())
    self.click("重试启动后端")
    wait_until(lambda: self.snapshot()["startup_id"] != failed["startup_id"])
    retried = self.state("failed")
    wait_until(lambda: "查看本次启动日志" in self.body())
    self.click("查看本次启动日志")
    wait_until(lambda: "正在读取日志" in self.body())
    self.record(failed=failed, retried=retried, body=self.body())
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_continuous_python_stderr_is_bounded_and_fault_reclaims_the_tree(self):
    entry = self.root / "app/desktop.py"
    entry.write_text(
      entry.read_text(encoding="utf-8").replace(
        '    if os.environ.get("DESKTOP_TEST_SYNC_INIT"):',
        """
    import threading
    def flood():
        while True:
            os.write(2, ("持续日志洪泛\\n".encode("utf-8") + b"\\xff") * 512)
    threading.Thread(target=flood, daemon=True).start()
    pathlib.Path("flood-started").touch()
    while not pathlib.Path("fail-flood").exists():
        await asyncio.sleep(0.05)
    raise RuntimeError("日志洪泛中的初始化故障")
    if os.environ.get("DESKTOP_TEST_SYNC_INIT"):
""",
      ),
      encoding="utf-8",
    )
    host = self.launch()
    self.connect()
    wait_until(lambda: (self.root / "flood-started").exists())
    handles = self.fixture.process_handles()
    logs = wait_until(
      lambda: (
        value
        if (
          value := self.evaluate(
            "window.__TAURI_INTERNALS__.invoke('get_backend_logs').then(logs => ({"
            "retained_bytes:logs.retained_bytes, truncated:logs.truncated,"
            "chinese:logs.text.includes('持续日志洪泛'),"
            "replacement:logs.text.includes('�')}))"
          )
        )["truncated"]
        else None
      )
    )
    self.assertEqual(logs["retained_bytes"], 1048576)
    self.assertTrue(logs["chinese"])
    self.assertTrue(logs["replacement"])
    (self.root / "fail-flood").touch()
    failed = self.state("failed")
    self.assertTrue(failed["can_retry"])
    self.assertEqual(failed["error"]["code"], "RuntimeError")
    self.assertEqual(failed["error"]["message"], "日志洪泛中的初始化故障")
    for handle in handles:
      self.assertEqual(
        win32event.WaitForSingleObject(handle, 5000), win32con.WAIT_OBJECT_0
      )
    self.click("查看本次启动日志")
    wait_until(
      lambda: self.evaluate("document.body.innerText.includes('仅显示最近 1 MiB')")
    )
    self.record(failed=failed, retained_bytes=logs["retained_bytes"], truncated=True)
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_runtime_exit_preserves_its_stderr_diagnostic_and_reclaims_descendant(self):
    entry = self.root / "app/desktop.py"
    entry.write_text(
      entry.read_text(encoding="utf-8").replace(
        "async def agent(**kwargs):\n",
        """async def agent(**kwargs):
    import threading
    def crash():
        while not pathlib.Path("crash-backend").exists():
            time.sleep(0.05)
        os.write(2, "运行异常诊断：测试触发退出 73\\n".encode("utf-8"))
        os._exit(73)
    threading.Thread(target=crash, daemon=True).start()
""",
      ),
      encoding="utf-8",
    )
    host = self.launch()
    self.connect()
    self.state("ready")
    handles = self.fixture.process_handles()
    (self.root / "crash-backend").touch()
    failed = self.state("failed")
    self.assertEqual(failed["error"]["code"], "backend_exit")
    for handle in handles:
      self.assertEqual(
        win32event.WaitForSingleObject(handle, 5000), win32con.WAIT_OBJECT_0
      )
    self.click("查看本次启动日志")
    wait_until(lambda: "运行异常诊断：测试触发退出 73" in self.body())
    self.assertNotIn("运行异常诊断", failed["error"]["message"])
    self.record(failed=failed, body=self.body())
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)


if __name__ == "__main__":
  unittest.main()
