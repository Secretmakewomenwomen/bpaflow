from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.core.database import get_session_local
from app.models.upload import UploadedFile
from app.services.chunking_service import ChunkingService
from app.services.cleaning_service import TextCleaningService
from app.services.document_types import VectorizationResult
from app.services.embedding_service import EmbeddingService
from app.services.image_embedding_service import ImageEmbeddingService
from app.services.parsing_service import ParsingService
from app.services.pgvector_service import PgVectorService
from app.services.status_service import calculate_aggregate_vector_status


class VectorizationService:
    def __init__(
        self,
        settings: Settings,
        parsing_service: ParsingService | None = None,
        cleaning_service: TextCleaningService | None = None,
        chunking_service: ChunkingService | None = None,
        embedding_service: EmbeddingService | None = None,
        image_embedding_service: ImageEmbeddingService | None = None,
        pgvector_service: PgVectorService | None = None,
        session_factory: Any = None,
    ) -> None:
        self.settings = settings
        self.parsing_service = parsing_service or ParsingService(settings)
        self.cleaning_service = cleaning_service or TextCleaningService()
        self.chunking_service = chunking_service or ChunkingService(
            small_chunk_size=settings.small_chunk_size,
            small_chunk_overlap=settings.small_chunk_overlap,
            large_chunk_size=settings.large_chunk_size,
        )
        self.embedding_service = embedding_service or EmbeddingService(settings)
        self.image_embedding_service = image_embedding_service or ImageEmbeddingService(settings)
        self.pgvector_service = pgvector_service or PgVectorService(settings)
        self.session_factory = session_factory or (lambda: get_session_local()())

    def vectorize_uploaded_file(
        self,
        uploaded_file_id: int,
        filename: str,
        file_ext: str,
        mime_type: str,
        content: bytes,
    ) -> None:
        db = self.session_factory()
        record: UploadedFile | None = None
        try:
            record = db.get(UploadedFile, uploaded_file_id)
            if record is None:
                return
            record.file_name = filename
            record.file_ext = file_ext
            record.mime_type = mime_type
            record.vector_status = "PROCESSING"
            record.text_vector_status = "PROCESSING"
            record.text_vector_error = None
            record.image_vector_error = None
            if file_ext.lower().lstrip(".") == "png":
                record.image_vector_status = "PROCESSING"
            db.commit()

            result = self.vectorize_record(record, content)
            record.chunk_count = result.chunk_count
            record.text_chunk_count = result.text_chunk_count
            record.image_chunk_count = result.image_chunk_count
            record.text_vector_status = "VECTORIZED"
            record.text_vector_error = None
            if file_ext.lower().lstrip(".") == "png":
                record.image_vector_status = "VECTORIZED"
                record.image_vector_error = None
            record.vector_status, record.vector_error = calculate_aggregate_vector_status(
                file_ext=file_ext,
                text_status=record.text_vector_status,
                text_error=record.text_vector_error,
                image_status=record.image_vector_status,
                image_error=record.image_vector_error,
            )
            if record.vector_status == "VECTORIZED":
                record.vectorized_at = datetime.now(UTC)
            db.commit()
        except Exception as exc:
            if record is not None:
                extension = file_ext.lower().lstrip(".")
                error = self._truncate_error(str(exc))
                record.text_vector_status = "FAILED"
                record.text_vector_error = error
                if extension == "png":
                    record.image_vector_status = "FAILED"
                    record.image_vector_error = error
                record.vector_status, record.vector_error = calculate_aggregate_vector_status(
                    file_ext=file_ext,
                    text_status=record.text_vector_status,
                    text_error=record.text_vector_error,
                    image_status=record.image_vector_status,
                    image_error=record.image_vector_error,
                )
                db.commit()
        finally:
            db.close()

    def vectorize_record(self, record: UploadedFile | Any, content: bytes) -> VectorizationResult:
        text_result = self._vectorize_text_channel(record, content)
        image_count = 0
        if record.file_ext.lower().lstrip(".") == "png":
            image_count = self._vectorize_image_channel(record, content)

        return VectorizationResult(
            chunk_count=text_result.chunk_count + image_count,
            text_chunk_count=text_result.chunk_count,
            image_chunk_count=image_count,
        )

    def _vectorize_text_channel(self, record: UploadedFile | Any, content: bytes) -> VectorizationResult:
        parsed_document = self.parsing_service.parse(
            record.file_name,
            record.file_ext,
            record.mime_type,
            content,
        )
        cleaned_segments = self.cleaning_service.clean_segments(parsed_document.segments)
        chunks = self.chunking_service.build_chunks(cleaned_segments)
        if not chunks:
            raise ValueError("No text content extracted for vectorization")

        embeddings = self.embedding_service.embed_texts(
            [chunk.small_chunk_text for chunk in chunks]
        )
        if len(embeddings) != len(chunks):
            raise ValueError("Embedding count does not match chunk count")

        rows = []
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            rows.append(
                {
                    "id": f"{record.id}:{chunk.small_chunk_index}",
                    "file_id": record.id,
                    "file_name": record.file_name,
                    "file_ext": record.file_ext,
                    "mime_type": record.mime_type,
                    "page_start": chunk.page_start or 0,
                    "page_end": chunk.page_end or 0,
                    "small_chunk_index": chunk.small_chunk_index,
                    "large_chunk_id": chunk.large_chunk_id,
                    "small_chunk_text": chunk.small_chunk_text,
                    "large_chunk_text": chunk.large_chunk_text,
                    "source_type": chunk.source_type,
                    "created_at": getattr(
                        record,
                        "created_at",
                        datetime.now(UTC),
                    ).isoformat(),
                    "embedding": embedding,
                }
            )

        self.pgvector_service.ensure_text_collection()
        self.pgvector_service.replace_text_chunks(record.id, rows)
        return VectorizationResult(chunk_count=len(chunks))

    def _vectorize_image_channel(self, record: UploadedFile | Any, content: bytes) -> int:
        image_vector = self.image_embedding_service.embed_image(
            image_url=self._build_data_url(record.mime_type, content),
            prompt_text="architecture diagram",
        )
        rows = [
            {
                "id": f"{record.id}:image:0",
                "file_id": record.id,
                "file_name": record.file_name,
                "file_ext": record.file_ext,
                "mime_type": record.mime_type,
                "image_index": 0,
                "source_type": "image",
                "created_at": getattr(
                    record,
                    "created_at",
                    datetime.now(UTC),
                ).isoformat(),
                "embedding": image_vector,
            }
        ]
        self.pgvector_service.ensure_image_collection()
        self.pgvector_service.replace_image_vectors(record.id, rows)
        return 1

    def _build_data_url(self, mime_type: str, content: bytes) -> str:
        encoded = base64.b64encode(content).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def delete_file_vectors(self, uploaded_file_id: int) -> None:
        self.pgvector_service.delete_file_vectors(uploaded_file_id)

    def _truncate_error(self, message: str) -> str:
        return message[:1024]
