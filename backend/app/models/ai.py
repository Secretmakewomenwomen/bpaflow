from datetime import datetime
from uuid import uuid4

from sqlalchemy import BIGINT, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AiConversation(Base):
    __tablename__ = "ai_conversation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新对话")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    messages = relationship(
        "AiMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AiMessage.created_at.asc()",
    )


class AiMessage(Base):
    __tablename__ = "ai_message"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ai_conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    conversation = relationship("AiConversation", back_populates="messages")
    references = relationship(
        "AiMessageReference",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="AiMessageReference.created_at.asc()",
    )


class AiMessageReference(Base):
    __tablename__ = "ai_message_reference"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ai_message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reference_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    upload_id: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    snippet_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_start: Mapped[int | None] = mapped_column(nullable=True)
    page_end: Mapped[int | None] = mapped_column(nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    download_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    message = relationship("AiMessage", back_populates="references")


class AiAgentTrace(Base):
    __tablename__ = "ai_agent_trace"
    __table_args__ = (
        Index("idx_ai_agent_trace_conversation_id", "conversation_id"),
        Index("idx_ai_agent_trace_session_id", "session_id"),
        Index("idx_ai_agent_trace_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    step_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    phase: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="reason",
        server_default=text("'reason'"),
    )
    decision_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="reason",
        server_default=text("'reason'"),
    )
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_args_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    observation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="running",
        server_default=text("'running'"),
    )
    reason_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
