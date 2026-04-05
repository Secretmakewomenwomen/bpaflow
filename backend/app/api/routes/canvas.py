from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.schemas.auth import CurrentUserResponse
from app.schemas.canvas import (
    CanvasNodeCreateRequest,
    CanvasNodeResponse,
    CanvasResponse,
    CanvasSaveRequest,
)
from app.services.canvas_service import CanvasService

router = APIRouter(prefix="/canvas", tags=["canvas"])


def get_canvas_service(db=Depends(get_db)) -> CanvasService:
    return CanvasService(db=db)


@router.post("", response_model=CanvasResponse)
def save_canvas(
    node_id: Annotated[str, Query(alias="nodeId", min_length=1)],
    payload: CanvasSaveRequest,
    service: Annotated[CanvasService, Depends(get_canvas_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> CanvasResponse:
    return service.save_canvas(
        user_id=current_user.user_id,
        node_id=node_id,
        name=payload.name,
        xml_content=payload.xmlContent,
        node_info=payload.nodeInfo,
    )


@router.get("", response_model=CanvasResponse)
def get_canvas(
    node_id: Annotated[str, Query(alias="nodeId", min_length=1)],
    service: Annotated[CanvasService, Depends(get_canvas_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> CanvasResponse:
    return service.get_canvas(user_id=current_user.user_id, node_id=node_id)


@router.get("/nodes", response_model=list[CanvasNodeResponse])
def list_canvas_nodes(
    service: Annotated[CanvasService, Depends(get_canvas_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> list[CanvasNodeResponse]:
    return service.list_tree_nodes(user_id=current_user.user_id)


@router.post("/nodes", response_model=CanvasNodeResponse)
def create_canvas_node(
    payload: CanvasNodeCreateRequest,
    service: Annotated[CanvasService, Depends(get_canvas_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> CanvasNodeResponse:
    return service.create_node(
        user_id=current_user.user_id,
        name=payload.name,
        parent_id=payload.parentId,
    )
