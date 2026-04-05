from __future__ import annotations

from typing import Any

from app.ai.agent.tools import ToolCall, ToolDispatcher


class ToolExecutor:

    def __init__(
        self,
        *,
        work_service: Any | None = None,
        upload_service: Any | None = None,
        ai_rag_service: Any | None = None,
        current_user_id: str | None = None,
    ) -> None:
        self._dispatcher = ToolDispatcher(
            work_service=work_service,
            upload_service=upload_service,
            ai_rag_service=ai_rag_service,
            current_user_id=current_user_id,
        )

    def execute(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        call = ToolCall(tool_name=tool_name, arguments=kwargs)
        result = self._dispatcher.execute(call)
        return result.to_legacy_dict()
