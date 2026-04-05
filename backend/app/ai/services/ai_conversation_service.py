from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload
from fastapi import HTTPException, status
from pydantic import ValidationError

from app.models.ai import AiConversation, AiMessage, AiMessageReference
from app.schemas.ai import (
    AssistantReference,
    AssistantReferenceType,
    AssistantResponse,
    AssistantActionButton,
    AssistantArtifact,
    AssistantPendingAction,
    AssistantToolTrace,
    ConversationCreateResponse,
    ConversationMessageReferenceResponse,
    ConversationMessageResponse,
    AssistantMessageStatus,
    Intent,
    MessageReferenceType,
    MessageRole,
)


def build_assistant_message_content(response: AssistantResponse) -> str:
    if response.answer.strip():
        return response.answer.strip()

    if response.message and response.message.strip():
        return response.message.strip()

    return "已完成检索。"


def _iter_response_references(response: AssistantResponse) -> list[AssistantReference]:
    if response.references:
        return response.references
    return []


def map_reference(record: AiMessageReference) -> ConversationMessageReferenceResponse:
    return ConversationMessageReferenceResponse(
        reference_type=MessageReferenceType(record.reference_type),
        upload_id=record.upload_id,
        file_name=record.file_name,
        snippet_text=record.snippet_text,
        page_start=record.page_start,
        page_end=record.page_end,
        score=record.score,
        download_url=record.download_url,
    )


def _serialize_assistant_payload(response: AssistantResponse) -> str | None:
    payload: dict[str, object] = {}
    if response.tool_trace:
        payload["tool_trace"] = [trace.model_dump(mode="json") for trace in response.tool_trace]
    if response.pending_action is not None:
        payload["pending_action"] = response.pending_action.model_dump(mode="json")
    if response.artifact is not None:
        payload["artifact"] = response.artifact.model_dump(mode="json")
    if response.actions:
        payload["actions"] = [action.model_dump(mode="json") for action in response.actions]

    if not payload:
        return None
    return json.dumps(payload, ensure_ascii=False)


def _deserialize_assistant_payload(payload_json: str | None) -> dict[str, object]:
    if not payload_json:
        return {}
    try:
        loaded = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def map_message(record: AiMessage) -> ConversationMessageResponse:
    payload = _deserialize_assistant_payload(record.payload_json)
    pending_action_raw = payload.get("pending_action")
    artifact_raw = payload.get("artifact")
    actions_raw = payload.get("actions")
    tool_trace_raw = payload.get("tool_trace")
    pending_action = None
    artifact = None
    actions: list[AssistantActionButton] = []
    tool_trace = []

    if isinstance(pending_action_raw, dict):
        try:
            pending_action = AssistantPendingAction.model_validate(pending_action_raw)
        except ValidationError:
            pending_action = None
    if isinstance(artifact_raw, dict):
        try:
            artifact = AssistantArtifact.model_validate(artifact_raw)
        except ValidationError:
            artifact = None
    if isinstance(actions_raw, list):
        try:
            actions = [AssistantActionButton.model_validate(item) for item in actions_raw]
        except ValidationError:
            actions = []
    if isinstance(tool_trace_raw, list):
        try:
            tool_trace = [AssistantToolTrace.model_validate(item) for item in tool_trace_raw]
        except ValidationError:
            tool_trace = []

    return ConversationMessageResponse(
        message_id=record.id,
        role=MessageRole(record.role),
        intent=Intent(record.intent) if record.intent else None,
        content=record.content,
        status=AssistantMessageStatus(record.status),
        pending_action=pending_action,
        artifact=artifact,
        actions=actions,
        tool_trace=tool_trace,
        created_at=record.created_at,
        references=[map_reference(item) for item in record.references],
    )


def map_conversation(record: AiConversation) -> ConversationCreateResponse:
    return ConversationCreateResponse(
        conversation_id=record.id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_message_at=record.last_message_at,
    )


class AiConversationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_conversation(self, *, user_id: str, title: str = "新对话") -> ConversationCreateResponse:
        conversation = AiConversation(user_id=user_id, title=title)
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return map_conversation(conversation)

    def get_latest_conversation(self, *, user_id: str) -> ConversationCreateResponse | None:
        conversation = self.db.scalar(
            select(AiConversation)
            .where(AiConversation.user_id == user_id)
            .order_by(desc(AiConversation.last_message_at), desc(AiConversation.created_at))
            .limit(1)
        )
        if conversation is None:
            return None
        return map_conversation(conversation)

    def get_messages(self, *, conversation_id: str, user_id: str) -> list[ConversationMessageResponse]:
        conversation = self._get_conversation_or_404(conversation_id=conversation_id, user_id=user_id)
        records = self.db.scalars(
            select(AiMessage)
            .options(selectinload(AiMessage.references))
            .where(AiMessage.conversation_id == conversation.id)
            .order_by(AiMessage.created_at.asc())
        ).all()

        return [map_message(record) for record in records]

    def get_recent_messages(
        self,
        *,
        conversation_id: str,
        user_id: str,
        limit: int = 6,
    ) -> list[ConversationMessageResponse]:
        conversation = self._get_conversation_or_404(conversation_id=conversation_id, user_id=user_id)
        records = self.db.scalars(
            select(AiMessage)
            .options(selectinload(AiMessage.references))
            .where(AiMessage.conversation_id == conversation.id)
            .order_by(desc(AiMessage.created_at))
            .limit(limit)
        ).all()
        return [map_message(record) for record in reversed(records)]



    def create_user_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        content: str,
    ) -> ConversationMessageResponse:
        conversation = self._get_conversation_or_404(conversation_id=conversation_id, user_id=user_id)
        message = AiMessage(
            conversation_id=conversation.id,
            role=MessageRole.user.value,
            content=content,
            status="completed",
        )
        self.db.add(message)
        conversation.last_message_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self.db.commit()
        self.db.refresh(message)
        return map_message(message)

    def create_assistant_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        response: AssistantResponse,
    ) -> ConversationMessageResponse:
        conversation = self._get_conversation_or_404(conversation_id=conversation_id, user_id=user_id)
        message = AiMessage(
            conversation_id=conversation.id,
            role=MessageRole.assistant.value,
            intent=response.intent.value if response.intent else None,
            content=build_assistant_message_content(response),
            status=response.status.value,
            payload_json=_serialize_assistant_payload(response),
        )
        self.db.add(message)
        self.db.flush()

        for reference in _iter_response_references(response):
            if reference.reference_type == AssistantReferenceType.snippet:
                self.db.add(
                    AiMessageReference(
                        message_id=message.id,
                        reference_type=MessageReferenceType.snippet.value,
                        upload_id=reference.upload_id,
                        file_name=reference.file_name,
                        snippet_text=reference.snippet_text,
                        page_start=reference.page_start,
                        page_end=reference.page_end,
                        score=reference.score,
                    )
                )
                continue
            self.db.add(
                AiMessageReference(
                    message_id=message.id,
                    reference_type=MessageReferenceType.file.value,
                    upload_id=reference.upload_id,
                    file_name=reference.file_name,
                    download_url=reference.download_url,
                )
            )

        conversation.last_message_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self.db.commit()
        refreshed = self.db.scalar(
            select(AiMessage)
            .options(selectinload(AiMessage.references))
            .where(AiMessage.id == message.id)
        )
        if refreshed is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="AI 消息保存失败。")
        mapped = map_message(refreshed)
        # reasoning_trace is runtime-only and intentionally not persisted in payload_json.
        if response.reasoning_trace:
            return mapped.model_copy(update={"reasoning_trace": list(response.reasoning_trace)})
        return mapped

    def _get_conversation_or_404(self, *, conversation_id: str, user_id: str) -> AiConversation:
        conversation = self.db.scalar(
            select(AiConversation).where(
                AiConversation.id == conversation_id,
                AiConversation.user_id == user_id,
            )
        )
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 会话不存在。")
        return conversation

    def deleteMessage(
        self,
        *,
        conversation_id: str,
        user_id: str,
    ) -> None:
        conversation = self._get_conversation_or_404(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        self.db.delete(conversation)
        self.db.commit()
