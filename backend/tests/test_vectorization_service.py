from datetime import datetime
from types import SimpleNamespace

from app.services.document_types import ParsedDocument, ParsedSegment, VectorChunk
from app.services.vectorization_service import VectorizationService


class FakeParsingService:
    def parse(self, filename: str, file_ext: str, mime_type: str, content: bytes) -> ParsedDocument:
        if file_ext == "pdf":
            assert content == b"raw-pdf"
            return ParsedDocument(
                segments=[
                    ParsedSegment(
                        text="raw-one",
                        page_start=1,
                        page_end=1,
                        source_type="pdf_text",
                    )
                ]
            )

        assert file_ext == "png"
        assert content == b"raw-png"
        return ParsedDocument(
            segments=[
                ParsedSegment(
                    text="ocr-one",
                    page_start=1,
                    page_end=1,
                    source_type="ocr",
                )
            ]
        )


class FakeCleaningService:
    def clean_segments(self, segments: list[ParsedSegment]) -> list[ParsedSegment]:
        if [segment.text for segment in segments] == ["raw-one"]:
            return [
                ParsedSegment(
                    text="clean-one",
                    page_start=1,
                    page_end=1,
                    source_type="pdf_text",
                ),
                ParsedSegment(
                    text="clean-two",
                    page_start=2,
                    page_end=2,
                    source_type="ocr",
                ),
            ]

        return [
            ParsedSegment(
                text="png-clean-one",
                page_start=1,
                page_end=1,
                source_type="ocr",
            )
        ]


class FakeChunkingService:
    def build_chunks(self, segments: list[ParsedSegment]) -> list[VectorChunk]:
        if [segment.text for segment in segments] == ["clean-one", "clean-two"]:
            return [
                VectorChunk(
                    small_chunk_text="clean-one",
                    large_chunk_text="大块一",
                    small_chunk_index=0,
                    large_chunk_id="large-0",
                    page_start=1,
                    page_end=1,
                    source_type="pdf_text",
                ),
                VectorChunk(
                    small_chunk_text="clean-two",
                    large_chunk_text="大块一",
                    small_chunk_index=1,
                    large_chunk_id="large-0",
                    page_start=2,
                    page_end=2,
                    source_type="ocr",
                ),
            ]

        return [
            VectorChunk(
                small_chunk_text="png-clean-one",
                large_chunk_text="图片大块一",
                small_chunk_index=0,
                large_chunk_id="png-large-0",
                page_start=1,
                page_end=1,
                source_type="ocr",
            )
        ]


class FakeEmbeddingService:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return [[0.1, 0.2] for _ in texts]


class FakeImageEmbeddingService:
    def __init__(self) -> None:
        self.calls = []

    def embed_image(self, *, image_url: str, prompt_text: str) -> list[float]:
        self.calls.append((image_url, prompt_text))
        return [0.3, 0.4]


class FakePgVectorService:
    def __init__(self) -> None:
        self.text_ensured = 0
        self.image_ensured = 0
        self.text_rows = []
        self.image_rows = []
        self.deleted_text_file_id = None
        self.deleted_image_file_id = None

    def ensure_text_collection(self) -> None:
        self.text_ensured += 1

    def ensure_image_collection(self) -> None:
        self.image_ensured += 1

    def replace_text_chunks(self, file_id: int, rows: list[dict]) -> None:
        self.deleted_text_file_id = file_id
        self.text_rows = rows

    def replace_image_vectors(self, file_id: int, rows: list[dict]) -> None:
        self.deleted_image_file_id = file_id
        self.image_rows = rows


class FakeDbSession:
    def __init__(self, record) -> None:
        self.record = record
        self.closed = False
        self.commit_count = 0

    def get(self, model, record_id: int):
        if record_id == self.record.id:
            return self.record
        return None

    def commit(self) -> None:
        self.commit_count += 1

    def close(self) -> None:
        self.closed = True


def build_service() -> tuple[VectorizationService, FakeEmbeddingService, FakeImageEmbeddingService, FakePgVectorService]:
    embedding_service = FakeEmbeddingService()
    image_embedding_service = FakeImageEmbeddingService()
    pgvector_service = FakePgVectorService()
    service = VectorizationService(
        settings=SimpleNamespace(),
        parsing_service=FakeParsingService(),
        cleaning_service=FakeCleaningService(),
        chunking_service=FakeChunkingService(),
        embedding_service=embedding_service,
        image_embedding_service=image_embedding_service,
        pgvector_service=pgvector_service,
    )
    return service, embedding_service, image_embedding_service, pgvector_service


def test_vectorization_service_embeds_pdf_into_text_table_only() -> None:
    service, embedding_service, image_embedding_service, pgvector_service = build_service()
    record = SimpleNamespace(
        id=9,
        file_name="diagram.pdf",
        file_ext="pdf",
        mime_type="application/pdf",
        public_url="https://example.com/diagram.pdf",
        created_at=datetime(2026, 3, 24, 12, 0, 0),
    )

    result = service.vectorize_record(record, b"raw-pdf")

    assert result.chunk_count == 2
    assert result.text_chunk_count == 2
    assert result.image_chunk_count == 0
    assert embedding_service.inputs == [["clean-one", "clean-two"]]
    assert image_embedding_service.calls == []
    assert pgvector_service.text_ensured == 1
    assert pgvector_service.image_ensured == 0
    assert pgvector_service.deleted_text_file_id == 9
    assert pgvector_service.text_rows[0]["file_id"] == 9
    assert pgvector_service.text_rows[0]["file_name"] == "diagram.pdf"
    assert pgvector_service.text_rows[0]["large_chunk_text"] == "大块一"
    assert pgvector_service.text_rows[1]["source_type"] == "ocr"


def test_vectorization_service_embeds_png_into_text_and_image_tables() -> None:
    service, embedding_service, image_embedding_service, pgvector_service = build_service()
    record = SimpleNamespace(
        id=10,
        file_name="diagram.png",
        file_ext="png",
        mime_type="image/png",
        public_url="https://example.com/diagram.png",
        created_at=datetime(2026, 3, 24, 12, 0, 0),
    )

    result = service.vectorize_record(record, b"raw-png")

    assert result.chunk_count == 2
    assert result.text_chunk_count == 1
    assert result.image_chunk_count == 1
    assert embedding_service.inputs == [["png-clean-one"]]
    assert image_embedding_service.calls[0][0].startswith("data:image/png;base64,")
    assert image_embedding_service.calls[0][1] == "architecture diagram"
    assert pgvector_service.text_ensured == 1
    assert pgvector_service.image_ensured == 1
    assert pgvector_service.deleted_text_file_id == 10
    assert pgvector_service.deleted_image_file_id == 10
    assert pgvector_service.text_rows[0]["small_chunk_text"] == "png-clean-one"
    assert pgvector_service.image_rows[0]["file_id"] == 10
    assert pgvector_service.image_rows[0]["source_type"] == "image"


def test_vectorization_service_default_session_factory_creates_and_closes_session(monkeypatch) -> None:
    record = SimpleNamespace(
        id=11,
        file_name="diagram.pdf",
        file_ext="pdf",
        mime_type="application/pdf",
        vector_status="PENDING",
        text_vector_status="PENDING",
        text_vector_error=None,
        image_vector_status=None,
        image_vector_error=None,
        vector_error=None,
        chunk_count=0,
        text_chunk_count=0,
        image_chunk_count=0,
        vectorized_at=None,
        created_at=datetime(2026, 3, 24, 12, 0, 0),
    )
    fake_db = FakeDbSession(record)
    session_local_calls = {"count": 0}

    def fake_get_session_local():
        session_local_calls["count"] += 1
        return lambda: fake_db

    monkeypatch.setattr("app.services.vectorization_service.get_session_local", fake_get_session_local)

    service = VectorizationService(
        settings=SimpleNamespace(
            small_chunk_size=700,
            small_chunk_overlap=120,
            large_chunk_size=2100,
        ),
        parsing_service=FakeParsingService(),
        cleaning_service=FakeCleaningService(),
        chunking_service=FakeChunkingService(),
        embedding_service=FakeEmbeddingService(),
        image_embedding_service=FakeImageEmbeddingService(),
        pgvector_service=FakePgVectorService(),
    )

    service.vectorize_uploaded_file(
        uploaded_file_id=11,
        filename="diagram.pdf",
        file_ext="pdf",
        mime_type="application/pdf",
        content=b"raw-pdf",
    )

    assert session_local_calls["count"] == 1
    assert fake_db.commit_count == 2
    assert fake_db.closed is True
    assert record.vector_status == "VECTORIZED"
