import asyncio
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace

from fastapi import UploadFile
from fastapi import HTTPException

from app.services.upload_service import UploadService


class FakeOssService:
    def upload_from_path(self, file_path: str, object_key: str) -> dict[str, str]:
        return {
            "bucket": "demo-bucket",
            "key": object_key,
            "public_url": f"https://static.example.com/{object_key}",
        }

    def __init__(self) -> None:
        self.deleted_keys = []

    def delete_object(self, object_key: str) -> None:
        self.deleted_keys.append(object_key)


class FakeDbSession:
    def __init__(self) -> None:
        self.records = []
        self.committed = False
        self.deleted_records = []
        self.rollback_called = False

    def add(self, record) -> None:
        self.records.append(record)

    def commit(self) -> None:
        self.committed = True

    def refresh(self, record) -> None:
        record.id = 1
        record.created_at = datetime(2026, 3, 24, 12, 0, 0)

    def get(self, model, record_id: int):
        for record in self.records:
            if getattr(record, "id", None) == record_id:
                return record
        return None

    def delete(self, record) -> None:
        self.deleted_records.append(record)
        self.records = [item for item in self.records if item is not record]

    def rollback(self) -> None:
        self.rollback_called = True

    def scalar(self, statement):
        records = self._filter_records(statement)
        return records[0] if records else None

    def scalars(self, statement):
        records = self._filter_records(statement)
        return SimpleNamespace(all=lambda: records)

    def _filter_records(self, statement):
        records = list(self.records)
        for criterion in getattr(statement, "_where_criteria", ()):
            field_name = criterion.left.name
            expected_value = criterion.right.value
            records = [record for record in records if getattr(record, field_name, None) == expected_value]
        records = sorted(
            records,
            key=lambda item: getattr(item, "created_at", datetime.min),
            reverse=True,
        )
        limit_clause = getattr(statement, "_limit_clause", None)
        if limit_clause is not None:
            limit_value = getattr(limit_clause, "value", None)
            if isinstance(limit_value, int) and limit_value >= 0:
                records = records[:limit_value]
        return records


class FakeBackgroundTasks:
    def __init__(self) -> None:
        self.tasks = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.tasks.append((func, args, kwargs))


class FakeVectorizationService:
    def __init__(self) -> None:
        self.calls = []

    def vectorize_uploaded_file(
        self,
        uploaded_file_id: int,
        filename: str,
        file_ext: str,
        mime_type: str,
        content: bytes,
    ) -> None:
        self.calls.append(
            {
                "uploaded_file_id": uploaded_file_id,
                "filename": filename,
                "file_ext": file_ext,
                "mime_type": mime_type,
                "content": content,
            }
        )

    def delete_file_vectors(self, uploaded_file_id: int) -> None:
        self.calls.append({"delete_uploaded_file_id": uploaded_file_id})


def test_upload_service_uploads_and_maps_record() -> None:
    db = FakeDbSession()
    background_tasks = FakeBackgroundTasks()
    vectorization_service = FakeVectorizationService()
    settings = SimpleNamespace(
        allowed_extensions=("docx", "png", "pdf"),
        max_upload_size=10 * 1024 * 1024,
    )
    service = UploadService(
        db=db,
        settings=settings,
        oss_service=FakeOssService(),
        vectorization_service=vectorization_service,
    )
    upload = UploadFile(
        filename="diagram.pdf",
        file=BytesIO(b"architecture"),
        headers={"content-type": "application/pdf"},
    )

    result = asyncio.run(service.upload_file(upload, background_tasks, user_id="user-a"))

    assert result.id == 1
    assert result.fileName == "diagram.pdf"
    assert result.fileExt == "pdf"
    assert result.vectorStatus == "PENDING"
    assert result.url.startswith("https://static.example.com/uploads/")
    assert db.records[0].status == "UPLOADED"
    assert db.records[0].user_id == "user-a"
    assert db.records[0].vector_status == "PENDING"
    assert db.records[0].text_vector_status == "PENDING"
    assert db.records[0].text_chunk_count == 0
    assert db.records[0].image_vector_status is None
    assert db.records[0].image_chunk_count == 0
    assert db.records[0].oss_bucket == "demo-bucket"
    assert db.committed is True
    assert len(background_tasks.tasks) == 1
    scheduled_func, scheduled_args, _ = background_tasks.tasks[0]
    assert scheduled_func == vectorization_service.vectorize_uploaded_file
    assert scheduled_args[0] == 1
    assert scheduled_args[1] == "diagram.pdf"
    assert scheduled_args[2] == "pdf"
    assert scheduled_args[4] == b"architecture"


def test_upload_service_sets_png_channel_statuses() -> None:
    db = FakeDbSession()
    background_tasks = FakeBackgroundTasks()
    settings = SimpleNamespace(
        allowed_extensions=("docx", "png", "pdf"),
        max_upload_size=10 * 1024 * 1024,
    )
    service = UploadService(
        db=db,
        settings=settings,
        oss_service=FakeOssService(),
        vectorization_service=FakeVectorizationService(),
    )
    upload = UploadFile(
        filename="diagram.png",
        file=BytesIO(b"png-bits"),
        headers={"content-type": "image/png"},
    )

    result = asyncio.run(service.upload_file(upload, background_tasks, user_id="user-a"))

    assert result.vectorStatus == "PENDING"
    assert db.records[0].text_vector_status == "PENDING"
    assert db.records[0].image_vector_status == "PENDING"


def test_upload_service_lists_only_current_users_records() -> None:
    db = FakeDbSession()
    db.records.extend(
        [
            SimpleNamespace(
                id=1,
                user_id="user-a",
                file_name="mine.pdf",
                file_ext="pdf",
                mime_type="application/pdf",
                file_size=12,
                oss_bucket="demo-bucket",
                oss_key="uploads/demo/mine.pdf",
                public_url="https://static.example.com/uploads/demo/mine.pdf",
                status="UPLOADED",
                vector_status="PENDING",
                created_at=datetime(2026, 3, 24, 12, 0, 0),
            ),
            SimpleNamespace(
                id=2,
                user_id="user-b",
                file_name="others.pdf",
                file_ext="pdf",
                mime_type="application/pdf",
                file_size=12,
                oss_bucket="demo-bucket",
                oss_key="uploads/demo/others.pdf",
                public_url="https://static.example.com/uploads/demo/others.pdf",
                status="UPLOADED",
                vector_status="PENDING",
                created_at=datetime(2026, 3, 24, 12, 1, 0),
            ),
        ]
    )
    service = UploadService(
        db=db,
        settings=SimpleNamespace(
            allowed_extensions=("docx", "png", "pdf"),
            max_upload_size=10 * 1024 * 1024,
            recent_upload_limit=12,
        ),
        oss_service=FakeOssService(),
        vectorization_service=FakeVectorizationService(),
    )

    result = service.list_uploads(user_id="user-a")

    assert [item.fileName for item in result] == ["mine.pdf"]


def test_upload_service_expands_query_window_when_explicit_limit_is_provided() -> None:
    db = FakeDbSession()
    for index in range(6):
        db.records.append(
            SimpleNamespace(
                id=index + 1,
                user_id="user-a",
                file_name=f"mine-{index + 1}.pdf",
                file_ext="pdf",
                mime_type="application/pdf",
                file_size=12,
                oss_bucket="demo-bucket",
                oss_key=f"uploads/demo/mine-{index + 1}.pdf",
                public_url=f"https://static.example.com/uploads/demo/mine-{index + 1}.pdf",
                status="UPLOADED",
                vector_status="PENDING",
                created_at=datetime(2026, 3, 24, 12, index, 0),
            )
        )
    service = UploadService(
        db=db,
        settings=SimpleNamespace(
            allowed_extensions=("docx", "png", "pdf"),
            max_upload_size=10 * 1024 * 1024,
            recent_upload_limit=2,
        ),
        oss_service=FakeOssService(),
        vectorization_service=FakeVectorizationService(),
    )

    result = service.list_uploads(user_id="user-a", limit=5)

    assert [item.fileName for item in result] == [
        "mine-6.pdf",
        "mine-5.pdf",
        "mine-4.pdf",
        "mine-3.pdf",
        "mine-2.pdf",
    ]


def test_upload_service_returns_file_detail_for_current_user() -> None:
    db = FakeDbSession()
    db.records.append(
        SimpleNamespace(
            id=11,
            user_id="user-a",
            file_name="claim-guide.pdf",
            file_ext="pdf",
            mime_type="application/pdf",
            file_size=1024,
            oss_bucket="demo-bucket",
            oss_key="uploads/demo/claim-guide.pdf",
            public_url="https://static.example.com/uploads/demo/claim-guide.pdf",
            status="UPLOADED",
            vector_status="VECTORIZED",
            vector_error=None,
            chunk_count=9,
            text_vector_status="VECTORIZED",
            text_vector_error=None,
            text_chunk_count=9,
            image_vector_status=None,
            image_vector_error=None,
            image_chunk_count=0,
            created_at=datetime(2026, 3, 24, 12, 0, 0),
            updated_at=datetime(2026, 3, 24, 12, 3, 0),
            vectorized_at=datetime(2026, 3, 24, 12, 2, 0),
        )
    )
    service = UploadService(
        db=db,
        settings=SimpleNamespace(
            allowed_extensions=("docx", "png", "pdf"),
            max_upload_size=10 * 1024 * 1024,
            recent_upload_limit=12,
        ),
        oss_service=FakeOssService(),
        vectorization_service=FakeVectorizationService(),
    )

    result = service.get_file_detail(11, user_id="user-a")

    assert result["id"] == 11
    assert result["fileName"] == "claim-guide.pdf"
    assert result["vectorStatus"] == "VECTORIZED"
    assert result["textVectorStatus"] == "VECTORIZED"
    assert result["textChunkCount"] == 9
    assert result["vectorizedAt"] == datetime(2026, 3, 24, 12, 2, 0)


def test_upload_service_deletes_oss_vectors_and_database_record() -> None:
    db = FakeDbSession()
    record = SimpleNamespace(
        id=9,
        user_id="user-a",
        file_name="diagram.png",
        file_ext="png",
        mime_type="image/png",
        file_size=12,
        oss_bucket="demo-bucket",
        oss_key="uploads/demo/diagram.png",
        public_url="https://static.example.com/uploads/demo/diagram.png",
        status="UPLOADED",
        vector_status="VECTORIZED",
        created_at=datetime(2026, 3, 24, 12, 0, 0),
    )
    db.records.append(record)
    oss_service = FakeOssService()
    vectorization_service = FakeVectorizationService()
    service = UploadService(
        db=db,
        settings=SimpleNamespace(
            allowed_extensions=("docx", "png", "pdf"),
            max_upload_size=10 * 1024 * 1024,
        ),
        oss_service=oss_service,
        vectorization_service=vectorization_service,
    )

    service.delete_file(9, user_id="user-a")

    assert vectorization_service.calls == [{"delete_uploaded_file_id": 9}]
    assert oss_service.deleted_keys == ["uploads/demo/diagram.png"]
    assert db.deleted_records == [record]
    assert db.committed is True


def test_upload_service_rejects_delete_for_missing_record() -> None:
    service = UploadService(
        db=FakeDbSession(),
        settings=SimpleNamespace(
            allowed_extensions=("docx", "png", "pdf"),
            max_upload_size=10 * 1024 * 1024,
        ),
        oss_service=FakeOssService(),
        vectorization_service=FakeVectorizationService(),
    )

    try:
        service.delete_file(404, user_id="user-a")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "文件不存在。"
    else:
        raise AssertionError("Expected delete_file to raise HTTPException for missing record")


def test_upload_service_rejects_delete_for_other_users_record() -> None:
    db = FakeDbSession()
    db.records.append(
        SimpleNamespace(
            id=9,
            user_id="user-b",
            file_name="diagram.png",
            file_ext="png",
            mime_type="image/png",
            file_size=12,
            oss_bucket="demo-bucket",
            oss_key="uploads/demo/diagram.png",
            public_url="https://static.example.com/uploads/demo/diagram.png",
            status="UPLOADED",
            vector_status="VECTORIZED",
            created_at=datetime(2026, 3, 24, 12, 0, 0),
        )
    )
    service = UploadService(
        db=db,
        settings=SimpleNamespace(
            allowed_extensions=("docx", "png", "pdf"),
            max_upload_size=10 * 1024 * 1024,
            recent_upload_limit=12,
        ),
        oss_service=FakeOssService(),
        vectorization_service=FakeVectorizationService(),
    )

    try:
        service.delete_file(9, user_id="user-a")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "文件不存在。"
    else:
        raise AssertionError("Expected delete_file to reject cross-user delete")
