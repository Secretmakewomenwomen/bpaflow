from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.schemas.auth import CurrentUserResponse
from app.schemas.flow import ChapterPhaseParseResponse
from app.schemas.upload import UploadResponse
from app.services.chapter_flow_service import ChapterFlowService
from app.services.upload_service import UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])


def get_upload_service(
    db=Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UploadService:
    return UploadService(db=db, settings=settings)


def get_chapter_flow_service(
    db=Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ChapterFlowService:
    return ChapterFlowService(db=db, settings=settings)


@router.post("", response_model=UploadResponse)
async def upload_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    service: Annotated[UploadService, Depends(get_upload_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> UploadResponse:
    return await service.upload_file(file, background_tasks, user_id=current_user.user_id)


@router.get("", response_model=list[UploadResponse])
def list_uploads(
    service: Annotated[UploadService, Depends(get_upload_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> list[UploadResponse]:
    return service.list_uploads(user_id=current_user.user_id)


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_upload(
    upload_id: int,
    service: Annotated[UploadService, Depends(get_upload_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> Response:
    service.delete_file(upload_id, user_id=current_user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{upload_id}/download")
def download_upload(
    upload_id: int,
    service: Annotated[UploadService, Depends(get_upload_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> RedirectResponse:
    url = service.get_download_url(upload_id, user_id=current_user.user_id)
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/{upload_id}/chapter-flow", response_model=ChapterPhaseParseResponse)
def get_upload_chapter_flow(
    upload_id: int,
    service: Annotated[ChapterFlowService, Depends(get_chapter_flow_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> ChapterPhaseParseResponse:
    return service.parse_upload(upload_id=upload_id, user_id=current_user.user_id)
