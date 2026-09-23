"""从执行日志锁定根 checkpoint，并展开其中的全部待响应 Interrupt。"""

from collections.abc import Mapping
from typing import Any

from shikigen.core.execution import ExecutionPause


class GraphPauseCollector:
  def __init__(self, thread_id: str):
    self.thread_id = thread_id
    self.checkpoint: dict | None = None

  def coordinate(self, config: Any) -> dict:
    values = config.get("configurable", {}) if isinstance(config, Mapping) else {}
    if (
      values.get("thread_id") != self.thread_id
      or not isinstance(values.get("checkpoint_ns"), str)
      or not isinstance(values.get("checkpoint_id"), str)
      or not values["checkpoint_id"]
    ):
      raise ValueError("Incomplete or foreign checkpoint coordinate")
    return {
      "configurable": {
        key: values[key] for key in ("thread_id", "checkpoint_ns", "checkpoint_id")
      }
    }

  def observe(self, event: object) -> None:
    if not isinstance(event, Mapping) or event.get("method") != "checkpoints":
      return
    params = event["params"]
    if params["namespace"] == []:
      coordinate = self.coordinate(params["data"]["config"])
      # todo. 当前只有主agent支持中断？？？后续看看
      if coordinate["configurable"]["checkpoint_ns"]:
        raise ValueError("Root checkpoint must have an empty namespace")
      self.checkpoint = coordinate

  async def read_pause(self, agent) -> ExecutionPause | None:
    if self.checkpoint is None:
      raise ValueError("Execution did not expose its root checkpoint")
    snapshot = await agent.aget_state(self.checkpoint, subgraphs=True)
    if self.coordinate(snapshot.config) != self.checkpoint:
      raise ValueError("Graph returned a different checkpoint")
    pending: dict[str, dict] = {}

    def collect(state) -> set[str]:
      namespace = self.coordinate(state.config)["configurable"]["checkpoint_ns"]
      found: set[str] = set()
      for task in state.tasks:
        nested = task.state
        if nested is not None:
          if isinstance(nested, Mapping):
            raise ValueError("Nested checkpoint was not expanded")
          nested_ids = collect(nested)
          if {item.id for item in task.interrupts} != nested_ids:
            raise ValueError("Nested Interrupts disagree with parent task")
          found.update(nested_ids)
        else:
          for item in task.interrupts:
            if not isinstance(item.id, str) or not item.id or item.id in pending:
              raise ValueError("Missing or duplicate Interrupt identity")
            pending[item.id] = {
              "id": item.id,
              "value": item.value,
              "namespace": namespace,
            }
            found.add(item.id)
      return found

    collect(snapshot)
    if pending:
      return ExecutionPause(self.checkpoint, tuple(pending.values()))
    if snapshot.next or snapshot.interrupts:
      raise ValueError("Paused checkpoint has no complete pending Interrupts")
    return None
