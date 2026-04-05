from datetime import datetime

from sqlalchemy import BIGINT, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UploadedFile(Base):
    __tablename__ = "uploaded_file"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_ext: Mapped[str] = mapped_column(String(32), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BIGINT, nullable=False)
    oss_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    oss_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    public_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="UPLOADED")
    vector_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    vector_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text_vector_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    text_vector_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    text_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_vector_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    image_vector_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    image_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    vectorized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
