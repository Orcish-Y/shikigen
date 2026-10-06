"""第19票：真实 Tauri 的取消晚量及公开传输边界上的有限核实。"""

import re

from pagination_acceptance import PaginationAcceptance
from run_details_acceptance import CancelRunDetailsAcceptance, RunDetailsAcceptance
from window_acceptance import REPO, wait_until


class UsageEvidence:
  def connect(self):
    # Wait for the stable Tauri page via the existing acceptance handshake.
    PaginationAcceptance.connect(self)

  def instrument_usage(self):
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source=r"""(() => {
      window.__usageRequests=[];
      window.__pendingUsage=true;
      window.__usageFailures=0;
      const fetchFromBackend=window.fetch.bind(window);
      window.fetch=async(url,init)=>{
        const path=new URL(String(url)).pathname, method=init?.method??'GET';
        if(!/\/runs\/[^/]+$/.test(path)||method!=='GET')
          return fetchFromBackend(url,init);
        const request={path,method,startedAt:performance.now()};
        window.__usageRequests.push(request);
        init?.signal?.addEventListener('abort',()=>request.isAborted=true,{once:true});
        if(window.__usageFailures>0){
          window.__usageFailures--;
          request.finishedAt=performance.now();request.status=503;
          return new Response('测试公开传输边界 busy',
            {status:503,headers:{'Retry-After':'1'}});
        }
        const response=await fetchFromBackend(url,init);
        const envelope=await response.clone().json();
        request.actualSnapshot=structuredClone(envelope.data);
        if(window.__pendingUsage && envelope.data.status==='completed'){
          envelope.data.usage_pending=true;
          request.isPendingInjected=true;
        }
        request.finishedAt=performance.now();request.status=response.status;
        return new Response(JSON.stringify(envelope),
          {status:response.status,headers:response.headers});
      };
    })()""",
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__usageRequests)"))
    wait_until(lambda: "从一个想法开始" in self.body())

  def read_usage_requests(self):
    return self.evaluate("window.__usageRequests")

  def read_summary(self):
    return self.evaluate("document.querySelector('.usage')?.innerText ?? ''")

  def save_usage(self, **evidence):
    self.record(
      requests=self.read_usage_requests(), page_target=self.page_target, **evidence
    )
    self.screenshot()


class UsageSettlementAcceptance(UsageEvidence, RunDetailsAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-19/native"

  def begin_pending_usage(self):
    host, backend_snapshot, thread = self.start_empty()
    self.instrument_usage()
    self.send("第19票公开 GET 边界保持待结算")
    wait_until(lambda: "真实多模型用量已完成" in self.body())
    wait_until(lambda: "仍在结算" in self.read_summary())
    wait_until(lambda: "正在刷新用量" not in self.read_summary())
    return host, backend_snapshot, thread

  def test_twelve_real_time_reads_pause_and_manual_continue_in_summary_and_details(
    self,
  ):
    host, backend_snapshot, thread = self.begin_pending_usage()
    initial_reads = len(self.read_usage_requests())
    # Real clock: twelve completed GETs, each followed by a five-second wait.
    wait_until(lambda: "自动核实已暂停" in self.read_summary(), timeout=90)
    requests = self.read_usage_requests()
    self.assertEqual(len(requests) - initial_reads, 12)
    for previous, following in zip(
      requests[initial_reads - 1 :], requests[initial_reads:], strict=False
    ):
      self.assertGreaterEqual(following["startedAt"] - previous["finishedAt"], 4800)
    self.screenshot()
    (self.artifacts / "paused-summary.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.open_details()
    wait_until(
      lambda: (
        "自动核实已暂停"
        in self.evaluate("document.querySelector('.run-usage').innerText")
      )
    )
    wait_until(lambda: "正在刷新用量" not in self.body())
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 1
    )
    self.assertEqual(
      self.evaluate(
        "getComputedStyle(document.querySelector('.run-usage "
        ".settlement-status')).fontSize"
      ),
      "14px",
    )
    self.evaluate("window.__pendingUsage=false")
    before_manual = len(self.read_usage_requests())
    self.evaluate("document.querySelector('.run-usage .usage-continue').click()")
    wait_until(
      lambda: (
        "当前用量已保存"
        in self.evaluate("document.querySelector('.run-usage').innerText")
      )
    )
    self.assertEqual(len(self.read_usage_requests()), before_manual + 1)
    snapshot = self.run_snapshot(backend_snapshot, thread)
    self.assertFalse(snapshot["usage_pending"])
    self.assertEqual(snapshot["usage"]["total_tokens"], 27)
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent"), "已完成"
    )
    self.close_details()
    self.assertIn("当前用量已保存", self.read_summary())
    self.save_usage(
      initial_reads=initial_reads,
      snapshot=snapshot,
      thread=thread,
      boundary=(
        "pending=true injected only at GET response boundary; "
        "actual model totals and backend facts retained"
      ),
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_recoverable_failures_stop_after_three_retries_and_manual_read_recovers(self):
    host, backend_snapshot, thread = self.begin_pending_usage()
    initial_reads = len(self.read_usage_requests())
    self.evaluate("window.__usageFailures=4")
    wait_until(lambda: "用量读取失败" in self.read_summary(), timeout=30)
    requests = self.read_usage_requests()
    failures = requests[initial_reads:]
    self.assertEqual(len(failures), 4)
    self.assertTrue(all(request["status"] == 503 for request in failures))
    for previous, following, delay in zip(
      failures, failures[1:], [1000, 2000, 5000], strict=False
    ):
      self.assertGreaterEqual(
        following["startedAt"] - previous["finishedAt"], delay - 200
      )
    self.assertIn("27", self.read_summary())
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent"), "已完成"
    )
    self.evaluate("window.__pendingUsage=false")
    self.evaluate("document.querySelector('.usage .usage-continue').click()")
    wait_until(lambda: "当前用量已保存" in self.read_summary())
    self.assertEqual(len(self.read_usage_requests()), initial_reads + 5)
    self.save_usage(
      snapshot=self.run_snapshot(backend_snapshot, thread),
      thread=thread,
      boundary=(
        "503 and pending injected at public fetch boundary; "
        "actual HTTP/SQLite/Graph totals retained"
      ),
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


class CancelUsageSettlementAcceptance(CancelRunDetailsAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-19/native"

  def test_actual_cancel_late_usage_is_verified_with_details_closed(self):
    host, backend_snapshot, thread = self.start_empty()
    self.instrument_details()
    self.send("实际取消后的用量与消息分别核实")
    wait_until(lambda: (self.root / "cancel-text-ready").exists())
    self.confirm()
    wait_until(lambda: self.evaluate("Boolean(window.__cancelSnapshot)"))
    cancellation = self.evaluate("window.__cancelSnapshot.data")
    self.assertTrue(cancellation["usage_pending"])
    self.assertEqual(cancellation["status"], "cancelled")
    wait_until(
      lambda: (
        "当前用量已保存" in self.evaluate("document.querySelector('.usage').innerText")
      ),
      timeout=20,
    )
    self.assertFalse(self.evaluate("Boolean(document.querySelector('dialog[open]'))"))
    late_snapshot = self.run_snapshot(backend_snapshot, thread)
    self.assertFalse(late_snapshot["usage_pending"])
    self.assertEqual(late_snapshot["updated_at"], cancellation["updated_at"])
    self.assertEqual(late_snapshot["usage"]["total_tokens"], 0)
    self.assertIn("已取消", self.body())
    queries = [
      request
      for request in self.details_requests()
      if request["method"] == "GET" and re.search(r"/runs/[^/]+$", request["path"])
    ]
    self.assertTrue(
      any(
        not request["snapshot"]["data"]["usage_pending"]
        and request["snapshot"]["data"]["status"] == "cancelled"
        for request in queries
      )
    )
    self.save_details(
      cancellation=cancellation,
      late_snapshot=late_snapshot,
      thread=thread,
      boundary="actual cancellation and usage settlement; no modified GET envelope",
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
