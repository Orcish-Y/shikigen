"""第 12 票公开 HTTP：多 Interrupt / 多动作、同 Run 继续与真实工具副作用。"""

import tempfile
import unittest
from pathlib import Path

import httpx
from desktop_approval_fixtures import create_approval_workbench_agent
from langgraph.checkpoint.memory import InMemorySaver
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime
from sse_fixtures import parse_sse_frames

from app.server import create_app


class FrontendApprovalFlowTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.workspace = Path(directory.name)
    store = await ChatStore.open(self.workspace / "chat.db")
    self.addAsyncCleanup(store.close)
    agent = await create_approval_workbench_agent(
      config=None,
      middlewares=[],
      checkpointer=InMemorySaver(),
      tool_registry=None,
      workspace_root=self.workspace,
    )
    runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=agent,
      chat_store=store,
    )
    self.addAsyncCleanup(runtime.lifecycle.shutdown)
    server = create_app()
    server.state.runtime = runtime
    self.client = httpx.AsyncClient(
      transport=httpx.ASGITransport(app=server), base_url="http://test"
    )
    self.addAsyncCleanup(self.client.aclose)

  async def test_all_interrupts_and_ordered_decisions_resume_same_run(self):
    thread_id = (await self.client.post("/api/threads")).json()["thread_id"]
    path = f"/api/threads/{thread_id}"
    response = await self.client.post(path + "/stream", json={"message": "逐项审批"})
    self.assertEqual(response.status_code, 200)
    frames = parse_sse_frames(response.text)
    run_id = frames[0]["data"]["run_id"]
    replay = await self.client.get(path + f"/runs/{run_id}/stream")
    self.assertEqual(replay.status_code, 200)
    facts = parse_sse_frames(replay.text)
    request = next(
      frame["data"]["payload"]
      for frame in facts
      if frame["event"] == "event" and frame["data"]["event_type"] == "required"
    )
    self.assertEqual(len(request["interrupts"]), 2)
    self.assertEqual(
      [
        len(interrupt["value"]["action_requests"])
        for interrupt in request["interrupts"]
      ],
      [2, 2],
    )
    self.assertEqual(list(self.workspace.glob("approval-executed-*")), [])
    decisions_path = path + f"/runs/{run_id}/approval-decisions"
    responses = {
      interrupt["id"]: {
        "decisions": [
          {"type": "approve"},
          {"type": "reject", "message": "  不覆盖原文件\n"},
        ]
      }
      for interrupt in request["interrupts"]
    }
    incomplete_response = await self.client.post(
      decisions_path,
      json={
        "responses": {request["interrupts"][0]["id"]: next(iter(responses.values()))}
      },
    )
    self.assertEqual(incomplete_response.status_code, 409)
    self.assertEqual(list(self.workspace.glob("approval-executed-*")), [])
    (self.workspace / "allow-approval-tools").touch()
    resume_response = await self.client.post(
      decisions_path, json={"responses": responses}
    )
    self.assertEqual(resume_response.status_code, 200)
    resumed_frames = parse_sse_frames(resume_response.text)
    self.assertEqual(resumed_frames[0]["data"]["run_id"], run_id)
    snapshot = (await self.client.get(path + f"/runs/{run_id}")).json()["data"]
    self.assertEqual(snapshot["status"], "completed")
    self.assertEqual(
      sorted(
        operation.name for operation in self.workspace.glob("approval-executed-*")
      ),
      ["approval-executed-child-0", "approval-executed-main-0"],
    )
    actual_responses = next(
      frame["data"]["payload"]["responses"]
      for frame in resumed_frames
      if frame["event"] == "event" and frame["data"]["event_type"] == "resolved"
    )
    self.assertEqual(actual_responses, responses)
    duplicate = await self.client.post(decisions_path, json={"responses": responses})
    self.assertEqual(duplicate.status_code, 409)
    history = (await self.client.get(path + "/messages")).json()["data"]
    self.assertTrue(all(message["run_id"] == run_id for message in history))
