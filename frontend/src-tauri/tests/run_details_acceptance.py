"""第17票真实 Tauri、真实 HTTP/SQLite/Graph，用量与详情请求边界。"""

import json

from cancel_partial_acceptance import CancelPartialAcceptance
from desktop_usage_fixtures import MODEL_A, MODEL_B
from failure_partial_acceptance import FailurePartialAcceptance
from message_drafts_acceptance import MessageDraftAcceptance
from window_acceptance import REPO, wait_until


class DetailsEvidence:
  def instrument_details(self):
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source=r"""(() => {
      window.__detailsRequests=[];
      const original=window.fetch.bind(window);
      window.fetch=async (url,init)=>{
        const method=init?.method??'GET', path=new URL(String(url)).pathname;
        const requestRecord={path,method,startedAt:performance.now()};
        if(path.includes('/api/'))window.__detailsRequests.push(requestRecord);
        const response=await original(url,init);
        if(method==='POST'&&path.endsWith('/cancel'))
          window.__cancelSnapshot=await response.clone().json();
        if(method==='GET'&&/\/runs\/[^/]+$/.test(path)){
          requestRecord.snapshot=await response.clone().json();
          if(window.__holdDetails){
            window.__holdDetails=false;
            await new Promise(resolveDetailsResponse=>
              window.__releaseDetails=resolveDetailsResponse);
          }
          if(window.__failDetails){
            window.__failDetails=false;
            return new Response('真实传输边界失败',{status:500});
          }
        }
        requestRecord.finishedAt=performance.now();return response;
      };
    })()""",
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__detailsRequests)"))
    wait_until(lambda: "从一个想法开始" in self.body())

  def open_details(self):
    self.evaluate("document.querySelector('button[aria-label=运行详情]').click()")
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('.run-details'))"))

  def close_details(self):
    self.evaluate(
      "document.querySelector('dialog[open] .overlay-heading button').click()"
    )
    wait_until(
      lambda: not self.evaluate("Boolean(document.querySelector('dialog[open]'))")
    )

  def run_snapshot(self, backend_snapshot, thread):
    history = self.client.get(
      backend_snapshot["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    run_id = history[-1]["run_id"]
    response = self.client.get(
      backend_snapshot["base_url"] + f"/api/threads/{thread}/runs/{run_id}"
    )
    response.raise_for_status()
    return response.json()["data"]

  def details_requests(self):
    return self.evaluate("window.__detailsRequests")

  def save_details(self, **evidence):
    self.record(requests=self.details_requests(), **evidence)
    self.screenshot()


class RunDetailsAcceptance(DetailsEvidence, MessageDraftAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-17/native"

  def setUp(self):
    super().setUp()
    bootstrap = self.root / "app/desktop.py"
    bootstrap.write_text(
      bootstrap.read_text(encoding="utf-8").replace(
        "from runtime_fixtures import deterministic_agent",
        "from desktop_usage_fixtures import usage_agent as deterministic_agent",
      ),
      encoding="utf-8",
    )
    if "zero" in self._testMethodName:
      (self.root / "zero-usage-model").touch()
    if "unknown" in self._testMethodName:
      (self.root / "hold-usage-model").touch()

  def test_running_unknown_reuses_pending_query_and_keeps_one_observation(self):
    host, backend_snapshot, thread = self.start_empty()
    self.instrument_details()
    self.assertTrue(
      self.evaluate("document.querySelector('button[aria-label=运行详情]').disabled")
    )
    self.evaluate("window.__holdDetails=true")
    self.send("实际运行中的未知用量")
    wait_until(lambda: (self.root / "usage-model-ready").exists())
    wait_until(lambda: self.evaluate("Boolean(window.__releaseDetails)"))
    before = self.details_requests()
    snapshot_reads = [
      request
      for request in before
      if request["method"] == "GET"
      and "/runs/" in request["path"]
      and not request["path"].endswith(("/stream", "/messages", "/events"))
    ]
    self.assertEqual(len(snapshot_reads), 1, "已有一个挂起的运行快照 GET")
    self.open_details()
    self.assertIn("正在读取用量", self.body())
    self.assertNotIn("暂无用量数据", self.body())
    self.assertIn("正在刷新详情…", self.body())
    self.assertNotIn(
      "已保存", self.evaluate("document.querySelector('.run-usage').innerText")
    )
    current_snapshot_reads = [
      request
      for request in self.details_requests()
      if request["method"] == "GET"
      and "/runs/" in request["path"]
      and not request["path"].endswith(("/stream", "/messages", "/events"))
    ]
    self.assertEqual(
      len(current_snapshot_reads), len(snapshot_reads), "打开详情复用在读快照请求"
    )
    self.assertEqual(
      sum(request["path"].endswith("/events") for request in self.details_requests()),
      1,
      "打开详情独立读取真实事件历史",
    )
    self.evaluate("window.__releaseDetails()")
    wait_until(
      lambda: (
        "暂无用量数据"
        in self.evaluate("document.querySelector('.run-usage').innerText")
      )
    )
    self.assertIn("仍在结算", self.body())
    self.assertIn("尚未结束", self.body())
    self.close_details()
    self.open_details()
    requests = self.details_requests()
    self.assertEqual(sum(r["path"].endswith("/stream") for r in requests), 1)
    self.assertEqual(sum(r["path"].endswith("/cancel") for r in requests), 0)
    self.save_details(
      snapshot=self.run_snapshot(backend_snapshot, thread), thread=thread
    )
    (self.root / "allow-usage-model").touch()
    self.close_details()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_real_zero_missing_model_and_server_times(self):
    host, backend_snapshot, thread = self.start_empty()
    self.instrument_details()
    self.send("真实零用量")
    wait_until(lambda: "真实零用量已完成" in self.body())
    self.open_details()
    wait_until(lambda: "当前用量已保存" in self.body())
    snapshot = self.run_snapshot(backend_snapshot, thread)
    self.assertEqual(
      snapshot["usage"],
      {
        "total_input": 0,
        "total_output": 0,
        "total_tokens": 0,
        "calls": 1,
        "by_model": {},
      },
    )
    self.assertEqual(
      self.evaluate(
        "[...document.querySelectorAll('.run-usage dd')].map(e=>e.textContent)"
      ),
      ["0", "0", "0", "1"],
    )
    self.evaluate("document.querySelector('.model-usage summary').click()")
    self.assertIn("暂无模型分项", self.body())
    for key in ("created_at", "updated_at", "completed_at"):
      self.assertIsNotNone(snapshot[key])
    self.assertIn(thread, self.body())
    self.assertIn(snapshot["id"], self.body())
    self.evaluate(
      "Object.defineProperty(navigator,'clipboard',{configurable:true,value:{"
      "writeText:async text=>{window.__copied=text}}})"
    )
    for label, expected in (
      ("复制会话 ID", thread),
      ("复制运行 ID", snapshot["id"]),
      ("复制创建时间 UTC", snapshot["created_at"]),
    ):
      self.evaluate(
        f"document.querySelector('button[aria-label={json.dumps(label)}]').click()"
      )
      wait_until(lambda expected=expected: self.evaluate("window.__copied") == expected)
    drawer_geometry = self.evaluate(
      "({cssWidth:getComputedStyle(document.querySelector('.drawer')).width,"
      "rectWidth:document.querySelector('.drawer').getBoundingClientRect().width,"
      "devicePixelRatio:window.devicePixelRatio})"
    )
    # The design specifies CSS pixels; native DPI can round client rect floats.
    self.assertEqual(drawer_geometry["cssWidth"], "400px")
    self.assertIn("UTC：", self.body())
    self.save_details(snapshot=snapshot, thread=thread, drawer_geometry=drawer_geometry)
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_real_multi_model_full_view_failure_preserves_values_and_stale_selection(
    self,
  ):
    host, backend_snapshot, thread = self.start_empty()
    self.instrument_details()
    self.send("真实多模型累计")
    wait_until(lambda: "真实多模型用量已完成" in self.body())
    self.open_details()
    wait_until(lambda: "当前用量已保存" in self.body())
    snapshot = self.run_snapshot(backend_snapshot, thread)
    self.assertEqual(snapshot["usage"]["total_input"], 15)
    self.assertEqual(snapshot["usage"]["total_output"], 12)
    self.assertEqual(snapshot["usage"]["total_tokens"], 27)
    self.assertEqual(snapshot["usage"]["calls"], 2)
    self.assertEqual(set(snapshot["usage"]["by_model"]), {MODEL_A, MODEL_B})
    self.assertFalse(self.evaluate("document.querySelector('.model-usage').open"))
    self.evaluate("document.querySelector('.model-usage summary').click()")
    self.assertIn(MODEL_A, self.body())
    self.click("查看完整模型用量")
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 1
    )
    raw = self.evaluate("document.querySelector('.content-viewer pre').textContent")
    self.assertEqual(json.loads(raw), snapshot["usage"]["by_model"])
    self.click("返回运行详情")
    self.assertTrue(self.evaluate("document.querySelector('.model-usage').open"))
    # A real external second POST is discovered by the existing list/history path.
    response = self.client.post(
      backend_snapshot["base_url"] + f"/api/threads/{thread}/stream",
      json={"message": "第二次真实运行"},
    )
    response.raise_for_status()
    next_snapshot = self.run_snapshot(backend_snapshot, thread)
    self.assertNotEqual(next_snapshot["id"], snapshot["id"])
    wait_until(
      lambda: (
        next_snapshot["id"]
        in self.evaluate("document.querySelector('.run-details')?.innerText ?? ''")
      )
    )
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 1
    )
    self.assertFalse(self.evaluate("document.querySelector('.model-usage').open"))
    self.assertNotIn(
      snapshot["id"], self.evaluate("document.querySelector('.run-details').innerText")
    )
    self.evaluate("window.__failDetails=true")
    self.click("刷新详情")
    wait_until(lambda: "运行信息读取失败" in self.body())
    self.assertEqual(
      self.evaluate(
        "[...document.querySelectorAll('.run-usage .usage-values > div > dd')]"
        ".slice(0,4).map(e=>e.textContent)"
      ),
      ["15", "12", "27", "2"],
    )
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent"), "已完成"
    )
    self.evaluate("window.__holdDetails=true")
    self.click("重试读取")
    wait_until(lambda: self.evaluate("Boolean(window.__releaseDetails)"))
    self.close_details()
    self.click("新建")
    wait_until(
      lambda: (
        "尚未开始运行" in self.evaluate("document.querySelector('.usage').innerText")
      )
    )
    self.evaluate("window.__releaseDetails()")
    self.assertNotIn("27", self.evaluate("document.querySelector('.usage').innerText"))
    self.assertTrue(
      self.evaluate("document.querySelector('button[aria-label=运行详情]').disabled")
    )
    self.save_details(
      snapshot=snapshot,
      next_snapshot=next_snapshot,
      thread=thread,
      raw_models=json.loads(raw),
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


class CancelRunDetailsAcceptance(DetailsEvidence, CancelPartialAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-17/native"

  def test_cancel_pending_snapshot_then_same_updated_at_late_usage(self):
    host, backend_snapshot, thread = self.start_empty()
    self.instrument_details()
    self.send("取消后晚到累计用量")
    wait_until(lambda: (self.root / "cancel-text-ready").exists())
    self.confirm()
    wait_until(lambda: self.evaluate("Boolean(window.__cancelSnapshot)"))
    cancel_snapshot = self.evaluate("window.__cancelSnapshot.data")
    self.assertEqual(cancel_snapshot["status"], "cancelled")
    self.assertTrue(cancel_snapshot["usage_pending"])
    snapshot = wait_until(
      lambda: (
        run
        if not (run := self.run_snapshot(backend_snapshot, thread))["usage_pending"]
        else None
      )
    )
    self.assertEqual(snapshot["updated_at"], cancel_snapshot["updated_at"])
    self.assertEqual(snapshot["usage"]["total_tokens"], 0)
    self.open_details()
    wait_until(lambda: "当前用量已保存" in self.body())
    self.assertIn("已取消", self.body())
    self.assertNotIn("结束时间未取得", self.body())
    self.save_details(
      cancel_snapshot=cancel_snapshot, late_snapshot=snapshot, thread=thread
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


class FailureRunDetailsAcceptance(DetailsEvidence, FailurePartialAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-17/native"

  def test_actual_failure_complete_readonly_error_and_single_foreground(self):
    host, backend_snapshot, thread = self.start_empty()
    self.instrument_details()
    self.send("真实失败详情")
    wait_until(lambda: (self.root / "failure-text-ready").exists())
    (self.root / "allow-failure-model").touch()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "运行失败"
      )
    )
    self.open_details()
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('.details-execution-error pre'))"
      )
    )
    snapshot = self.run_snapshot(backend_snapshot, thread)
    self.assertEqual(
      self.evaluate(
        "document.querySelector('.details-execution-error pre').textContent"
      ),
      snapshot["error"],
    )
    self.click("查看完整执行错误")
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 1
    )
    self.assertEqual(
      self.evaluate("document.querySelector('.content-viewer pre').textContent"),
      snapshot["error"],
    )
    self.save_details(snapshot=snapshot, thread=thread)
    self.click("返回运行详情")
    self.close_details()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
