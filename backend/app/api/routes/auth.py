from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db, get_tenant_id
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.auth import AuthResponse, CurrentUserResponse, LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


def build_auth_response(user: User, settings: Settings, tenant_id: str) -> AuthResponse:
    return AuthResponse(
        access_token=create_access_token(
            user_id=user.user_id,
            username=user.username,
            settings=settings,
            tenant_id=tenant_id,
        ),
        user=CurrentUserResponse(
            user_id=user.user_id,
            username=user.username,
            tenant_id=tenant_id,
        ),
    )


@router.post("/register", response_model=AuthResponse)
def register(
    payload: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    existing_user = db.scalar(select(User).where(User.username == payload.username))
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在。",
        )

    user = User(
        user_id=str(uuid4()),
        username=payload.username,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return build_auth_response(user, settings, tenant_id)


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误。",
        )
    return build_auth_response(user, settings, tenant_id)


@router.get("/me", response_model=CurrentUserResponse)
def get_me(
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> CurrentUserResponse:
    return current_user
