from app.core.database import (
    build_bm25_index_name,
    create_tables,
    ensure_ai_agent_trace_schema,
    ensure_ai_message_schema,
    ensure_pgvector_extension,
    ensure_pg_search_ready,
    ensure_worker_file_schema,
    ensure_uploaded_file_schema,
    ensure_vector_store_schema,
)
from sqlalchemy import create_engine, inspect


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> None:
        self.statements.append(statement)


class FakeBegin:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FakeDialect:
    name = "postgresql"


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.dialect = FakeDialect()

    def begin(self) -> FakeBegin:
        return FakeBegin(self.connection)


class FakeInspector:
    def __init__(
        self,
        columns: list[str],
        indexes: list[str],
        has_table: bool = True,
        table_name: str = "uploaded_file",
    ) -> None:
        self.columns = columns
        self.indexes = indexes
        self._has_table = has_table
        self.table_name = table_name

    def has_table(self, table_name: str) -> bool:
        assert table_name == self.table_name
        return self._has_table

    def get_columns(self, table_name: str) -> list[dict]:
        assert table_name == self.table_name
        return [{"name": column} for column in self.columns]

    def get_indexes(self, table_name: str) -> list[dict]:
        assert table_name == self.table_name
        return [{"name": name} for name in self.indexes]


def test_ensure_pgvector_extension_creates_vector_extension() -> None:
    engine = FakeEngine()

    ensure_pgvector_extension(engine)

    assert engine.connection.statements == ["CREATE EXTENSION IF NOT EXISTS vector"]


def test_ensure_uploaded_file_schema_adds_missing_vector_columns() -> None:
    engine = FakeEngine()
    inspector = FakeInspector(
        columns=[
            "id",
            "file_name",
            "file_ext",
            "mime_type",
            "file_size",
            "oss_bucket",
            "oss_key",
            "public_url",
            "status",
            "created_at",
            "updated_at",
        ],
        indexes=["idx_uploaded_file_created_at"],
    )

    ensure_uploaded_file_schema(engine=engine, inspector=inspector)

    assert engine.connection.statements == [
        "ALTER TABLE uploaded_file ADD COLUMN user_id VARCHAR(36) NOT NULL DEFAULT 'system'",
        "ALTER TABLE uploaded_file ADD COLUMN vector_status VARCHAR(32) NOT NULL DEFAULT 'PENDING'",
        "ALTER TABLE uploaded_file ADD COLUMN vector_error VARCHAR(1024) NULL",
        "ALTER TABLE uploaded_file ADD COLUMN chunk_count INT NOT NULL DEFAULT 0",
        "ALTER TABLE uploaded_file ADD COLUMN text_vector_status VARCHAR(32) NOT NULL DEFAULT 'PENDING'",
        "ALTER TABLE uploaded_file ADD COLUMN text_vector_error VARCHAR(1024) NULL",
        "ALTER TABLE uploaded_file ADD COLUMN text_chunk_count INT NOT NULL DEFAULT 0",
        "ALTER TABLE uploaded_file ADD COLUMN image_vector_status VARCHAR(32) NULL",
        "ALTER TABLE uploaded_file ADD COLUMN image_vector_error VARCHAR(1024) NULL",
        "ALTER TABLE uploaded_file ADD COLUMN image_chunk_count INT NOT NULL DEFAULT 0",
        "ALTER TABLE uploaded_file ADD COLUMN vectorized_at TIMESTAMPTZ NULL",
        "CREATE INDEX idx_uploaded_file_user_id ON uploaded_file (user_id)",
        "CREATE INDEX idx_uploaded_file_vector_status ON uploaded_file (vector_status)",
        "CREATE INDEX idx_uploaded_file_text_vector_status ON uploaded_file (text_vector_status)",
        "CREATE INDEX idx_uploaded_file_image_vector_status ON uploaded_file (image_vector_status)",
    ]


def test_ensure_uploaded_file_schema_skips_when_schema_is_current() -> None:
    engine = FakeEngine()
    inspector = FakeInspector(
        columns=[
            "id",
            "file_name",
            "file_ext",
            "mime_type",
            "file_size",
            "oss_bucket",
            "oss_key",
            "public_url",
            "status",
            "user_id",
            "vector_status",
            "vector_error",
            "chunk_count",
            "text_vector_status",
            "text_vector_error",
            "text_chunk_count",
            "image_vector_status",
            "image_vector_error",
            "image_chunk_count",
            "created_at",
            "updated_at",
            "vectorized_at",
        ],
        indexes=[
            "idx_uploaded_file_created_at",
            "idx_uploaded_file_user_id",
            "idx_uploaded_file_vector_status",
            "idx_uploaded_file_text_vector_status",
            "idx_uploaded_file_image_vector_status",
        ],
    )

    ensure_uploaded_file_schema(engine=engine, inspector=inspector)

    assert engine.connection.statements == []


def test_ensure_worker_file_schema_adds_user_id_column() -> None:
    engine = FakeEngine()
    inspector = FakeInspector(
        columns=["id", "name", "content", "created_at"],
        indexes=[],
        table_name="worker_file",
    )

    ensure_worker_file_schema(engine=engine, inspector=inspector)

    assert engine.connection.statements == [
        "ALTER TABLE worker_file ADD COLUMN user_id VARCHAR(36) NOT NULL DEFAULT 'system'",
        "CREATE INDEX idx_worker_file_user_id ON worker_file (user_id)",
    ]


def test_ensure_ai_message_schema_adds_payload_json_column() -> None:
    engine = FakeEngine()
    inspector = FakeInspector(
        columns=[
            "id",
            "conversation_id",
            "role",
            "intent",
            "content",
            "status",
            "created_at",
        ],
        indexes=["idx_ai_message_created_at"],
        table_name="ai_message",
    )

    ensure_ai_message_schema(engine=engine, inspector=inspector)

    assert engine.connection.statements == [
        "ALTER TABLE ai_message ADD COLUMN payload_json TEXT NULL",
    ]


def test_ensure_ai_message_schema_skips_when_column_exists() -> None:
    engine = FakeEngine()
    inspector = FakeInspector(
        columns=[
            "id",
            "conversation_id",
            "role",
            "intent",
            "content",
            "status",
            "payload_json",
            "created_at",
        ],
        indexes=["idx_ai_message_created_at"],
        table_name="ai_message",
    )

    ensure_ai_message_schema(engine=engine, inspector=inspector)

    assert engine.connection.statements == []


def test_create_tables_includes_ai_agent_trace() -> None:
    engine = create_engine("sqlite:///:memory:")
    create_tables(engine)
    inspector = inspect(engine)
    assert "ai_agent_trace" in inspector.get_table_names()


def test_ensure_ai_agent_trace_schema_adds_missing_columns() -> None:
    engine = FakeEngine()
    inspector = FakeInspector(
        columns=["id", "conversation_id", "session_id"],
        indexes=[],
        table_name="ai_agent_trace",
    )

    ensure_ai_agent_trace_schema(engine=engine, inspector=inspector)

    statements = engine.connection.statements
    expected_statements = [
        "ALTER TABLE ai_agent_trace ADD COLUMN phase VARCHAR(32) NOT NULL DEFAULT 'reason'",
        "ALTER TABLE ai_agent_trace ADD COLUMN decision_type VARCHAR(32) NOT NULL DEFAULT 'reason'",
        "ALTER TABLE ai_agent_trace ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'running'",
        "ALTER TABLE ai_agent_trace ADD COLUMN step_index INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE ai_agent_trace ADD COLUMN tool_name VARCHAR(128) NULL",
        "ALTER TABLE ai_agent_trace ADD COLUMN tool_args_json TEXT NULL",
        "ALTER TABLE ai_agent_trace ADD COLUMN observation_json TEXT NULL",
        "ALTER TABLE ai_agent_trace ADD COLUMN reason_summary TEXT NULL",
        "ALTER TABLE ai_agent_trace ADD COLUMN error_code VARCHAR(64) NULL",
        "ALTER TABLE ai_agent_trace ADD COLUMN error_message TEXT NULL",
        "ALTER TABLE ai_agent_trace ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "CREATE INDEX IF NOT EXISTS idx_ai_agent_trace_conversation_id ON ai_agent_trace (conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_agent_trace_session_id ON ai_agent_trace (session_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_agent_trace_created_at ON ai_agent_trace (created_at)",
    ]
    assert statements == expected_statements


def test_ensure_ai_agent_trace_schema_skips_when_schema_is_current() -> None:
    engine = FakeEngine()
    inspector = FakeInspector(
        columns=[
            "id",
            "conversation_id",
            "session_id",
            "step_index",
            "phase",
            "decision_type",
            "tool_name",
            "tool_args_json",
            "observation_json",
            "status",
            "reason_summary",
            "error_code",
            "error_message",
            "created_at",
        ],
        indexes=[
            "idx_ai_agent_trace_conversation_id",
            "idx_ai_agent_trace_session_id",
            "idx_ai_agent_trace_created_at",
        ],
        table_name="ai_agent_trace",
    )

    ensure_ai_agent_trace_schema(engine=engine, inspector=inspector)

    assert engine.connection.statements == []


def test_ensure_vector_store_schema_creates_pgvector_tables(monkeypatch) -> None:
    engine = FakeEngine()

    class FakeSettings:
        pgvector_text_table = "uploaded_file_text_vector"
        pgvector_image_table = "uploaded_file_image_vector"
        pgvector_text_vector_dimension = 1024
        pgvector_image_vector_dimension = 512
        pgvector_distance_operator = "vector_cosine_ops"
        pgvector_hnsw_m = 16
        pgvector_hnsw_ef_construction = 200

    monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())

    ensure_vector_store_schema(engine=engine)

    assert "CREATE TABLE IF NOT EXISTS uploaded_file_text_vector" in engine.connection.statements[0]
    assert "embedding VECTOR(1024) NOT NULL" in engine.connection.statements[0]
    assert "USING hnsw (embedding vector_cosine_ops)" in engine.connection.statements[2]
    assert "CREATE TABLE IF NOT EXISTS uploaded_file_image_vector" in engine.connection.statements[3]
    assert "embedding VECTOR(512) NOT NULL" in engine.connection.statements[3]


def test_build_bm25_index_name_is_stable() -> None:
    assert build_bm25_index_name("uploaded_file_text_vector") == "idx_uploaded_file_text_vector_bm25"


def test_ensure_pg_search_ready_returns_immediately_when_bm25_disabled(monkeypatch) -> None:
    engine = FakeEngine()

    class FakeSettings:
        assistant_enable_bm25 = False
        pgvector_text_table = "uploaded_file_text_vector"

    monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())

    # Should not raise even if checks would fail; feature is disabled.
    ensure_pg_search_ready(engine=engine, extension_exists=False, index_exists=False)


def test_ensure_pg_search_ready_requires_extension_when_bm25_enabled(monkeypatch) -> None:
    engine = FakeEngine()
    inspector = FakeInspector(columns=[], indexes=[], table_name="uploaded_file_text_vector")

    class FakeSettings:
        assistant_enable_bm25 = True
        pgvector_text_table = "uploaded_file_text_vector"

    monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())

    import pytest

    with pytest.raises(RuntimeError, match="pg_search extension is required"):
        ensure_pg_search_ready(
            engine=engine,
            inspector=inspector,
            extension_exists=False,
            index_exists=False,
        )


def test_ensure_pg_search_ready_requires_named_bm25_index(monkeypatch) -> None:
    engine = FakeEngine()
    inspector = FakeInspector(columns=[], indexes=[], table_name="uploaded_file_text_vector")

    class FakeSettings:
        assistant_enable_bm25 = True
        pgvector_text_table = "uploaded_file_text_vector"

    monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())

    import pytest

    with pytest.raises(RuntimeError, match="idx_uploaded_file_text_vector_bm25"):
        ensure_pg_search_ready(
            engine=engine,
            inspector=inspector,
            extension_exists=True,
            index_exists=False,
        )


def test_ensure_pg_search_ready_passes_when_extension_and_index_exist(monkeypatch) -> None:
    engine = FakeEngine()
    inspector = FakeInspector(
        columns=[],
        indexes=["idx_uploaded_file_text_vector_bm25"],
        table_name="uploaded_file_text_vector",
    )

    class FakeSettings:
        assistant_enable_bm25 = True
        pgvector_text_table = "uploaded_file_text_vector"

    monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())

    ensure_pg_search_ready(
        engine=engine,
        inspector=inspector,
        extension_exists=True,
        index_exists=True,
    )


def test_ensure_pg_search_ready_uses_default_index_existence_check(monkeypatch) -> None:
    engine = FakeEngine()
    inspector = FakeInspector(
        columns=[],
        indexes=["idx_uploaded_file_text_vector_bm25"],
        table_name="uploaded_file_text_vector",
    )

    class FakeSettings:
        assistant_enable_bm25 = True
        pgvector_text_table = "uploaded_file_text_vector"

    monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())

    # Don't pass index_exists so the implementation exercises the inspector path.
    ensure_pg_search_ready(
        engine=engine,
        inspector=inspector,
        extension_exists=True,
    )
