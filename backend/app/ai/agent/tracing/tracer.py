from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.models import AiAgentTrace

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    # AiAgentTrace.created_at is stored in a naive DateTime column; keep UTC but drop tzinfo.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _coerce_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _json_dumps(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(_to_jsonable(value), ensure_ascii=False, default=str)


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        # naive datetime stays naive; aware datetime becomes UTC naive
        return _coerce_naive_utc(value).isoformat()
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json")
        except Exception:
            dumped = value.model_dump()
        return _to_jsonable(dumped)
    if isinstance(value, Mapping):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int)):
        return enum_value
    return value


class AgentTracer(Protocol):
    def record_reason(
        self,
        *,
        conversation_id: str,
        session_id: str,
        step_index: int,
        decision_type: str,
        status: str,
        reason_summary: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        created_at: datetime | None = None,
    ) -> None: ...

    def record_action(
        self,
        *,
        conversation_id: str,
        session_id: str,
        step_index: int,
        decision_type: str,
        tool_name: str,
        tool_args: Mapping[str, Any] | None,
        status: str,
        created_at: datetime | None = None,
    ) -> None: ...

    def record_observation(
        self,
        *,
        conversation_id: str,
        session_id: str,
        step_index: int,
        tool_name: str,
        tool_args: Mapping[str, Any] | None,
        observation: Any,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
        created_at: datetime | None = None,
    ) -> None: ...

    def record_termination(
        self,
        *,
        conversation_id: str,
        session_id: str,
        step_index: int,
        status: str,
        reason_summary: str,
        created_at: datetime | None = None,
    ) -> None: ...


class NoopAgentTracer:
    def record_reason(self, **_: Any) -> None:
        return None

    def record_action(self, **_: Any) -> None:
        return None

    def record_observation(self, **_: Any) -> None:
        return None

    def record_termination(self, **_: Any) -> None:
        return None


class SqlAlchemyAgentTracer:
    """Persist agent traces to the ai_agent_trace table."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record_reason(
        self,
        *,
        conversation_id: str,
        session_id: str,
        step_index: int,
        decision_type: str,
        status: str,
        reason_summary: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self._add_row(
            conversation_id=conversation_id,
            session_id=session_id,
            step_index=step_index,
            phase="reason",
            decision_type=decision_type,
            status=status,
            reason_summary=reason_summary,
            error_code=error_code,
            error_message=error_message,
            created_at=created_at,
        )

    def record_action(
        self,
        *,
        conversation_id: str,
        session_id: str,
        step_index: int,
        decision_type: str,
        tool_name: str,
        tool_args: Mapping[str, Any] | None,
        status: str,
        created_at: datetime | None = None,
    ) -> None:
        self._add_row(
            conversation_id=conversation_id,
            session_id=session_id,
            step_index=step_index,
            phase="action",
            decision_type=decision_type,
            tool_name=tool_name,
            tool_args_json=_json_dumps(dict(tool_args or {})),
            status=status,
            created_at=created_at,
        )

    def record_observation(
        self,
        *,
        conversation_id: str,
        session_id: str,
        step_index: int,
        tool_name: str,
        tool_args: Mapping[str, Any] | None,
        observation: Any,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self._add_row(
            conversation_id=conversation_id,
            session_id=session_id,
            step_index=step_index,
            phase="observation",
            decision_type="observation",
            tool_name=tool_name,
            tool_args_json=_json_dumps(dict(tool_args or {})),
            observation_json=_json_dumps(observation),
            status=status,
            error_code=error_code,
            error_message=error_message,
            created_at=created_at,
        )

    def record_termination(
        self,
        *,
        conversation_id: str,
        session_id: str,
        step_index: int,
        status: str,
        reason_summary: str,
        created_at: datetime | None = None,
    ) -> None:
        self._add_row(
            conversation_id=conversation_id,
            session_id=session_id,
            step_index=step_index,
            phase="termination",
            decision_type="termination",
            status=status,
            reason_summary=reason_summary,
            created_at=created_at,
        )

    def _add_row(
        self,
        *,
        conversation_id: str,
        session_id: str,
        step_index: int,
        phase: str,
        decision_type: str,
        status: str,
        tool_name: str | None = None,
        tool_args_json: str | None = None,
        observation_json: str | None = None,
        reason_summary: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        if not conversation_id:
            # Some call sites execute without a persisted conversation (e.g., unit tests).
            return
        try:
            # Tracing must not affect the caller's transaction; isolate via savepoint.
            with self.db.begin_nested():
                row = AiAgentTrace(
                    conversation_id=conversation_id,
                    session_id=session_id,
                    step_index=int(step_index),
                    phase=phase,
                    decision_type=decision_type,
                    tool_name=tool_name,
                    tool_args_json=tool_args_json,
                    observation_json=observation_json,
                    status=status,
                    reason_summary=reason_summary,
                    error_code=error_code,
                    error_message=error_message,
                    created_at=_coerce_naive_utc(created_at) if created_at is not None else _utc_now(),
                )
                self.db.add(row)
                self.db.flush()
        except Exception as exc:
            # Tracing must not break the agent execution path.
            logger.debug("Failed to persist agent trace row", exc_info=exc)
            return None
