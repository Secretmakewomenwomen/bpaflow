from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.schemas.auth import CurrentUserResponse
from app.schemas.work import WorkResponse, WorkSaveRequest
from app.services.work_service import WorkService

router = APIRouter(prefix="/work", tags=["work"])


def get_work_service(db=Depends(get_db)) -> WorkService:
    return WorkService(db=db)


@router.post("", response_model=WorkResponse)
def save_work(
    payload: WorkSaveRequest,
    service: Annotated[WorkService, Depends(get_work_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> WorkResponse:
    return service.save_work(
        name=payload.name,
        content=payload.content,
        user_id=current_user.user_id,
        work_id=payload.id,
    )

@router.get("", response_model=list[WorkResponse])
def list_works(
    service: Annotated[WorkService, Depends(get_work_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> list[WorkResponse]:
    return service.list_works(user_id=current_user.user_id)


@router.delete("/{work_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_work(
    work_id: str,
    service: Annotated[WorkService, Depends(get_work_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> Response:
    service.delete_work(work_id, user_id=current_user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
