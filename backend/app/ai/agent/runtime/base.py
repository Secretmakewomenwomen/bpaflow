from __future__ import annotations

from typing import Protocol

from app.ai.agent.state.models import AgentSessionState


class AgentRuntime(Protocol):
    """Minimal runtime contract for agent execution."""

    def run(self, *, session_state: AgentSessionState, stream: bool = False) -> AgentSessionState:
        """Run the agent logic for the provided session state."""
        ...
