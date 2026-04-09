from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TenantCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    database_url: str | None = Field(default=None, min_length=10, max_length=2048)
    database_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=63,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )
    config: dict[str, Any] | None = None


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    name: str
    database_url: str
    config: dict[str, Any] | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime
