from datetime import datetime
from io import BytesIO

from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.routes.uploads import get_upload_service
from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.main import app
from app.schemas.auth import CurrentUserResponse
from app.schemas.upload import UploadResponse


class FakeUploadService:
    async def upload_file(self, file, background_tasks, user_id: str):
        assert user_id == "user-a"
        if file.filename == "blocked.exe":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type")
        if file.filename == "too-large.pdf":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File exceeds the maximum size")
        return UploadResponse(
            id=1,
            fileName=file.filename,
            fileExt=file.filename.split(".")[-1],
            mimeType=file.content_type or "application/octet-stream",
            fileSize=12,
            url="https://static.example.com/uploads/2026/03/24/test.pdf",
            vectorStatus="PENDING",
            createdAt=datetime(2026, 3, 24, 12, 0, 0),
        )

    def list_uploads(self, user_id: str):
        assert user_id == "user-a"
        return [
            UploadResponse(
                id=2,
                fileName="newest.pdf",
                fileExt="pdf",
                mimeType="application/pdf",
                fileSize=32,
                url="https://static.example.com/uploads/2026/03/24/newest.pdf",
                vectorStatus="VECTORIZED",
                createdAt=datetime(2026, 3, 24, 12, 1, 0),
            )
        ]

    def delete_file(self, upload_id: int, user_id: str) -> None:
        assert user_id == "user-a"
        if upload_id == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在。")


def create_client(authenticated: bool = True) -> TestClient:
    def override_db():
        yield None

    app.dependency_overrides = {
        get_db: override_db,
        get_upload_service: lambda: FakeUploadService(),
    }
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: CurrentUserResponse(
            user_id="user-a",
            username="alice",
        )
    return TestClient(app)


def test_post_uploads_returns_success() -> None:
    client = create_client()
    response = client.post(
        "/api/uploads",
        files={"file": ("diagram.pdf", BytesIO(b"pdf"), "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["fileName"] == "diagram.pdf"
    assert response.json()["vectorStatus"] == "PENDING"


def test_post_uploads_rejects_invalid_extension() -> None:
    client = create_client()
    response = client.post(
        "/api/uploads",
        files={"file": ("blocked.exe", BytesIO(b"exe"), "application/octet-stream")},
    )

    assert response.status_code == 400


def test_post_uploads_rejects_oversized_file() -> None:
    client = create_client()
    response = client.post(
        "/api/uploads",
        files={"file": ("too-large.pdf", BytesIO(b"pdf"), "application/pdf")},
    )

    assert response.status_code == 400


def test_get_uploads_returns_recent_files() -> None:
    client = create_client()
    response = client.get("/api/uploads")

    assert response.status_code == 200
    assert response.json()[0]["fileName"] == "newest.pdf"


def test_delete_uploads_returns_no_content() -> None:
    client = create_client()
    response = client.delete("/api/uploads/2")

    assert response.status_code == 204


def test_delete_uploads_returns_not_found_for_missing_record() -> None:
    client = create_client()
    response = client.delete("/api/uploads/404")

    assert response.status_code == 404


def test_upload_routes_require_authentication() -> None:
    client = create_client(authenticated=False)

    response = client.get("/api/uploads")

    assert response.status_code == 401
