from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CanvasSaveRequest(BaseModel):
    name: str
    xmlContent: str
    nodeInfo: dict[str, Any]


class CanvasNodeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parentId: str | None = None


class CanvasNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parentId: str | None
    name: str
    sortOrder: int
    createdAt: datetime
    updatedAt: datetime


class CanvasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nodeId: str
    exists: bool = True
    name: str
    xmlContent: str
    nodeInfo: dict[str, Any]
    createdAt: datetime
    updatedAt: datetime
