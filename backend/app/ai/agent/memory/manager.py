from __future__ import annotations

from typing import Sequence

from app.ai.agent.state.models import AgentSessionState, ToolObservationRecord


class MemoryManager:
    def __init__(self, *, history_window: int = 5):
        self.history_window = history_window

    def recent_history(self, state: AgentSessionState, *, limit: int | None = None) -> list[str]:
        if limit is not None:
            if limit <= 0:
                return []
            window = limit
        else:
            window = self.history_window
        return state.short_term_memory[-window:]

    def observation_summaries(self, state: AgentSessionState, *, limit: int | None = None) -> list[str]:
        summaries = [step.observation_summary for step in state.steps if step.observation_summary]
        if limit is not None:
            if limit <= 0:
                return []
            summaries = summaries[-limit:]
        return summaries

    def extract_tool_result_summary(
        self,
        observation: ToolObservationRecord,
        *,
        max_length: int = 256,
    ) -> str:
        raw = observation.observation.strip()
        if not raw:
            return ""
        if len(raw) <= max_length:
            return raw
        truncated = raw[: max_length - 1].rstrip()
        return f"{truncated}..."

    def record_observation(
        self,
        state: AgentSessionState,
        *,
        observation_record: ToolObservationRecord,
        summary: str | None = None,
    ) -> str:
        summary_text = summary or self.extract_tool_result_summary(observation_record)
        step = state.call_step_map.get(observation_record.call_id)
        if step is None:
            raise ValueError(f"Observation call_id '{observation_record.call_id}' is not linked to a step.")
        step.observation_summary = summary_text
        state.short_term_memory.append(summary_text)
        while len(state.short_term_memory) > self.history_window:
            state.short_term_memory.pop(0)
        return summary_text

    def persist_long_term(self, state: AgentSessionState, *, summary: str) -> None:
        # Long-term memory is a no-op placeholder until a persistence layer is added.
        return None
