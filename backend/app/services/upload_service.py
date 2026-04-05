from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import BackgroundTasks, HTTPException, UploadFile, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.upload import UploadedFile
from app.schemas.upload import UploadResponse
from app.services.oss_service import OssService
from app.services.vectorization_service import VectorizationService
from app.utils.file_validation import (
    FileValidationError,
    get_extension,
    validate_extension,
    validate_size,
)
from app.utils.object_key import build_object_key


def map_upload_record(record: UploadedFile) -> UploadResponse:
    # 统一在这里做接口字段映射，避免路由层和服务层重复拼响应结构。
    return UploadResponse(
        id=record.id,
        fileName=record.file_name,
        fileExt=record.file_ext,
        mimeType=record.mime_type,
        fileSize=record.file_size,
        url=record.public_url,
        vectorStatus=record.vector_status,
        createdAt=record.created_at,
    )


def map_upload_detail_record(record: UploadedFile) -> dict[str, object]:
    return {
        "id": record.id,
        "fileName": record.file_name,
        "fileExt": record.file_ext,
        "mimeType": record.mime_type,
        "fileSize": record.file_size,
        "url": record.public_url,
        "vectorStatus": record.vector_status,
        "vectorError": record.vector_error,
        "chunkCount": record.chunk_count,
        "textVectorStatus": record.text_vector_status,
        "textVectorError": record.text_vector_error,
        "textChunkCount": record.text_chunk_count,
        "imageVectorStatus": record.image_vector_status,
        "imageVectorError": record.image_vector_error,
        "imageChunkCount": record.image_chunk_count,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
        "vectorizedAt": record.vectorized_at,
    }


class UploadService:
    # 上传服务只负责上传主链路和异步任务调度，不直接处理向量化细节。
    def __init__(
        self,
        db: Session,
        settings: Settings,
        oss_service: OssService | None = None,
        vectorization_service: VectorizationService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.oss_service = oss_service or OssService(settings)
        self.vectorization_service = vectorization_service or VectorizationService(settings)

    # 上传初始状态按文件类型区分通道：文档只走文本通道，图片同时挂起文本和图片通道。
    def _build_initial_channel_state(self, extension: str) -> dict[str, str | int | None]:
        if extension == "png":
            return {
                "vector_status": "PENDING",
                "text_vector_status": "PENDING",
                "text_chunk_count": 0,
                "image_vector_status": "PENDING",
                "image_chunk_count": 0,
            }
        return {
            "vector_status": "PENDING",
            "text_vector_status": "PENDING",
            "text_chunk_count": 0,
            "image_vector_status": None,
            "image_chunk_count": 0,
        }

    # 上传接口遵循“先返回上传成功，再后台向量化”的原则，保证前端响应快且职责清晰。
    async def upload_file(
        self,
        file: UploadFile,
        background_tasks: BackgroundTasks,
        user_id: str,
    ) -> UploadResponse:
        filename = file.filename or ""
        try:
            validate_extension(filename, set(self.settings.allowed_extensions))
        except FileValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        contents = await file.read()
        size = len(contents)

        try:
            validate_size(size, self.settings.max_upload_size)
        except FileValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        extension = get_extension(filename)
        object_key = build_object_key(filename)
        temp_path = ""

        try:
            with NamedTemporaryFile(delete=False, suffix=f".{extension}") as temp_file:
                temp_file.write(contents)
                temp_path = temp_file.name

            upload_result = self.oss_service.upload_from_path(temp_path, object_key)
            initial_state = self._build_initial_channel_state(extension)

            record = UploadedFile(
                user_id=user_id,
                file_name=filename,
                file_ext=extension,
                mime_type=file.content_type or "application/octet-stream",
                file_size=size,
                oss_bucket=upload_result["bucket"],
                oss_key=upload_result["key"],
                public_url=upload_result["public_url"],
                status="UPLOADED",
                vector_status=initial_state["vector_status"],
                text_vector_status=initial_state["text_vector_status"],
                text_chunk_count=initial_state["text_chunk_count"],
                image_vector_status=initial_state["image_vector_status"],
                image_chunk_count=initial_state["image_chunk_count"],
            )

            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
            background_tasks.add_task(
                self.vectorization_service.vectorize_uploaded_file,
                record.id,
                filename,
                extension,
                file.content_type or "application/octet-stream",
                contents,
            )
            return map_upload_record(record)
        except HTTPException:
            raise
        except Exception as exc:
            if "upload_result" not in locals():
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="OSS upload failed",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to persist upload metadata",
            ) from exc
        finally:
            await file.close()
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)

    # 列表查询只返回最近上传记录，向量状态直接复用同一响应模型给前端展示。
    def list_uploads(
        self,
        user_id: str,
        *,
        limit: int | None = None,
        file_type: str | None = None,
    ) -> list[UploadResponse]:
        query_limit = self.settings.recent_upload_limit
        if limit is not None and limit > 0:
            query_limit = max(query_limit, limit)
        records = self.db.scalars(
            select(UploadedFile)
            .where(UploadedFile.user_id == user_id)
            .order_by(desc(UploadedFile.created_at))
            .limit(query_limit)
        ).all()
        filtered_records = [
            record for record in records
            if self._matches_file_type(record, file_type)
        ]
        if limit is not None and limit > 0:
            filtered_records = filtered_records[:limit]
        return [map_upload_record(record) for record in filtered_records]

    def get_file_detail(self, upload_id: int, *, user_id: str) -> dict[str, object]:
        record = self.db.scalar(
            select(UploadedFile).where(
                UploadedFile.id == upload_id,
                UploadedFile.user_id == user_id,
            )
        )
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在。")
        return map_upload_detail_record(record)

    # 删除走“向量库 -> OSS -> PostgreSQL”顺序，失败时保留数据库记录，便于用户重试。
    def delete_file(self, upload_id: int, user_id: str) -> None:
        record = self.db.scalar(
            select(UploadedFile).where(
                UploadedFile.id == upload_id,
                UploadedFile.user_id == user_id,
            )
        )
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在。")

        try:
            self.vectorization_service.delete_file_vectors(record.id)
            self.oss_service.delete_object(record.oss_key)
            self.db.delete(record)
            self.db.commit()
        except HTTPException:
            raise
        except Exception as exc:
            if hasattr(self.db, "rollback"):
                self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="删除文件失败。",
            ) from exc

    def get_download_url(self, upload_id: int, user_id: str) -> str:
        record = self.db.scalar(
            select(UploadedFile).where(
                UploadedFile.id == upload_id,
                UploadedFile.user_id == user_id,
            )
        )
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在。")
        return record.public_url

    def _matches_file_type(self, record: UploadedFile, file_type: str | None) -> bool:
        if not file_type:
            return True
        normalized_type = file_type.strip().lower()
        if normalized_type == "pdf":
            return record.file_ext.lower() == "pdf"
        if normalized_type == "image":
            return record.mime_type.startswith("image/")
        if normalized_type == "document":
            return not record.mime_type.startswith("image/")
        return True
