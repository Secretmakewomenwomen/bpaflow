from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentStartRequest(BaseModel):
    input: str = Field(min_length=1)
    fileIds: list[int] = Field(default_factory=list)


class AgentResumeRequest(BaseModel):
    actionId: str = Field(min_length=1)
    decision: Literal["approve", "reject", "confirm"]
    feedback: str | None = None


class AgentPendingActionResponse(BaseModel):
    actionId: str
    actionType: str
    payload: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime


class AgentRunResponse(BaseModel):
    threadId: str
    status: str
    currentStage: str
    intent: str | None = None
    pendingAction: AgentPendingActionResponse | None = None
