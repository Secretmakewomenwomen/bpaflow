from datetime import datetime

from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.routes.work import get_work_service
from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.main import app
from app.schemas.auth import CurrentUserResponse
from app.schemas.work import WorkResponse


class FakeWorkService:
    def save_work(self, name: str, content: str, user_id: str, work_id: str | None = None) -> WorkResponse:
        assert user_id == "user-a"
        if work_id == "missing-id":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待办不存在。")
        return WorkResponse(
            id=work_id or "11111111-1111-1111-1111-111111111111",
            name=name,
            content=content,
            createdAt=datetime(2026, 3, 27, 12, 0, 0),
        )

    def list_works(self, user_id: str) -> list[WorkResponse]:
        assert user_id == "user-a"
        return [
            WorkResponse(
                id="22222222-2222-2222-2222-222222222222",
                name="todo-2",
                content="second",
                createdAt=datetime(2026, 3, 27, 12, 0, 0),
            )
        ]

    def delete_work(self, work_id: str, user_id: str) -> None:
        assert user_id == "user-a"
        if work_id == "missing-id":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待办不存在。")


def create_client(authenticated: bool = True) -> TestClient:
    def override_db():
        yield None

    app.dependency_overrides = {
        get_db: override_db,
        get_work_service: lambda: FakeWorkService(),
    }
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: CurrentUserResponse(
            user_id="user-a",
            username="alice",
        )
    return TestClient(app)


def test_post_work_creates_record_without_id() -> None:
    client = create_client()

    response = client.post("/api/work", json={"name": "todo-1", "content": "first"})

    assert response.status_code == 200
    assert response.json()["id"] == "11111111-1111-1111-1111-111111111111"
    assert response.json()["name"] == "todo-1"


def test_post_work_updates_record_with_id() -> None:
    client = create_client()

    response = client.post(
        "/api/work",
        json={"id": "33333333-3333-3333-3333-333333333333", "name": "todo-3", "content": "updated"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == "33333333-3333-3333-3333-333333333333"
    assert response.json()["content"] == "updated"


def test_get_work_returns_list() -> None:
    client = create_client()

    response = client.get("/api/work")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "todo-2"


def test_delete_work_returns_no_content() -> None:
    client = create_client()

    response = client.delete("/api/work/22222222-2222-2222-2222-222222222222")

    assert response.status_code == 204


def test_post_work_returns_not_found_when_updating_missing_record() -> None:
    client = create_client()

    response = client.post("/api/work", json={"id": "missing-id", "name": "todo", "content": "missing"})

    assert response.status_code == 404


def test_work_routes_require_authentication() -> None:
    client = create_client(authenticated=False)

    response = client.get("/api/work")

    assert response.status_code == 401
