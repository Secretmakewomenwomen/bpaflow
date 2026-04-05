from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Intent(str, Enum):
    general_chat = "general_chat"
    rag_retrieval = "rag_retrieval"
    generate_flow_from_file = "generate_flow_from_file"


class AssistantSnippet(BaseModel):
    upload_id: int
    file_name: str
    text: str
    page_start: int | None = None
    page_end: int | None = None
    small_chunk_index: int
    score: float

    @field_validator("small_chunk_index")
    def non_negative_chunk(cls, value: int) -> int:
        if value < 0:
            raise ValueError("small_chunk_index must be >= 0")
        return value

    @field_validator("score")
    def score_in_range(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("score must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def validate_page_range(cls, values: "AssistantSnippet") -> "AssistantSnippet":
        start = values.page_start
        end = values.page_end
        if start is not None and end is not None and start > end:
            raise ValueError("page_start must be <= page_end")
        return values


class RelatedFile(BaseModel):
    upload_id: int
    file_name: str
    mime_type: str
    created_at: datetime
    download_url: str


class AssistantReferenceType(str, Enum):
    snippet = "snippet"
    file = "file"


class AssistantReference(BaseModel):
    reference_type: AssistantReferenceType
    upload_id: int | None = None
    file_name: str
    snippet_text: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    score: float | None = None
    download_url: str | None = None


class AssistantToolTrace(BaseModel):
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["success", "error"]


class AssistantReasoningStep(BaseModel):
    step_type: Literal["thought", "action", "observation"]
    content: str
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    status: Literal["success", "error"] | None = None


class AssistantMessageStatus(str, Enum):
    completed = "completed"
    waiting_input = "waiting_input"
    processing = "processing"
    failed = "failed"


class AssistantPendingActionCandidate(BaseModel):
    upload_id: int
    file_name: str


class AssistantSelectFilePayload(BaseModel):
    selection_mode: Literal["single"]
    candidates: list[AssistantPendingActionCandidate] = Field(default_factory=list)


class AssistantPendingAction(BaseModel):
    action_id: str
    action_type: Literal["select_file"]
    payload: AssistantSelectFilePayload


class AssistantArtifact(BaseModel):
    artifact_type: str
    graph_payload: dict[str, Any] | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AssistantActionButton(BaseModel):
    action_id: str
    label: str
    action_type: str


class AssistantResponse(BaseModel):
    intent: Intent | None = None
    status: AssistantMessageStatus = AssistantMessageStatus.completed
    message: str | None = None
    answer: str
    reasoning_trace: list[AssistantReasoningStep] = Field(default_factory=list)
    pending_action: AssistantPendingAction | None = None
    artifact: AssistantArtifact | None = None
    actions: list[AssistantActionButton] = Field(default_factory=list)
    references: list[AssistantReference] = Field(default_factory=list)
    tool_trace: list[AssistantToolTrace] = Field(default_factory=list)
    snippets: list[AssistantSnippet] = Field(default_factory=list)
    related_files: list[RelatedFile] = Field(default_factory=list)

    @model_validator(mode="after")
    def migrate_legacy_references(cls, values: "AssistantResponse") -> "AssistantResponse":
        references: list[AssistantReference] = list(values.references)
        seen = {
            (
                reference.reference_type,
                reference.upload_id,
                reference.file_name,
                reference.snippet_text,
                reference.page_start,
                reference.page_end,
                reference.score,
                reference.download_url,
            )
            for reference in references
        }
        for snippet in values.snippets:
            key = (
                AssistantReferenceType.snippet,
                snippet.upload_id,
                snippet.file_name,
                snippet.text,
                snippet.page_start,
                snippet.page_end,
                snippet.score,
                None,
            )
            if key in seen:
                continue
            seen.add(key)
            references.append(
                AssistantReference(
                    reference_type=AssistantReferenceType.snippet,
                    upload_id=snippet.upload_id,
                    file_name=snippet.file_name,
                    snippet_text=snippet.text,
                    page_start=snippet.page_start,
                    page_end=snippet.page_end,
                    score=snippet.score,
                )
            )
        for related_file in values.related_files:
            key = (
                AssistantReferenceType.file,
                related_file.upload_id,
                related_file.file_name,
                None,
                None,
                None,
                None,
                related_file.download_url,
            )
            if key in seen:
                continue
            seen.add(key)
            references.append(
                AssistantReference(
                    reference_type=AssistantReferenceType.file,
                    upload_id=related_file.upload_id,
                    file_name=related_file.file_name,
                    download_url=related_file.download_url,
                )
            )
        values.references = references
        return values


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"


class MessageReferenceType(str, Enum):
    snippet = "snippet"
    file = "file"


class ConversationCreateResponse(BaseModel):
    conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime


class ConversationMessageReferenceResponse(BaseModel):
    reference_type: MessageReferenceType
    upload_id: int | None = None
    file_name: str
    snippet_text: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    score: float | None = None
    download_url: str | None = None


class ConversationMessageResponse(BaseModel):
    message_id: str
    role: MessageRole
    intent: Intent | None = None
    content: str
    status: AssistantMessageStatus
    reasoning_trace: list[AssistantReasoningStep] = Field(default_factory=list)
    tool_trace: list[AssistantToolTrace] = Field(default_factory=list)
    pending_action: AssistantPendingAction | None = None
    artifact: AssistantArtifact | None = None
    actions: list[AssistantActionButton] = Field(default_factory=list)
    created_at: datetime
    references: list[ConversationMessageReferenceResponse] = Field(default_factory=list)


class SendConversationMessageRequest(BaseModel):
    query: str = Field(min_length=1)


class ResumeConversationMessagePayload(BaseModel):
    uploadId: int = Field(gt=0)


class ResumeConversationMessageRequest(BaseModel):
    actionId: str = Field(min_length=1)
    decision: Literal["confirm"]
    payload: ResumeConversationMessagePayload

    @field_validator("actionId")
    def validate_action_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("actionId must not be blank")
        return normalized
