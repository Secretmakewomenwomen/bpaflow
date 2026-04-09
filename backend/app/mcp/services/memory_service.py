from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class MemoryRecord:
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryToolService:
    def __init__(self) -> None:
        self._storage: dict[str, list[MemoryRecord]] = {}

    def memory_read(self, *, session_id: str, limit: int = 20) -> dict[str, Any]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        records = self._storage.get(session_id, [])
        rows = records[-limit:]
        return {
            "session_id": session_id,
            "items": [
                {
                    "content": row.content,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
        }

    def memory_append(self, *, session_id: str, content: str) -> dict[str, Any]:
        normalized = content.strip()
        if not normalized:
            raise ValueError("content must not be empty")
        rows = self._storage.setdefault(session_id, [])
        row = MemoryRecord(content=normalized)
        rows.append(row)
        return {
            "session_id": session_id,
            "size": len(rows),
            "item": {
                "content": row.content,
                "created_at": row.created_at.isoformat(),
            },
        }

    def memory_summarize(self, *, session_id: str, max_items: int = 20) -> dict[str, Any]:
        if max_items <= 0:
            raise ValueError("max_items must be > 0")
        records = self._storage.get(session_id, [])
        contents = [record.content for record in records[-max_items:]]
        summary = " | ".join(contents)
        return {
            "session_id": session_id,
            "summary": summary,
            "count": len(contents),
        }

