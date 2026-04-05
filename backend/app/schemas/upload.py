from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fileName: str
    fileExt: str
    mimeType: str
    fileSize: int
    url: str
    vectorStatus: str
    createdAt: datetime


class UploadListResponseItem(UploadResponse):
    pass
