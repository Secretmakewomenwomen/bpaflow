from datetime import datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.services.work_service import WorkService


class FakeDbSession:
    def __init__(self) -> None:
        self.records = []
        self.committed = False
        self.deleted_records = []

    def add(self, record) -> None:
        self.records.append(record)

    def commit(self) -> None:
        self.committed = True

    def refresh(self, record) -> None:
        if getattr(record, "id", None) is None:
            record.id = str(uuid4())
        if getattr(record, "created_at", None) is None:
            record.created_at = datetime(2026, 3, 27, 12, 0, 0)

    def get(self, model, record_id: str):
        for record in self.records:
            if getattr(record, "id", None) == record_id:
                return record
        return None

    def scalar(self, statement):
        records = self.scalars(statement).all()
        return records[0] if records else None

    def delete(self, record) -> None:
        self.deleted_records.append(record)
        self.records = [item for item in self.records if item is not record]

    def scalars(self, statement):
        ordered = list(self.records)
        for criterion in getattr(statement, "_where_criteria", ()):
            field_name = criterion.left.name
            expected_value = criterion.right.value
            ordered = [record for record in ordered if getattr(record, field_name, None) == expected_value]
        ordered = sorted(ordered, key=lambda item: item.id, reverse=True)
        return SimpleNamespace(all=lambda: ordered)


def test_work_service_creates_record_when_id_is_missing() -> None:
    service = WorkService(db=FakeDbSession())

    result = service.save_work(name="todo-1", content="first task", work_id=None, user_id="user-a")

    assert isinstance(UUID(result.id), UUID)
    assert result.name == "todo-1"
    assert result.content == "first task"
    assert result.createdAt == datetime(2026, 3, 27, 12, 0, 0)
    assert service.db.records[0].user_id == "user-a"


def test_work_service_updates_record_when_id_exists() -> None:
    db = FakeDbSession()
    existing = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000003",
        user_id="user-a",
        name="old",
        content="old content",
        created_at=datetime(2026, 3, 26, 12, 0, 0),
    )
    db.records.append(existing)
    service = WorkService(db=db)

    result = service.save_work(name="new", content="new content", work_id=existing.id, user_id="user-a")

    assert result.id == existing.id
    assert existing.name == "new"
    assert existing.content == "new content"
    assert result.createdAt == datetime(2026, 3, 26, 12, 0, 0)


def test_work_service_lists_records_in_descending_id_order() -> None:
    db = FakeDbSession()
    db.records.extend(
        [
            SimpleNamespace(
                id="00000000-0000-0000-0000-000000000001",
                user_id="user-a",
                name="first",
                content="a",
                created_at=datetime(2026, 3, 25, 10, 0, 0),
            ),
            SimpleNamespace(
                id="00000000-0000-0000-0000-000000000002",
                user_id="user-b",
                name="second",
                content="b",
                created_at=datetime(2026, 3, 26, 10, 0, 0),
            ),
        ]
    )
    service = WorkService(db=db)

    result = service.list_works(user_id="user-a")

    assert [item.id for item in result] == ["00000000-0000-0000-0000-000000000001"]


def test_work_service_deletes_existing_record() -> None:
    db = FakeDbSession()
    record = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000004",
        user_id="user-a",
        name="todo",
        content="delete me",
        created_at=datetime(2026, 3, 26, 10, 0, 0),
    )
    db.records.append(record)
    service = WorkService(db=db)

    service.delete_work(record.id, user_id="user-a")

    assert db.deleted_records == [record]
    assert db.committed is True


def test_work_service_raises_not_found_for_missing_record() -> None:
    service = WorkService(db=FakeDbSession())

    try:
        service.delete_work("missing-id", user_id="user-a")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "待办不存在。"
    else:
        raise AssertionError("Expected delete_work to raise HTTPException")


def test_work_service_rejects_update_for_other_users_record() -> None:
    db = FakeDbSession()
    db.records.append(
        SimpleNamespace(
            id="00000000-0000-0000-0000-000000000009",
            user_id="user-b",
            name="old",
            content="old",
            created_at=datetime(2026, 3, 26, 12, 0, 0),
        )
    )
    service = WorkService(db=db)

    try:
        service.save_work(
            name="new",
            content="new",
            work_id="00000000-0000-0000-0000-000000000009",
            user_id="user-a",
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "待办不存在。"
    else:
        raise AssertionError("Expected save_work to reject cross-user update")
