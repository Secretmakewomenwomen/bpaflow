from types import SimpleNamespace

import pytest

import app.services.pgvector_service as pgvector_module
from app.services.pgvector_service import PgVectorService

EXPECTED_RETRIEVAL_ALIASES = {
    "file_id",
    "upload_id",
    "file_name",
    "mime_type",
    "created_at",
    "download_url",
    "small_chunk_text",
    "large_chunk_text",
    "page_start",
    "page_end",
    "small_chunk_index",
    "distance",
    "bm25_score",
    "rule_score",
}


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict]:
        return self.rows


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.result: FakeResult | None = None

    def execute(self, statement, params: dict):
        self.calls.append((str(statement), params))
        return self.result or FakeResult([])


class FakeBegin:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self) -> FakeBegin:
        return FakeBegin(self.connection)


def build_service() -> tuple[PgVectorService, FakeEngine]:
    engine = FakeEngine()
    service = PgVectorService(
        SimpleNamespace(
            pgvector_text_table="uploaded_file_text_vector",
            pgvector_image_table="uploaded_file_image_vector",
            pgvector_text_vector_dimension=2,
            pgvector_image_vector_dimension=2,
        ),
        engine=engine,
    )
    return service, engine


def test_pgvector_service_replaces_text_and_image_rows_in_matching_tables() -> None:
    service, engine = build_service()

    service.replace_text_chunks(9, [{"id": "t1", "file_id": 9, "embedding": [0.1, 0.2], "created_at": "2026-03-28T00:00:00+00:00"}])
    service.replace_image_vectors(9, [{"id": "i1", "file_id": 9, "embedding": [0.3, 0.4], "created_at": "2026-03-28T00:00:00+00:00"}])

    assert "DELETE FROM uploaded_file_text_vector WHERE file_id = :file_id" in engine.connection.calls[0][0]
    assert engine.connection.calls[0][1] == {"file_id": 9}
    assert "INSERT INTO uploaded_file_text_vector" in engine.connection.calls[1][0]
    assert "CAST(:embedding_vector AS vector)" in engine.connection.calls[1][0]
    assert engine.connection.calls[1][1]["embedding_vector"] == "[0.1,0.2]"
    assert "DELETE FROM uploaded_file_image_vector WHERE file_id = :file_id" in engine.connection.calls[2][0]
    assert "INSERT INTO uploaded_file_image_vector" in engine.connection.calls[3][0]
    assert "CAST(:embedding_vector AS vector)" in engine.connection.calls[3][0]
    assert engine.connection.calls[3][1]["embedding_vector"] == "[0.3,0.4]"


def test_pgvector_service_deletes_text_and_image_vectors_for_same_file() -> None:
    service, engine = build_service()

    service.delete_file_vectors(7)

    assert "DELETE FROM uploaded_file_text_vector WHERE file_id = :file_id" in engine.connection.calls[0][0]
    assert "DELETE FROM uploaded_file_image_vector WHERE file_id = :file_id" in engine.connection.calls[1][0]
    assert engine.connection.calls[0][1] == {"file_id": 7}
    assert engine.connection.calls[1][1] == {"file_id": 7}


def test_pgvector_service_ensure_collection_calls_schema_helper(monkeypatch) -> None:
    service, _ = build_service()
    captured = {"engines": []}

    def fake_ensure_vector_store_schema(engine=None) -> None:
        captured["engines"].append(engine)

    monkeypatch.setattr(
        pgvector_module,
        "ensure_vector_store_schema",
        fake_ensure_vector_store_schema,
    )

    service.ensure_text_collection()
    service.ensure_image_collection()

    assert captured["engines"] == [service.engine, service.engine]


def test_pgvector_service_replace_rows_rejects_unsafe_column_name() -> None:
    service, _ = build_service()

    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        service.replace_text_chunks(
            9,
            [
                {
                    "id": "t1",
                    "file_id": 9,
                    "embedding": [0.1, 0.2],
                    "bad-column": "x",
                }
            ],
        )


def test_pgvector_service_validates_embedding_dimension_for_replacements() -> None:
    service, _ = build_service()

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        service.replace_text_chunks(
            9,
            [{"id": "t1", "file_id": 9, "embedding": [0.1]}],
        )

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        service.replace_image_vectors(
            9,
            [{"id": "i1", "file_id": 9, "embedding": [0.1, 0.2, 0.3]}],
        )


def test_pgvector_service_validates_text_query_embedding_dimension() -> None:
    service, _ = build_service()

    with pytest.raises(ValueError, match="Query embedding dimension mismatch"):
        service.search_text_similar_chunks(
            user_id="u-1",
            query_embedding=[0.1],
            top_k=3,
        )


def test_pgvector_service_validates_top_k_bounds() -> None:
    service, _ = build_service()

    with pytest.raises(ValueError, match="top_k must be between 1 and 1000"):
        service.search_text_similar_chunks(
            user_id="u-1",
            query_embedding=[0.1, 0.2],
            top_k=0,
        )

    with pytest.raises(ValueError, match="top_k must be between 1 and 1000"):
        service.search_text_similar_chunks(
            user_id="u-1",
            query_embedding=[0.1, 0.2],
            top_k=1001,
        )


def test_pgvector_service_vector_query_selects_unified_columns() -> None:
    service, engine = build_service()
    engine.connection.result = FakeResult([])

    service.search_text_similar_chunks(
        user_id="u-1",
        query_embedding=[0.1, 0.2],
        top_k=5,
    )

    sql = engine.connection.calls[0][0]
    for alias in EXPECTED_RETRIEVAL_ALIASES:
        assert f" AS {alias}" in sql
    assert "vectors.file_id AS file_id" in sql
    assert "uf.id AS upload_id" in sql
    assert "vectors.file_name AS file_name" in sql
    assert "vectors.mime_type AS mime_type" in sql
    assert "vectors.large_chunk_text AS large_chunk_text" in sql
    assert "(vectors.embedding <=> CAST(:query_embedding AS vector)) AS distance" in sql
    assert "NULL::double precision AS bm25_score" in sql
    assert "NULL::double precision AS rule_score" in sql


def test_pgvector_service_encode_vector_rejects_non_numeric_and_non_finite_values() -> None:
    service, _ = build_service()

    with pytest.raises(ValueError, match="Vector element at index 1 must be numeric"):
        service._encode_vector([0.1, "x"])  # type: ignore[list-item]

    with pytest.raises(ValueError, match="Vector element at index 1 must be finite"):
        service._encode_vector([0.1, float("nan")])

    with pytest.raises(ValueError, match="Vector element at index 1 must be finite"):
        service._encode_vector([0.1, float("inf")])


def test_pgvector_service_builds_bm25_query_against_dynamic_text_table() -> None:
    service, engine = build_service()
    engine.connection.result = FakeResult([])

    service.search_text_bm25_chunks(
        user_id="u-1",
        query_text="claim policy",
        top_k=5,
    )

    sql = engine.connection.calls[0][0]
    for alias in EXPECTED_RETRIEVAL_ALIASES:
        assert f" AS {alias}" in sql
    assert "FROM uploaded_file_text_vector AS vectors" in sql
    assert "JOIN uploaded_file AS uf ON uf.id = vectors.file_id" in sql
    assert "uf.user_id = :user_id" in sql
    assert "uf.text_vector_status = 'VECTORIZED'" in sql
    assert "uf.created_at AS created_at" in sql
    assert "uf.public_url AS download_url" in sql
    assert "vectors.file_id AS file_id" in sql
    assert "uf.id AS upload_id" in sql
    assert "vectors.file_name AS file_name" in sql
    assert "vectors.mime_type AS mime_type" in sql
    assert "vectors.large_chunk_text AS large_chunk_text" in sql
    assert "NULL::double precision AS distance" in sql
    assert "NULL::double precision AS rule_score" in sql
    assert "pdb.score(vectors.id) AS bm25_score" in sql
    assert "vectors.small_chunk_text ||| :query" in sql
    assert "vectors.file_name ||| :query::pdb.boost(2)" in sql
    assert "OR vectors.file_name ||| :query::pdb.boost(2)" in sql
    assert "ORDER BY pdb.score(vectors.id) DESC, uf.id DESC, vectors.small_chunk_index ASC" in sql


def test_pgvector_service_builds_file_name_rule_query() -> None:
    service, engine = build_service()
    engine.connection.result = FakeResult([])

    service.search_rule_candidate_chunks(
        user_id="u-1",
        file_name_tokens=["claim", "policy"],
        per_file_limit=2,
        top_k=6,
    )

    sql = engine.connection.calls[0][0]
    for alias in EXPECTED_RETRIEVAL_ALIASES:
        assert f" AS {alias}" in sql
    assert "FROM uploaded_file_text_vector AS vectors" in sql
    assert "WITH ranked AS" in sql
    assert "JOIN uploaded_file AS uf ON uf.id = vectors.file_id" in sql
    assert "uf.user_id = :user_id" in sql
    assert "uf.text_vector_status = 'VECTORIZED'" in sql
    assert "LOWER(vectors.file_name) LIKE" in sql
    assert "LOWER(vectors.file_name) LIKE :token_0 OR LOWER(vectors.file_name) LIKE :token_1" in sql
    assert (
        "ROW_NUMBER() OVER (PARTITION BY vectors.file_id ORDER BY vectors.small_chunk_index ASC)"
        in sql
    )
    assert "ranked.rn <= :per_file_limit" in sql
    assert "uf.created_at AS created_at" in sql
    assert "uf.public_url AS download_url" in sql
    assert "vectors.file_id AS file_id" in sql
    assert "uf.id AS upload_id" in sql
    assert "vectors.file_name AS file_name" in sql
    assert "vectors.mime_type AS mime_type" in sql
    assert "vectors.large_chunk_text AS large_chunk_text" in sql
    assert "NULL::double precision AS distance" in sql
    assert "NULL::double precision AS bm25_score" in sql
    assert "1.0::double precision AS rule_score" in sql
    assert "ORDER BY ranked.created_at DESC, ranked.file_id DESC, ranked.small_chunk_index ASC" in sql
