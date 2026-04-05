from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import uuid4

from app.ai.agent.state.models import (
    AgentSessionState,
    AgentStepState,
    ToolCallRecord,
    ToolObservationRecord,
)


class AgentStateManager:
    def create_session(
        self,
        conversation_id: str,
        user_id: str,
        query: str,
        *,
        session_id: str | None = None,
    ) -> AgentSessionState:
        return AgentSessionState(
            session_id=session_id or str(uuid4()),
            conversation_id=conversation_id,
            user_id=user_id,
            goal=query,
            status="running",
        )

    def start_step(
        self,
        state: AgentSessionState,
        *,
        prompt_context: Dict[str, Any] | None = None,
    ) -> AgentStepState:
        step_index = state.step_count + 1
        step = AgentStepState(step_index=step_index, prompt_context=prompt_context or {})
        state.step_count = step_index
        state.steps.append(step)
        return step

    def finalize_step(self, state: AgentSessionState, step: AgentStepState) -> AgentSessionState:
        if not state.steps or state.steps[-1] is not step:
            raise ValueError("Finalizing a step that is not the current active step.")
        has_activity = bool(step.tool_calls or step.tool_results)
        state.consecutive_empty_steps = 0 if has_activity else state.consecutive_empty_steps + 1
        return state

    def record_tool_call(
        self,
        state: AgentSessionState,
        *,
        tool_name: str,
        arguments: Dict[str, Any] | None = None,
        call_id: str | None = None,
    ) -> AgentSessionState:
        active_step = self._get_active_step(state)
        call_id = call_id or str(uuid4())
        arguments = dict(arguments or {})
        record = ToolCallRecord(call_id=call_id, tool_name=tool_name, arguments=arguments)
        previous = state.last_tool_call
        state.tool_history.append(record)
        if previous and previous.tool_name == tool_name and previous.arguments == arguments:
            state.repeated_action_count += 1
        else:
            state.repeated_action_count = 0
        state.last_tool_call = record
        active_step.tool_calls.append(record)
        state.call_step_map[call_id] = active_step
        return state

    def record_tool_observation(
        self,
        state: AgentSessionState,
        *,
        call_id: str,
        observation: str,
        metadata: Dict[str, Any] | None = None,
    ) -> AgentSessionState:
        step = state.call_step_map.get(call_id)
        if step is None:
            raise ValueError("Attempted to record an observation for an unknown tool call.")
        record = ToolObservationRecord(call_id=call_id, observation=observation, metadata=dict(metadata or {}))
        state.observations.append(record)
        step.tool_results.append(record)
        return state

    def _get_active_step(self, state: AgentSessionState) -> AgentStepState:
        if not state.steps:
            raise RuntimeError("Tool operations require an active step. Call start_step() first.")
        return state.steps[-1]

    def set_pending_action(self, state: AgentSessionState, action: Dict[str, Any], *, status: str = "waiting_input") -> AgentSessionState:
        state.pending_action = dict(action)
        state.status = status
        return state

    def set_final_response(self, state: AgentSessionState, response: Dict[str, Any], *, status: str = "completed") -> AgentSessionState:
        state.final_response = dict(response)
        state.status = status
        return state
