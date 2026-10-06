"""第18票真实 Tauri / HTTP / SQLite / Graph 的只读运行记录。"""

import json

from approval_resume_acceptance import ApprovalResumeAcceptance
from run_details_acceptance import DetailsEvidence
from window_acceptance import REPO, wait_until


class RunEventsAcceptance(DetailsEvidence, ApprovalResumeAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-18/native"

  def instrument_events(self):
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source=r"""(() => {
        window.__eventsRequests=[];
        const original=window.fetch.bind(window);
        window.fetch=async (url,init)=>{
          const path=new URL(String(url)).pathname;
          if(!path.endsWith('/events'))return original(url,init);
          const query={path,startedAt:performance.now(),aborted:false};
          window.__eventsRequests.push(query);
          init?.signal?.addEventListener('abort',()=>query.aborted=true,{once:true});
          const response=await original(url,init);
          query.facts=await response.clone().json();
          if(window.__holdEvents){window.__holdEvents=false;
            await new Promise(resolveEvents=>window.__releaseEvents=resolveEvents);}
          if(window.__failEvents){window.__failEvents=false;
            return new Response('事件读取传输故障',{status:500});}
          if(window.__invalidEvents){window.__invalidEvents=false;
            return Response.json({data:[{seq:900,created_at:'2026-10-06T00:00:00Z',
              category:'unknown',event_type:'unknown',payload:{path:'x.png'}}]});}
          query.finishedAt=performance.now();return response;
        };
      })()""",
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__eventsRequests)"))
    wait_until(lambda: "审批请求已核实，等待处理。" in self.body())

  def read_events(self, backend, thread, run_id):
    response = self.client.get(
      backend["base_url"] + f"/api/threads/{thread}/runs/{run_id}/events"
    )
    response.raise_for_status()
    self.assertEqual(response.headers.get("cache-control"), "no-store")
    return response.json()["data"]

  def read_visible_sequences(self):
    return self.evaluate(
      "[...document.querySelectorAll('.event-row')].map(row=>Number(row.dataset.seq))"
    )

  def read_event_requests(self):
    return self.evaluate("window.__eventsRequests")

  def install_copy_boundary(self):
    self.evaluate(
      "Object.defineProperty(navigator,'clipboard',{configurable:true,value:{"
      "writeText:async text=>{window.__eventCopy=text}}})"
    )

  def test_required_complete_json_actual_decisions_eof_and_reading_position(self):
    host, backend, thread, run_id = self.begin_approval()
    self.instrument_events()
    self.choose_decision(1, "reject")
    self.update_rejection_reason(1, "本地未提交原因不能进入历史")
    self.open_details()
    wait_until(lambda: "请求审批" in self.body())
    events = self.read_events(backend, thread, run_id)
    self.assertEqual(
      self.read_visible_sequences(),
      [e["seq"] for e in events if e["category"] != "message"],
    )
    self.assertNotIn(
      "本地未提交原因不能进入历史",
      self.evaluate("document.querySelector('.run-events').innerText"),
    )
    required_event = next(e for e in events if e["event_type"] == "required")
    selector = f".event-row[data-seq='{required_event['seq']}']"
    self.evaluate(
      f"document.querySelector({json.dumps(selector + ' summary')}).click()"
    )
    geometry = self.evaluate(
      f"(() => {{const block=document.querySelector({json.dumps(selector + ' pre')});"
      "return {maxHeight:getComputedStyle(block).maxHeight,"
      "fontSize:getComputedStyle(block).fontSize,lineHeight:getComputedStyle(block).lineHeight,"
      "height:block.clientHeight,"
      "scrollHeight:block.scrollHeight};})()"
    )
    self.assertEqual(geometry["maxHeight"], "320px")
    self.assertEqual(geometry["fontSize"], "12px")
    self.assertEqual(geometry["lineHeight"], "20px")
    self.assertGreater(geometry["scrollHeight"], geometry["height"])
    event_json = self.evaluate(
      f"document.querySelector({json.dumps(selector + ' pre')}).textContent"
    )
    self.assertEqual(json.loads(event_json), required_event)
    self.install_copy_boundary()
    copy_selector = json.dumps(selector + ' button[aria-label="复制完整事件"]')
    self.evaluate(f"document.querySelector({copy_selector}).click()")
    wait_until(lambda: self.evaluate("window.__eventCopy") == event_json)
    self.evaluate("document.querySelector('.run-details').scrollTop=250")
    position = self.evaluate("document.querySelector('.run-details').scrollTop")
    view_selector = json.dumps(selector + " .content-actions > button")
    self.evaluate(
      f"(() => {{const trigger=document.querySelector({view_selector});"
      "trigger.focus({preventScroll:true});trigger.click();})()"
    )
    wait_until(
      lambda: self.evaluate("Boolean(document.querySelector('.run-details-subview'))")
    )
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 1
    )
    self.assertEqual(
      self.evaluate("document.querySelector('dialog[open] textarea')"), None
    )
    self.assertEqual(
      self.evaluate("document.querySelector('.content-viewer pre').textContent"),
      event_json,
    )
    self.click("返回运行详情")
    self.assertEqual(
      self.evaluate("document.querySelector('.run-details').scrollTop"), position
    )
    self.assertEqual(
      self.evaluate("document.activeElement.textContent"), "查看完整事件"
    )
    self.evaluate("document.querySelector('.event-toolbar input').click()")
    self.assertEqual(self.read_visible_sequences(), [e["seq"] for e in events])
    self.screenshot()
    (self.artifacts / "window.png").rename(self.artifacts / "required.png")
    self.close_details()
    self.select_all_decisions()
    self.click("提交决策")
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "运行中"
      )
    )
    self.open_details()
    wait_until(lambda: "审批已处理" in self.body())
    self.assertIn(
      "拒绝原因：  拒绝原因保留",
      self.evaluate("document.querySelector('.run-events').innerText"),
    )
    self.assertNotIn(
      "本地未提交原因不能进入历史",
      self.evaluate("document.querySelector('.run-events').innerText"),
    )
    self.evaluate("document.querySelector('.run-details').scrollTop=180")
    before_eof_position = self.evaluate(
      "document.querySelector('.run-details').scrollTop"
    )
    before_eof_queries = len(self.read_event_requests())
    (self.root / "allow-approval-tools").touch()
    wait_until(
      lambda: (
        "运行已完成" in self.evaluate("document.querySelector('.run-events').innerText")
      )
    )
    wait_until(lambda: len(self.read_event_requests()) > before_eof_queries)
    self.assertEqual(len(self.read_event_requests()), before_eof_queries + 1)
    self.assertEqual(
      self.evaluate("document.querySelector('.run-details').scrollTop"),
      before_eof_position,
    )
    final_events = self.read_events(backend, thread, run_id)
    self.assertEqual(
      self.read_visible_sequences(),
      [e["seq"] for e in final_events if e["category"] != "message"],
    )
    self.record(
      thread=thread,
      run_id=run_id,
      events=events,
      final_events=final_events,
      full_event=json.loads(event_json),
      geometry=geometry,
      requests=self.read_event_requests(),
      position=position,
      before_eof_position=before_eof_position,
    )
    # Capture the new timeline itself after the reading-position assertions.
    self.evaluate("document.querySelector('.run-events').scrollIntoView()")
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_cancel_records_and_failed_event_query_keep_snapshot_then_close_aborts(self):
    host, backend, thread, run_id = self.begin_approval()
    self.instrument_events()
    self.click("取消运行")
    self.click("确认取消")
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已取消"
      )
    )
    self.open_details()
    wait_until(lambda: "审批已失效" in self.body())
    cancel_events = self.read_events(backend, thread, run_id)
    self.assertTrue(any(e["event_type"] == "invalidated" for e in cancel_events))
    self.assertIn("因运行取消失效", self.body())
    self.assertEqual(list(self.root.glob("approval-executed-*")), [])
    self.evaluate("window.__failEvents=true")
    self.click("刷新详情")
    wait_until(lambda: "运行记录读取失败" in self.body())
    self.assertNotIn("运行信息读取失败", self.body())
    self.assertIn(
      run_id, self.evaluate("document.querySelector('.run-information').innerText")
    )
    sequences = self.read_visible_sequences()
    self.evaluate("window.__holdEvents=true")
    self.click("重试运行记录")
    wait_until(lambda: self.evaluate("Boolean(window.__releaseEvents)"))
    self.close_details()
    self.assertTrue(self.read_event_requests()[-1]["aborted"])
    self.evaluate("window.__releaseEvents()")
    self.open_details()
    wait_until(lambda: "审批已失效" in self.body())
    self.assertEqual(self.read_visible_sequences(), sequences)
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent"), "已取消"
    )
    self.record(
      events=cancel_events, requests=self.read_event_requests(), sequences=sequences
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_incompatible_response_is_raw_readonly_problem_and_not_a_fact(self):
    host, backend, thread, run_id = self.begin_approval()
    self.instrument_events()
    self.open_details()
    wait_until(lambda: "请求审批" in self.body())
    sequences = self.read_visible_sequences()
    self.evaluate("window.__invalidEvents=true")
    self.click("刷新运行记录")
    wait_until(lambda: "运行记录协议问题" in self.body())
    self.assertEqual(self.read_visible_sequences(), sequences)
    self.click("查看读取问题")
    wait_until(
      lambda: self.evaluate("Boolean(document.querySelector('.content-viewer pre'))")
    )
    protocol_problem = json.loads(
      self.evaluate("document.querySelector('.content-viewer pre').textContent")
    )
    self.assertEqual(protocol_problem["raw"]["seq"], 900)
    self.assertEqual(protocol_problem["raw"]["payload"], {"path": "x.png"})
    self.assertEqual(
      self.evaluate(
        "document.querySelectorAll('.content-viewer img,.content-viewer a').length"
      ),
      0,
    )
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 1
    )
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent"), "等待审批"
    )
    self.record(
      events=self.read_events(backend, thread, run_id),
      requests=self.read_event_requests(),
      raw_problem=protocol_problem,
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
