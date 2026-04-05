from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.work import WorkerFile
from app.schemas.work import WorkResponse


def map_work_record(record: WorkerFile) -> WorkResponse:
    return WorkResponse(
        id=record.id,
        name=record.name,
        content=record.content,
        createdAt=record.created_at,
    )


class WorkService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save_work(self, name: str, content: str, work_id: int | None = None) -> WorkResponse:
        if work_id is None:
            record = WorkerFile(name=name, content=content)
            self.db.add(record)
        else:
            record = self.db.get(WorkerFile, work_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待办不存在。")
            record.name = name
            record.content = content

        self.db.commit()
        self.db.refresh(record)
        return map_work_record(record)

    def list_works(self) -> list[WorkResponse]:
        records = self.db.scalars(select(WorkerFile).order_by(desc(WorkerFile.id))).all()
        return [map_work_record(record) for record in records]

    def delete_work(self, work_id: int) -> None:
        record = self.db.get(WorkerFile, work_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待办不存在。")

        self.db.delete(record)
        self.db.commit()
