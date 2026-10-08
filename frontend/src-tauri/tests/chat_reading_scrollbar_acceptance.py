"""Real Chromium scrollbar against useChatReading, without a backend or user profile.

Requires Vite at 127.0.0.1:5173 and Edge. Run with the repo's .venv Python:
python -m unittest chat_reading_scrollbar_acceptance -v
"""

import base64
import json
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import httpx
from websockets.sync.client import connect

REPO = Path(__file__).resolve().parents[3]


class ScrollbarAcceptance(unittest.TestCase):
  def setUp(self):
    self.artifacts = REPO / ".scratch/chat-reading-scrollbar"
    self.artifacts.mkdir(parents=True, exist_ok=True)
    self.profile = tempfile.TemporaryDirectory(dir=self.artifacts)
    self.addCleanup(self.profile.cleanup)
    with socket.socket() as probe:
      probe.bind(("127.0.0.1", 0))
      port = probe.getsockname()[1]
    self.browser = subprocess.Popen(
      [
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        f"--user-data-dir={self.profile.name}",
        f"--remote-debugging-port={port}",
        "--window-size=900,700",
        "http://127.0.0.1:5173/tests/fixtures/chat-reading-scrollbar.html",
      ],
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
      creationflags=subprocess.CREATE_NO_WINDOW,
    )
    self.addCleanup(self.stop_browser)
    self.client = httpx.Client(trust_env=False, timeout=2)
    self.addCleanup(self.client.close)
    deadline = time.monotonic() + 20
    while True:
      try:
        targets = self.client.get(f"http://127.0.0.1:{port}/json/list").json()
        endpoint = next(
          target["webSocketDebuggerUrl"]
          for target in targets
          if target["type"] == "page" and "chat-reading-scrollbar.html" in target["url"]
        )
        break
      except (httpx.HTTPError, StopIteration):
        if time.monotonic() > deadline:
          raise
        time.sleep(0.1)
    self.ws = connect(endpoint, proxy=None)
    self.addCleanup(self.ws.close)
    self.sequence = 0
    deadline = time.monotonic() + 20
    while not self.evaluate("Boolean(window.readingFixture?.snapshot()?.total > 1000)"):
      self.assertLess(time.monotonic(), deadline, "Vite fixture did not load")
      time.sleep(0.1)
    time.sleep(0.2)

  def stop_browser(self):
    self.browser.terminate()
    self.browser.wait(timeout=10)

  def call(self, method, **params):
    self.sequence += 1
    self.ws.send(json.dumps({"id": self.sequence, "method": method, "params": params}))
    while True:
      reply = json.loads(self.ws.recv(timeout=10))
      if reply.get("id") == self.sequence:
        self.assertNotIn("error", reply)
        self.assertNotIn("exceptionDetails", reply["result"])
        return reply["result"]

  def evaluate(self, expression):
    return (
      self.call(
        "Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True
      )
      .get("result", {})
      .get("value")
    )

  def snapshot(self):
    return self.evaluate("window.readingFixture.snapshot()")

  def test_slow_scrollbar_drag_hold_release_and_new_content(self):
    self.assertTrue(self.snapshot()["following"])
    coordinates = self.evaluate("""(() => {
      const t=document.querySelector('.timeline'), r=t.getBoundingClientRect();
      const thumb=Math.max(20,t.clientHeight*t.clientHeight/t.scrollHeight);
      return {x:r.right-5,y:r.bottom-thumb/2,destination:r.top+r.height/2};
    })()""")
    self.call(
      "Input.dispatchMouseEvent",
      type="mousePressed",
      button="left",
      buttons=1,
      clickCount=1,
      x=coordinates["x"],
      y=coordinates["y"],
    )
    samples = []
    try:
      time.sleep(1.2)
      self.call(
        "Input.dispatchMouseEvent",
        type="mouseMoved",
        button="left",
        buttons=1,
        x=coordinates["x"],
        y=coordinates["destination"],
      )
      time.sleep(0.2)
      dragged = self.snapshot()
      samples.append(dragged)
      self.assertFalse(dragged["following"], dragged)
      self.assertGreater(dragged["scrollTop"], 20)
      self.assertLess(dragged["scrollTop"], dragged["total"] - dragged["height"] - 20)
      for _ in range(15):
        time.sleep(0.1)
        samples.append(self.snapshot())
        self.assertAlmostEqual(samples[-1]["scrollTop"], dragged["scrollTop"], delta=2)
    finally:
      self.call(
        "Input.dispatchMouseEvent",
        type="mouseReleased",
        button="left",
        buttons=0,
        clickCount=1,
        x=coordinates["x"],
        y=coordinates["destination"],
      )
      (self.artifacts / "samples.json").write_text(
        json.dumps(samples), encoding="utf-8"
      )
      screenshot = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / "window.png").write_bytes(base64.b64decode(screenshot))
    time.sleep(1.2)
    self.assertAlmostEqual(self.snapshot()["scrollTop"], dragged["scrollTop"], delta=2)
    self.evaluate("window.readingFixture.append(); window.readingFixture.resize()")
    time.sleep(0.2)
    self.assertFalse(self.snapshot()["following"])
    self.assertTrue(self.snapshot()["hasNewContent"])
    self.assertAlmostEqual(self.snapshot()["scrollTop"], dragged["scrollTop"], delta=2)
    self.evaluate("document.querySelector('.reading-controls button').click()")
    time.sleep(0.2)
    latest = self.snapshot()
    self.assertTrue(latest["following"])
    self.assertAlmostEqual(
      latest["scrollTop"], latest["total"] - latest["height"], delta=2
    )

  def test_layout_updates_keep_following_without_user_scroll(self):
    self.evaluate("window.readingFixture.append(); window.readingFixture.resize()")
    time.sleep(0.2)
    latest = self.snapshot()
    self.assertTrue(latest["following"])
    self.assertAlmostEqual(
      latest["scrollTop"], latest["total"] - latest["height"], delta=2
    )

  def test_nested_wheel_and_keyboard_preserve_scroll_ownership(self):
    coordinates = self.evaluate("""(() => {
      const parent=document.querySelector('[data-reading-anchor]:last-child');
      const nested=document.createElement('div'); nested.id='nested-scroll';
      nested.style.cssText='height:60px;overflow:auto';
      nested.innerHTML='<div style="height:400px">工具结果</div>';
      parent.append(nested);
      const r=nested.getBoundingClientRect();return {x:r.left+10,y:r.top+10};
    })()""")
    time.sleep(0.2)
    self.call(
      "Input.dispatchMouseEvent",
      type="mouseWheel",
      x=coordinates["x"],
      y=coordinates["y"],
      deltaX=0,
      deltaY=100,
    )
    time.sleep(0.2)
    self.assertGreater(
      self.evaluate("document.getElementById('nested-scroll').scrollTop"), 0
    )
    self.assertTrue(self.snapshot()["following"])
    self.evaluate("document.querySelector('.timeline').focus({preventScroll:true})")
    for key, key_code in [("Home", 36), ("End", 35)]:
      for event_type in ("keyDown", "keyUp"):
        self.call(
          "Input.dispatchKeyEvent",
          type=event_type,
          key=key,
          code=key,
          windowsVirtualKeyCode=key_code,
        )
      time.sleep(0.3)
      self.assertEqual(self.snapshot()["following"], key == "End")
      expected_top = (
        0 if key == "Home" else self.snapshot()["total"] - self.snapshot()["height"]
      )
      self.assertAlmostEqual(self.snapshot()["scrollTop"], expected_top, delta=2)


if __name__ == "__main__":
  unittest.main()
