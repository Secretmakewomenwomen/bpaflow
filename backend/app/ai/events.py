from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class AgentEvent:
    event: str
    thread_id: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "threadId": self.thread_id,
            **self.data,
        }
        if self.created_at is not None:
            payload["createdAt"] = self.created_at.isoformat()
        return payload

    def to_sse(self) -> str:
        return f"event: {self.event}\ndata: {json.dumps(self.to_payload(), ensure_ascii=False, separators=(',', ':'))}\n\n"
