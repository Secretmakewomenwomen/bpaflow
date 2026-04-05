from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.work import WorkerFile
from app.schemas.work import WorkResponse
from app.models.user import User
from app.schemas.work import UserResponse

def map_work_record(record: WorkerFile) -> WorkResponse:
    return WorkResponse(
        id=record.id,
        name=record.name,
        content=record.content,
        createdAt=record.created_at,
    )
def mapUser(record:User)->UserResponse:
        return UserResponse(user_id=record.user_id,username=record.username)


class WorkService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save_work(
        self,
        name: str,
        content: str,
        user_id: str,
        work_id: str | None = None,
    ) -> WorkResponse:
        if work_id is None:
            record = WorkerFile(name=name, content=content, user_id=user_id)
            self.db.add(record)
        else:
            record = self.db.scalar(
                select(WorkerFile).where(
                    WorkerFile.id == work_id,
                    WorkerFile.user_id == user_id,
                )
            )
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待办不存在。")
            record.name = name
            record.content = content

        self.db.commit()
        self.db.refresh(record)
        return map_work_record(record)

    def list_works(self, user_id: str) -> list[WorkResponse]:
        records = self.db.scalars(
            select(WorkerFile)
            .where(WorkerFile.user_id == user_id)
            .order_by(desc(WorkerFile.created_at))
        ).all()
        return [map_work_record(record) for record in records]

    def delete_work(self, work_id: str, user_id: str) -> None:
        record = self.db.scalar(
            select(WorkerFile).where(
                WorkerFile.id == work_id,
                WorkerFile.user_id == user_id,
            )
        )
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="待办不存在。")

        self.db.delete(record)
        self.db.commit()
    

    def queryUsers(self)->list[UserResponse]    :
        records =  self.db.scalars(select(User)).all()

        return [mapUser(record) for record in records]
