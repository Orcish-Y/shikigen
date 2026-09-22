"""应用的工具审批策略；通用 harness 不决定哪些工具需要人工许可。"""

from typing import Any

from langchain.agents.middleware import AgentState, HumanInTheLoopMiddleware
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
from shikigen.event_contract import ApprovalRequired, ApprovalSubmission
from shikigen.runtime_context import AgentRunContext

from app.run_state import ApprovalConflict, InvalidApprovalResponse, InvalidRunState

APPROVAL_POLICY: dict[str, bool | InterruptOnConfig] = {
  "write_file": {"allowed_decisions": ["approve", "reject"]},
  "bash": {"allowed_decisions": ["approve", "reject"]},
}


def build_approval_middleware(
  tool_names: list[str],
) -> HumanInTheLoopMiddleware[AgentState, AgentRunContext, Any]:
  missing = set(APPROVAL_POLICY) - set(tool_names)
  if missing:
    raise ValueError(
      f"Approval policy references missing tools: {', '.join(sorted(missing))}"
    )
  return HumanInTheLoopMiddleware[AgentState, AgentRunContext, Any](
    interrupt_on=APPROVAL_POLICY
  )


def validate_responses(
  required: ApprovalRequired, submission: ApprovalSubmission
) -> dict:
  """按 pending 中的动作顺序验证全部响应；目前只支持 approve/reject。"""
  if set(submission.responses) != {item.id for item in required.interrupts}:
    raise ApprovalConflict("Response keys must match all current Interrupt IDs")
  for item in required.interrupts:
    value = item.value
    if not isinstance(value, dict):
      raise InvalidRunState("Pending Interrupt is not an approval request")
    actions = value.get("action_requests")
    configs = value.get("review_configs")
    if not isinstance(actions, list) or not actions or not isinstance(configs, list):
      raise InvalidRunState("Pending approval has no action/review configuration")
    if len(configs) != len(actions):
      raise InvalidRunState("Each pending action requires a review configuration")
    decisions = submission.responses[item.id].decisions
    if len(decisions) != len(actions):
      raise InvalidApprovalResponse("Each action requires one ordered decision")
    for action, config, decision in zip(actions, configs, decisions, strict=True):
      if not isinstance(action, dict) or not isinstance(action.get("name"), str):
        raise InvalidRunState("Invalid pending action")
      if not isinstance(config, dict) or config.get("action_name") != action["name"]:
        raise InvalidRunState("Pending action has no matching review configuration")
      allowed_decisions = config.get("allowed_decisions")
      if not isinstance(allowed_decisions, list):
        raise InvalidRunState("Pending action has no matching review configuration")
      if decision.type not in allowed_decisions:
        raise InvalidApprovalResponse(f"Decision {decision.type} is not allowed")
  return submission.model_dump(mode="json", exclude_none=True)["responses"]
