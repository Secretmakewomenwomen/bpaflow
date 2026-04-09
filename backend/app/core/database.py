import logging
import re
from collections.abc import Callable, Generator
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
_session_local = None
_tenant_engine_by_id: dict[str, Any] = {}
_tenant_session_local_by_id: dict[str, Any] = {}
_tenant_db_url_by_id: dict[str, str] = {}


def get_engine():
    global _engine
    if _engine is None:
        from app.core.config import get_settings

        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
        )
    return _engine


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def get_control_session_local():
    global _session_local
    if _session_local is None:
        _session_local = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            class_=Session,
        )
    return _session_local


def get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> str:
    from app.core.config import get_settings

    fallback_tenant_id = get_settings().default_tenant_id
    tenant_id = (x_tenant_id or fallback_tenant_id).strip()
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="租户标识不能为空。",
        )
    return tenant_id


def _load_tenant_database_url(tenant_id: str) -> str:
    from app.core.config import get_settings
    from app.models.tenant import Tenant

    settings = get_settings()
    if tenant_id == settings.default_tenant_id:
        return settings.postgres_database_url

    with get_control_session_local()() as control_db:
        tenant = control_db.scalar(
            select(Tenant).where(
                Tenant.tenant_id == tenant_id,
                Tenant.enabled.is_(True),
            )
        )

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"租户不存在或已停用: {tenant_id}",
        )

    return tenant.database_url


def get_tenant_engine(tenant_id: str):
    tenant_db_url = _normalize_database_url(_load_tenant_database_url(tenant_id))
    cached_url = _tenant_db_url_by_id.get(tenant_id)
    cached_engine = _tenant_engine_by_id.get(tenant_id)
    if cached_engine is not None and cached_url == tenant_db_url:
        return cached_engine

    tenant_engine = create_engine(
        tenant_db_url,
        pool_pre_ping=True,
    )
    _tenant_db_url_by_id[tenant_id] = tenant_db_url
    _tenant_engine_by_id[tenant_id] = tenant_engine
    _tenant_session_local_by_id[tenant_id] = sessionmaker(
        bind=tenant_engine,
        autoflush=False,
        autocommit=False,
        class_=Session,
    )
    return tenant_engine


def get_tenant_database_url(tenant_id: str) -> str:
    return _load_tenant_database_url(tenant_id)


def get_tenant_session_local(tenant_id: str):
    if tenant_id not in _tenant_session_local_by_id:
        get_tenant_engine(tenant_id)
    return _tenant_session_local_by_id[tenant_id]


def create_tables(engine=None) -> None:
    from app.models import (
        AiAgentTrace,
        AiConversation,
        AiMessage,
        AiMessageReference,
        CanvasDocument,
        CanvasTreeNode,
        UploadedFile,
        User,
        WorkerFile,
    )

    engine = engine or get_engine()
    tables = [
        User.__table__,
        UploadedFile.__table__,
        WorkerFile.__table__,
        CanvasTreeNode.__table__,
        CanvasDocument.__table__,
        AiConversation.__table__,
        AiMessage.__table__,
        AiMessageReference.__table__,
        AiAgentTrace.__table__,
    ]

    if engine.dialect.name == "postgresql":
        # Guard startup migrations against concurrent cold starts in FC.
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "SELECT pg_advisory_xact_lock(hashtext('app_schema_bootstrap_v1'))"
            )
            for table in tables:
                table.create(bind=connection, checkfirst=True)
        return

    for table in tables:
        try:
            table.create(bind=engine, checkfirst=True)
        except IntegrityError:
            logger.warning("ignored concurrent table creation race for %s", table.name)


def ensure_pgvector_extension(engine=None) -> None:
    engine = engine or get_engine()

    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")


def ensure_pg_search_extension(engine=None) -> None:
    engine = engine or get_engine()

    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_search")


def ensure_vector_store_schema(engine=None) -> None:
    from app.core.config import get_settings

    engine = engine or get_engine()

    if engine.dialect.name != "postgresql":
        return

    settings = get_settings()
    statements = [
        f"""
        CREATE TABLE IF NOT EXISTS {settings.pgvector_text_table} (
          id VARCHAR(128) PRIMARY KEY,
          file_id BIGINT NOT NULL,
          file_name VARCHAR(255) NOT NULL,
          file_ext VARCHAR(32) NOT NULL,
          mime_type VARCHAR(128) NOT NULL,
          page_start INTEGER NOT NULL DEFAULT 0,
          page_end INTEGER NOT NULL DEFAULT 0,
          small_chunk_index INTEGER NOT NULL,
          large_chunk_id VARCHAR(128) NOT NULL,
          small_chunk_text TEXT NOT NULL,
          large_chunk_text TEXT NOT NULL,
          source_type VARCHAR(64) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL,
          embedding VECTOR({settings.pgvector_text_vector_dimension}) NOT NULL
        )
        """,
        f"CREATE INDEX IF NOT EXISTS idx_{settings.pgvector_text_table}_file_id ON {settings.pgvector_text_table} (file_id)",
        (
            f"CREATE INDEX IF NOT EXISTS idx_{settings.pgvector_text_table}_embedding "
            f"ON {settings.pgvector_text_table} USING hnsw "
            f"(embedding {settings.pgvector_distance_operator}) "
            f"WITH (m = {settings.pgvector_hnsw_m}, ef_construction = {settings.pgvector_hnsw_ef_construction})"
        ),
        f"""
        CREATE TABLE IF NOT EXISTS {settings.pgvector_image_table} (
          id VARCHAR(128) PRIMARY KEY,
          file_id BIGINT NOT NULL,
          file_name VARCHAR(255) NOT NULL,
          file_ext VARCHAR(32) NOT NULL,
          mime_type VARCHAR(128) NOT NULL,
          image_index INTEGER NOT NULL,
          source_type VARCHAR(64) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL,
          embedding VECTOR({settings.pgvector_image_vector_dimension}) NOT NULL
        )
        """,
        f"CREATE INDEX IF NOT EXISTS idx_{settings.pgvector_image_table}_file_id ON {settings.pgvector_image_table} (file_id)",
        (
            f"CREATE INDEX IF NOT EXISTS idx_{settings.pgvector_image_table}_embedding "
            f"ON {settings.pgvector_image_table} USING hnsw "
            f"(embedding {settings.pgvector_distance_operator}) "
            f"WITH (m = {settings.pgvector_hnsw_m}, ef_construction = {settings.pgvector_hnsw_ef_construction})"
        ),
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement.strip())


def build_bm25_index_name(table_name: str) -> str:
    return f"idx_{table_name}_bm25"


def ensure_pg_search_bm25_index(engine=None) -> None:
    from app.core.config import get_settings

    engine = engine or get_engine()
    if not hasattr(engine, "dialect") or engine.dialect.name != "postgresql":
        return

    settings = get_settings()
    table_name = settings.pgvector_text_table
    _require_simple_pg_identifier(table_name, label="Settings.pgvector_text_table")
    index_name = build_bm25_index_name(table_name)
    _require_simple_pg_identifier(index_name, label="BM25 index name")

    statement = (
        f"CREATE INDEX IF NOT EXISTS {index_name} "
        f"ON {table_name} USING bm25 "
        "(id, file_id, file_name, small_chunk_index, created_at, small_chunk_text) "
        "WITH (key_field = 'id')"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(statement)


def _get_pg_extension_version(engine: Any, extension_name: str) -> str | None:
    try:
        if not hasattr(engine, "connect"):
            return None
        with engine.connect() as connection:
            result = connection.exec_driver_sql(
                "SELECT extversion FROM pg_extension WHERE extname = %s",
                (extension_name,),
            )
            return result.scalar_one_or_none()
    except Exception:
        return None


def _index_exists_via_inspector(inspector: Any, table_name: str, index_name: str) -> bool:
    try:
        indexes = inspector.get_indexes(table_name)
    except Exception:
        return False
    return any(index.get("name") == index_name for index in indexes)


_SIMPLE_PG_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_simple_pg_identifier(value: str, *, label: str) -> None:
    # 中文说明：BM25 就绪检查依赖固定索引命名和 inspector.has_table/get_indexes。
    # 如果这里允许 schema.table 或带引号的复杂标识符，启动期很容易出现“索引实际存在、
    # 但检查永远匹配不到”的假失败，所以直接在入口处快速拒绝。
    if not _SIMPLE_PG_IDENTIFIER_RE.fullmatch(value):
        raise RuntimeError(
            f"{label} must be a simple unqualified PostgreSQL identifier, got: {value!r}. "
            "Schema-qualified or quoted table names are not supported for BM25 readiness checks."
        )


def ensure_pg_search_ready(
    engine=None,
    inspector=None,
    extension_exists: bool | Callable[..., bool] | None = None,
    index_exists: bool | Callable[..., bool] | None = None,
) -> None:
    """
    Readiness checks for pg_search BM25 retrieval.

    This intentionally does not create the BM25 index at startup; it only verifies:
    - pg_search extension is installed
    - the expected bm25 index exists on the configured pgvector text table
    """
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.assistant_enable_bm25:
        return

    engine = engine or get_engine()
    if not hasattr(engine, "dialect") or engine.dialect.name != "postgresql":
        return

    inspector = inspector or inspect(engine)

    table_name = settings.pgvector_text_table
    _require_simple_pg_identifier(table_name, label="Settings.pgvector_text_table")
    index_name = build_bm25_index_name(table_name)

    def _eval_check(
        check: bool | Callable[..., bool] | None,
        default: Callable[[], bool],
    ) -> bool:
        if check is None:
            return default()
        if callable(check):
            try:
                return bool(
                    check(
                        engine=engine,
                        inspector=inspector,
                        table_name=table_name,
                        index_name=index_name,
                    )
                )
            except TypeError:
                return bool(check())
        return bool(check)

    # 中文说明：这里读取数据库里真实安装的 pg_search 版本，是为了把 SQL 语法锁定到
    # 当前环境，而不是按“我记忆中的某个版本”去猜，避免线上/本地版本不一致时踩坑。
    ext_version = _get_pg_extension_version(engine, "pg_search")

    ext_ok = _eval_check(
        extension_exists,
        default=lambda: ext_version is not None,
    )
    if not ext_ok:
        raise RuntimeError(
            "pg_search extension is required when assistant_enable_bm25 is enabled. "
            "Install it and create the BM25 index via backend/sql/004_add_pg_search_bm25.sql."
        )

    if ext_version:
        logger.info("pg_search extension version: %s", ext_version)
    else:
        logger.warning("pg_search extension is enabled but version could not be read")

    if not inspector.has_table(table_name):
        raise RuntimeError(
            f"BM25 retrieval requires pgvector text table '{table_name}' to exist."
        )

    # 中文说明：按用户要求，这次 BM25 不是“尽量用、失败就降级”，而是强依赖。
    # 只要开启 assistant_enable_bm25，就必须显式检查出索引已经准备好，否则直接启动失败。
    idx_ok = _eval_check(
        index_exists,
        default=lambda: _index_exists_via_inspector(inspector, table_name, index_name),
    )
    if not idx_ok:
        raise RuntimeError(
            f"BM25 retrieval requires index '{index_name}' to exist. "
            "Create it via backend/sql/004_add_pg_search_bm25.sql."
        )


def ensure_uploaded_file_schema(engine=None, inspector=None) -> None:
    engine = engine or get_engine()
    inspector = inspector or inspect(engine)

    if engine.dialect.name != "postgresql":
        return

    if not inspector.has_table("uploaded_file"):
        return

    columns = {column["name"] for column in inspector.get_columns("uploaded_file")}
    indexes = {index["name"] for index in inspector.get_indexes("uploaded_file")}
    statements: list[str] = []

    if "user_id" not in columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN user_id VARCHAR(36) NOT NULL DEFAULT 'system'"
        )
    if "vector_status" not in columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN vector_status VARCHAR(32) NOT NULL DEFAULT 'PENDING'"
        )
    if "vector_error" not in columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN vector_error VARCHAR(1024) NULL"
        )
    if "chunk_count" not in columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN chunk_count INT NOT NULL DEFAULT 0"
        )
    if "text_vector_status" not in columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN text_vector_status VARCHAR(32) NOT NULL DEFAULT 'PENDING'"
        )
    if "text_vector_error" not in columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN text_vector_error VARCHAR(1024) NULL"
        )
    if "text_chunk_count" not in columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN text_chunk_count INT NOT NULL DEFAULT 0"
        )
    if "image_vector_status" not in columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN image_vector_status VARCHAR(32) NULL"
        )
    if "image_vector_error" not in columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN image_vector_error VARCHAR(1024) NULL"
        )
    if "image_chunk_count" not in columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN image_chunk_count INT NOT NULL DEFAULT 0"
        )
    if "vectorized_at" not in columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN vectorized_at TIMESTAMPTZ NULL"
        )
    if "idx_uploaded_file_user_id" not in indexes:
        statements.append(
            "CREATE INDEX idx_uploaded_file_user_id ON uploaded_file (user_id)"
        )
    if "idx_uploaded_file_vector_status" not in indexes:
        statements.append(
            "CREATE INDEX idx_uploaded_file_vector_status ON uploaded_file (vector_status)"
        )
    if "idx_uploaded_file_text_vector_status" not in indexes:
        statements.append(
            "CREATE INDEX idx_uploaded_file_text_vector_status ON uploaded_file (text_vector_status)"
        )
    if "idx_uploaded_file_image_vector_status" not in indexes:
        statements.append(
            "CREATE INDEX idx_uploaded_file_image_vector_status ON uploaded_file (image_vector_status)"
        )

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


def ensure_worker_file_schema(engine=None, inspector=None) -> None:
    engine = engine or get_engine()
    inspector = inspector or inspect(engine)

    if engine.dialect.name != "postgresql":
        return

    if not inspector.has_table("worker_file"):
        return

    columns = {column["name"] for column in inspector.get_columns("worker_file")}
    indexes = {index["name"] for index in inspector.get_indexes("worker_file")}
    statements: list[str] = []

    if "user_id" not in columns:
        statements.append(
            "ALTER TABLE worker_file ADD COLUMN user_id VARCHAR(36) NOT NULL DEFAULT 'system'"
        )
    if "idx_worker_file_user_id" not in indexes:
        statements.append(
            "CREATE INDEX idx_worker_file_user_id ON worker_file (user_id)"
        )

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


def ensure_ai_message_schema(engine=None, inspector=None) -> None:
    engine = engine or get_engine()
    inspector = inspector or inspect(engine)

    if engine.dialect.name != "postgresql":
        return

    if not inspector.has_table("ai_message"):
        return

    columns = {column["name"] for column in inspector.get_columns("ai_message")}
    statements: list[str] = []
    if "payload_json" not in columns:
        statements.append("ALTER TABLE ai_message ADD COLUMN payload_json TEXT NULL")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


def ensure_ai_agent_trace_schema(engine=None, inspector=None) -> None:
    engine = engine or get_engine()
    if not hasattr(engine, "dialect") or engine.dialect.name != "postgresql":
        return

    inspector = inspector or inspect(engine)
    table_name = "ai_agent_trace"
    if not inspector.has_table(table_name):
        return

    columns = {column["name"] for column in inspector.get_columns(table_name)}
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    statements: list[str] = []
    if "phase" not in columns:
        statements.append(
            "ALTER TABLE ai_agent_trace ADD COLUMN phase VARCHAR(32) NOT NULL DEFAULT 'reason'"
        )
    if "decision_type" not in columns:
        statements.append(
            "ALTER TABLE ai_agent_trace ADD COLUMN decision_type VARCHAR(32) NOT NULL DEFAULT 'reason'"
        )
    if "status" not in columns:
        statements.append(
            "ALTER TABLE ai_agent_trace ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'running'"
        )
    if "step_index" not in columns:
        statements.append(
            "ALTER TABLE ai_agent_trace ADD COLUMN step_index INTEGER NOT NULL DEFAULT 0"
        )
    if "tool_name" not in columns:
        statements.append("ALTER TABLE ai_agent_trace ADD COLUMN tool_name VARCHAR(128) NULL")
    if "tool_args_json" not in columns:
        statements.append("ALTER TABLE ai_agent_trace ADD COLUMN tool_args_json TEXT NULL")
    if "observation_json" not in columns:
        statements.append(
            "ALTER TABLE ai_agent_trace ADD COLUMN observation_json TEXT NULL"
        )
    if "reason_summary" not in columns:
        statements.append("ALTER TABLE ai_agent_trace ADD COLUMN reason_summary TEXT NULL")
    if "error_code" not in columns:
        statements.append("ALTER TABLE ai_agent_trace ADD COLUMN error_code VARCHAR(64) NULL")
    if "error_message" not in columns:
        statements.append(
            "ALTER TABLE ai_agent_trace ADD COLUMN error_message TEXT NULL"
        )
    if "created_at" not in columns:
        statements.append(
            "ALTER TABLE ai_agent_trace ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
        )

    required_indexes: dict[str, str] = {
        "idx_ai_agent_trace_conversation_id": "conversation_id",
        "idx_ai_agent_trace_session_id": "session_id",
        "idx_ai_agent_trace_created_at": "created_at",
    }
    for index_name, column_name in required_indexes.items():
        if index_name not in indexes:
            statements.append(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})"
            )

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


def ensure_canvas_schema(engine=None, inspector=None) -> None:
    engine = engine or get_engine()
    if not hasattr(engine, "dialect"):
        return
    inspector = inspector or inspect(engine)

    if engine.dialect.name != "postgresql":
        return

    statements: list[str] = []

    if inspector.has_table("canvas_document"):
        columns = {column["name"] for column in inspector.get_columns("canvas_document")}
        indexes = {index["name"] for index in inspector.get_indexes("canvas_document")}
        unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("canvas_document")
            if constraint.get("name")
        }

        if "node_id" not in columns:
            statements.append("ALTER TABLE canvas_document ADD COLUMN node_id VARCHAR(36)")
            statements.append("UPDATE canvas_document SET node_id = id WHERE node_id IS NULL")
            statements.append("ALTER TABLE canvas_document ALTER COLUMN node_id SET NOT NULL")
        if "idx_canvas_document_user_node" not in indexes:
            statements.append(
                "CREATE INDEX idx_canvas_document_user_node ON canvas_document (user_id, node_id)"
            )
        if "uq_canvas_document_user_node" not in unique_constraints:
            statements.append(
                "ALTER TABLE canvas_document ADD CONSTRAINT uq_canvas_document_user_node UNIQUE (user_id, node_id)"
            )

    if inspector.has_table("canvas_tree_node"):
        indexes = {index["name"] for index in inspector.get_indexes("canvas_tree_node")}
        if "idx_canvas_tree_node_user_parent" not in indexes:
            statements.append(
                "CREATE INDEX idx_canvas_tree_node_user_parent ON canvas_tree_node (user_id, parent_id)"
            )

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


def ensure_tenant_registry_schema(engine=None) -> None:
    from app.core.config import get_settings
    from app.models.tenant import Tenant

    engine = engine or get_engine()
    settings = get_settings()

    Tenant.__table__.create(bind=engine, checkfirst=True)

    with get_control_session_local()() as control_db:
        default_tenant = control_db.scalar(
            select(Tenant).where(Tenant.tenant_id == settings.default_tenant_id)
        )
        if default_tenant is None:
            control_db.add(
                Tenant(
                    tenant_id=settings.default_tenant_id,
                    name="默认租户",
                    database_url=settings.postgres_database_url,
                    config_json="{}",
                    enabled=True,
                )
            )
            control_db.commit()


def get_session_local():
    return get_control_session_local()


def get_control_db() -> Generator[Session, None, None]:
    db = get_control_session_local()()

    try:
        yield db
    finally:
        db.close()


def get_db(
    tenant_id: str = Depends(get_tenant_id),
) -> Generator[Session, None, None]:
    db = get_tenant_session_local(tenant_id)()

    try:
        yield db
    finally:
        db.close()
