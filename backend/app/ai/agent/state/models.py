from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ToolCallRecord:
    call_id: str
    tool_name: str
    arguments: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)


@dataclass
class ToolObservationRecord:
    call_id: str
    observation: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=_utc_now)


@dataclass
class AgentStepState:
    step_index: int
    prompt_context: Dict[str, Any] = field(default_factory=dict)
    decision: Optional[Dict[str, Any]] = None
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    tool_results: List[ToolObservationRecord] = field(default_factory=list)
    observation_summary: Optional[str] = None
    termination_signal: Optional[Dict[str, Any]] = None


@dataclass
class AgentSessionState:
    conversation_id: str
    user_id: str
    goal: str
    session_id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "running"
    step_count: int = 0
    consecutive_empty_steps: int = 0
    repeated_action_count: int = 0
    short_term_memory: List[str] = field(default_factory=list)
    long_term_memory_refs: List[str] = field(default_factory=list)
    pending_action: Optional[Dict[str, Any]] = None
    final_response: Optional[Dict[str, Any]] = None
    last_decision: Optional[Dict[str, Any]] = None
    steps: List[AgentStepState] = field(default_factory=list)
    tool_history: List[ToolCallRecord] = field(default_factory=list)
    observations: List[ToolObservationRecord] = field(default_factory=list)
    last_tool_call: Optional[ToolCallRecord] = field(default=None, repr=False, compare=False)
    call_step_map: Dict[str, AgentStepState] = field(default_factory=dict, repr=False, compare=False)
