import unittest

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime
from shikigen.core.loop import run_agent_loop
from shikigen.core.run_manager import RunRecord
from shikigen.core.stream import Stream
from shikigen.middleware.goal_middleware import (
  GoalAgentState,
  GoalEvaluator,
  GoalMiddleware,
  GoalResult,
)


class StubGoalEvaluator:
  def __init__(self, *results: GoalResult):
    self.results = list(results)
    self.calls: list[tuple[str, str]] = []

  async def evaluate(self, goal: str, messages_text: str) -> GoalResult:
    self.calls.append((goal, messages_text))
    return self.results.pop(0)


class GoalEvaluatorTests(unittest.IsolatedAsyncioTestCase):
  async def test_parses_yes_followed_by_newline(self) -> None:
    model = FakeMessagesListChatModel(
      responses=[AIMessage(content="YES\nThe tool output proves completion.")]
    )

    result = await GoalEvaluator(model).evaluate("finish task", "tool: done")

    self.assertTrue(result.satisfied)
    self.assertEqual(result.reason, "The tool output proves completion.")

  async def test_treats_no_as_unsatisfied(self) -> None:
    model = FakeMessagesListChatModel(
      responses=[AIMessage(content="NO Missing execution evidence.")]
    )

    result = await GoalEvaluator(model).evaluate("run file", "file created")

    self.assertFalse(result.satisfied)
    self.assertEqual(result.reason, "Missing execution evidence.")


class GoalMiddlewareTests(unittest.IsolatedAsyncioTestCase):
  async def test_evaluator_output_is_not_published_as_agent_message(self) -> None:
    evaluator_model = FakeMessagesListChatModel(
      responses=[AIMessage(content="YES evaluator-only explanation")]
    )
    agent_model = FakeMessagesListChatModel(
      responses=[AIMessage(content="agent-visible answer")]
    )
    agent = create_agent(
      model=agent_model,
      tools=[],
      middleware=[GoalMiddleware(GoalEvaluator(evaluator_model))],
      checkpointer=InMemorySaver(),
    )
    stream = Stream()

    await run_agent_loop(
      agent,
      HumanMessage(content="/goal finish task"),
      record=RunRecord(
        run_id="goal-run",
        thread_id="goal-output-thread",
        stream=stream,
      ),
    )
    events = [event async for event in stream.subscribe()]
    streamed_text = "".join(
      event.data["text"] for event in events if event.event == "message"
    )

    self.assertIn("agent-visible answer", streamed_text)
    self.assertNotIn("evaluator-only explanation", streamed_text)

  async def test_compiled_agent_continues_within_one_graph_run(self) -> None:
    evaluator = StubGoalEvaluator(
      GoalResult(False, "More work is needed."),
      GoalResult(True, "The second response completed the task."),
    )
    agent_model = FakeMessagesListChatModel(
      responses=[
        AIMessage(content="I only started the task."),
        AIMessage(content="I completed the remaining work."),
      ]
    )
    agent = create_agent(
      model=agent_model,
      tools=[],
      middleware=[GoalMiddleware(evaluator)],
      checkpointer=InMemorySaver(),
    )
    config: RunnableConfig = {"configurable": {"thread_id": "goal-thread"}}

    await agent.ainvoke(
      {"messages": [HumanMessage(content="/goal finish task")]},
      config=config,
    )
    state = await agent.aget_state(config)

    self.assertEqual(len(evaluator.calls), 2)
    self.assertEqual(state.values["goal_status"], "satisfied")
    self.assertEqual(state.values["goal_continuations"], 1)
    self.assertEqual(
      state.values["goal_reason"],
      "The second response completed the task.",
    )
    self.assertTrue(
      any(
        isinstance(message, HumanMessage) and "<system-reminder>" in message.text
        for message in state.values["messages"]
      )
    )

  def test_before_agent_activates_goal_and_records_message_boundary(self) -> None:
    evaluator = StubGoalEvaluator()
    middleware = GoalMiddleware(evaluator)
    state: GoalAgentState = {
      "messages": [
        HumanMessage(content="old task"),
        AIMessage(content="old answer"),
        HumanMessage(content="/goal create and run hello.py"),
      ]
    }

    update = middleware.before_agent(
      state,
      Runtime(context=None),
    )

    self.assertEqual(update["goal_status"], "running")
    self.assertEqual(update["goal_continuations"], 0)
    self.assertEqual(update["goal_start_index"], 2)

  def test_before_agent_is_inactive_without_a_goal_message(self) -> None:
    middleware = GoalMiddleware(StubGoalEvaluator())

    update = middleware.before_agent(
      {"messages": []},
      Runtime(context=None),
    )

    self.assertEqual(update["goal_status"], "inactive")

  async def test_satisfied_goal_stops_without_jumping_to_model(self) -> None:
    evaluator = StubGoalEvaluator(GoalResult(True, "Execution output observed."))
    middleware = GoalMiddleware(evaluator)
    state: GoalAgentState = {
      "messages": [
        HumanMessage(content="old task"),
        HumanMessage(content="/goal run hello.py"),
        AIMessage(
          content="I ran it.",
          tool_calls=[
            {"id": "call-1", "name": "shell", "args": {"cmd": "python hello.py"}}
          ],
        ),
        ToolMessage(content="Hello", tool_call_id="call-1"),
        AIMessage(content="The program printed Hello."),
      ],
      "goal_status": "running",
      "goal_continuations": 0,
      "goal_start_index": 1,
    }

    update = await middleware.aafter_agent(
      state,
      Runtime(context=None),
    )

    self.assertEqual(
      update,
      {
        "goal_status": "satisfied",
        "goal_reason": "Execution output observed.",
      },
    )
    goal, messages_text = evaluator.calls[0]
    self.assertEqual(goal, "run hello.py")
    self.assertNotIn("old task", messages_text)
    self.assertIn("python hello.py", messages_text)
    self.assertIn("Hello", messages_text)

  async def test_unsatisfied_goal_injects_continuation_and_jumps(self) -> None:
    evaluator = StubGoalEvaluator(GoalResult(False, "The file was not run."))
    middleware = GoalMiddleware(
      evaluator,
      max_continuations=2,
    )
    state: GoalAgentState = {
      "messages": [
        HumanMessage(content="/goal create and run hello.py"),
        AIMessage(content="I created hello.py."),
      ],
      "goal_status": "running",
      "goal_continuations": 0,
      "goal_start_index": 0,
    }

    update = await middleware.aafter_agent(
      state,
      Runtime(context=None),
    )

    self.assertIsNotNone(update)
    assert update is not None
    self.assertEqual(update["jump_to"], "model")
    self.assertEqual(update["goal_status"], "running")
    self.assertEqual(update["goal_continuations"], 1)
    self.assertIsInstance(update["messages"][0], HumanMessage)
    self.assertIn("Continuation: 1/2", update["messages"][0].text)

  async def test_final_continuation_is_evaluated_before_exhaustion(self) -> None:
    evaluator = StubGoalEvaluator(GoalResult(False, "Still incomplete."))
    middleware = GoalMiddleware(
      evaluator,
      max_continuations=2,
    )
    state: GoalAgentState = {
      "messages": [
        HumanMessage(content="/goal finish task"),
        AIMessage(content="I could not finish."),
      ],
      "goal_status": "running",
      "goal_continuations": 2,
      "goal_start_index": 0,
    }

    update = await middleware.aafter_agent(
      state,
      Runtime(context=None),
    )

    self.assertEqual(len(evaluator.calls), 1)
    self.assertEqual(
      update,
      {
        "goal_status": "exhausted",
        "goal_reason": "Still incomplete.",
      },
    )
