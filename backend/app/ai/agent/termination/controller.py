from __future__ import annotations

from dataclasses import dataclass

from app.ai.agent.reasoning.models import AgentDecision, DecisionType
from app.ai.agent.state.models import AgentSessionState


@dataclass(frozen=True)
class TerminationSignal:
    should_stop: bool
    status: str
    reason: str
    user_message: str | None = None


class TerminationController:
    def __init__(
        self,
        *,
        max_steps: int = 6,
        repeated_action_limit: int = 3,
        consecutive_empty_limit: int = 2,
    ):
        self.max_steps = max_steps
        self.repeated_action_limit = repeated_action_limit
        self.consecutive_empty_limit = consecutive_empty_limit

    def evaluate(
        self,
        state: AgentSessionState,
        *,
        last_decision: AgentDecision | None = None,
    ) -> TerminationSignal:
        if state.final_response is not None:
            return TerminationSignal(
                should_stop=True,
                status="completed",
                reason="Final response recorded.",
            )

        if state.status == "waiting_input":
            return TerminationSignal(
                should_stop=True,
                status="waiting_input",
                reason="Awaiting input from the user.",
            )

        if last_decision and last_decision.decision_type == DecisionType.final_answer:
            return TerminationSignal(
                should_stop=True,
                status="final_answer",
                reason="Model decided on a final answer.",
            )

        if state.step_count >= self.max_steps:
            return TerminationSignal(
                should_stop=True,
                status="max_steps",
                reason=f"Reached maximum number of steps ({state.step_count}/{self.max_steps}).",
            )

        if state.repeated_action_count >= self.repeated_action_limit:
            return TerminationSignal(
                should_stop=True,
                status="repeated_action",
                reason="Repeated tool invocations exceeded the configured limit.",
            )

        if state.consecutive_empty_steps >= self.consecutive_empty_limit:
            return TerminationSignal(
                should_stop=True,
                status="empty_steps",
                reason="Too many consecutive steps without tool activity.",
            )

        return TerminationSignal(
            should_stop=False,
            status="running",
            reason="Agent is permitted to continue.",
        )
