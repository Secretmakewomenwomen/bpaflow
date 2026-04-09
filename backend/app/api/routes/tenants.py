from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_control_db
from app.schemas.tenant import TenantCreateRequest, TenantResponse
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/tenants", tags=["tenants"])


def get_tenant_service(
    db: Annotated[Session, Depends(get_control_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TenantService:
    return TenantService(db=db, settings=settings)


@router.get("", response_model=list[TenantResponse])
def list_tenants(
    service: Annotated[TenantService, Depends(get_tenant_service)],
) -> list[TenantResponse]:
    return service.list_tenants()


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: TenantCreateRequest,
    service: Annotated[TenantService, Depends(get_tenant_service)],
) -> TenantResponse:
    return service.create_tenant(payload)
