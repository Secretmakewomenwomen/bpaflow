from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WorkSaveRequest(BaseModel):
    id: str | None = None
    name: str
    content: str


class WorkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    content: str
    createdAt: datetime

class UserResponse(BaseModel):
      model_config = ConfigDict(from_attributes=True)
      user_id:str
      username:str

