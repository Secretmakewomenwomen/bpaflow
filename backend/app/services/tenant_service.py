import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, status
from sqlalchemy import create_engine, desc, select, text
from sqlalchemy.orm import Session

from app.ai.services.langgraph_assistant import initialize_postgres_checkpointer_for_dsn
from app.core.config import Settings
from app.core.database import (
    create_tables,
    ensure_ai_agent_trace_schema,
    ensure_ai_message_schema,
    ensure_canvas_schema,
    ensure_pg_search_bm25_index,
    ensure_pg_search_extension,
    ensure_pg_search_ready,
    ensure_pgvector_extension,
    ensure_uploaded_file_schema,
    ensure_vector_store_schema,
    ensure_worker_file_schema,
    get_tenant_engine,
)
from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreateRequest, TenantResponse

_SIMPLE_PG_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _serialize_config(config: dict[str, Any] | None) -> str | None:
    if config is None:
        return None
    return json.dumps(config, ensure_ascii=False)


def _deserialize_config(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def map_tenant(tenant: Tenant) -> TenantResponse:
    return TenantResponse(
        tenant_id=tenant.tenant_id,
        name=tenant.name,
        database_url=tenant.database_url,
        config=_deserialize_config(tenant.config_json),
        enabled=tenant.enabled,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )


class TenantService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def list_tenants(self) -> list[TenantResponse]:
        records = self.db.scalars(
            select(Tenant).order_by(desc(Tenant.created_at))
        ).all()
        return [map_tenant(item) for item in records]

    def create_tenant(self, payload: TenantCreateRequest) -> TenantResponse:
        existing = self.db.scalar(
            select(Tenant).where(Tenant.tenant_id == payload.tenant_id)
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"租户已存在: {payload.tenant_id}",
            )

        database_url = self._resolve_tenant_database_url(payload)
        tenant = Tenant(
            tenant_id=payload.tenant_id,
            name=payload.name,
            database_url=database_url,
            config_json=_serialize_config(payload.config),
            enabled=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.db.add(tenant)
        self.db.commit()
        self.db.refresh(tenant)

        try:
            self._bootstrap_tenant_database(tenant)
        except Exception as exc:
            self.db.delete(tenant)
            self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"租户数据库初始化失败: {payload.tenant_id}，原因: {exc}",
            ) from exc

        return map_tenant(tenant)

    def _bootstrap_tenant_database(self, tenant: Tenant) -> None:
        tenant_engine = get_tenant_engine(tenant.tenant_id)
        ensure_pgvector_extension(tenant_engine)
        ensure_pg_search_extension(tenant_engine)
        ensure_uploaded_file_schema(tenant_engine)
        ensure_worker_file_schema(tenant_engine)
        create_tables(tenant_engine)
        ensure_ai_message_schema(tenant_engine)
        ensure_ai_agent_trace_schema(tenant_engine)
        ensure_canvas_schema(tenant_engine)
        ensure_vector_store_schema(tenant_engine)
        ensure_pg_search_bm25_index(tenant_engine)
        ensure_pg_search_ready(tenant_engine)
        initialize_postgres_checkpointer_for_dsn(tenant.database_url)

    def _resolve_tenant_database_url(self, payload: TenantCreateRequest) -> str:
        if payload.database_url:
            return payload.database_url.strip()

        if not self.settings.tenant_auto_create_database:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="当前环境未启用自动建库，请手动提供 database_url。",
            )

        admin_url = (self.settings.postgres_admin_url or self.settings.postgres_database_url).strip()
        if not admin_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="缺少 PostgreSQL 管理连接串，无法自动创建租户数据库。",
            )

        db_name = payload.database_name or self._build_database_name(payload.tenant_id)
        self._ensure_database_exists(admin_url=admin_url, database_name=db_name)
        return self._build_tenant_database_url(
            admin_url=admin_url,
            tenant_id=payload.tenant_id,
            database_name=db_name,
        )

    def _build_database_name(self, tenant_id: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_]+", "_", tenant_id.strip().lower())
        normalized = normalized.strip("_")
        prefix = self.settings.tenant_database_name_prefix.strip() or "tenant_"
        candidate = f"{prefix}{normalized}" if normalized else f"{prefix}default"
        candidate = candidate[:63]
        if not _SIMPLE_PG_IDENTIFIER_RE.fullmatch(candidate):
            candidate = re.sub(r"[^A-Za-z0-9_]+", "_", candidate)
            if not candidate or not (candidate[0].isalpha() or candidate[0] == "_"):
                candidate = f"tenant_{candidate}"
            candidate = candidate[:63]
        if not _SIMPLE_PG_IDENTIFIER_RE.fullmatch(candidate):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="根据租户 ID 生成数据库名失败，请显式传 database_name。",
            )
        return candidate

    def _build_tenant_database_url(self, *, admin_url: str, tenant_id: str, database_name: str) -> str:
        template = self.settings.tenant_database_url_template
        if template:
            try:
                return template.format(tenant_id=tenant_id, db_name=database_name)
            except KeyError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="TENANT_DATABASE_URL_TEMPLATE 模板变量错误，仅支持 {tenant_id}/{db_name}。",
                ) from exc

        parsed = urlsplit(admin_url)
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                f"/{database_name}",
                parsed.query,
                parsed.fragment,
            )
        )

    def _normalize_sqlalchemy_url(self, database_url: str) -> str:
        if database_url.startswith("postgresql://"):
            return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return database_url

    def _ensure_database_exists(self, *, admin_url: str, database_name: str) -> None:
        if not _SIMPLE_PG_IDENTIFIER_RE.fullmatch(database_name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"database_name 不合法: {database_name}",
            )

        admin_engine = create_engine(
            self._normalize_sqlalchemy_url(admin_url),
            pool_pre_ping=True,
            isolation_level="AUTOCOMMIT",
        )
        try:
            with admin_engine.connect() as connection:
                exists = connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :db_name"),
                    {"db_name": database_name},
                ).scalar()
                if exists:
                    return
                connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"自动创建租户数据库失败: {database_name}",
            ) from exc
        finally:
            admin_engine.dispose()
