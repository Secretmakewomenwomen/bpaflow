# AI Assistant Multi-Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the backend RAG retrieval path to support vector retrieval, `pg_search` BM25 retrieval, and rule-based retrieval with deterministic fusion and ranking.

**Architecture:** Keep the existing LangGraph flow unchanged and concentrate the new behavior in `backend/app/ai/services/ai_rag_service.py` plus database/query helpers. PostgreSQL remains the single search backend: `pgvector` handles semantic retrieval, `pg_search` handles BM25 on the existing text chunk table, and rule retrieval uses deterministic SQL + Python scoring on the same user-scoped data model.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL + pgvector, `pg_search`, pytest

---

### Task 1: Retrieval Config Defaults And Feature Flags

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/test_ai_config.py`

- [ ] **Step 1: Write the failing config test**

```python
from app.core.config import Settings


def test_multi_retrieval_settings_have_safe_defaults() -> None:
    settings = Settings(
        _env_file=None,
        postgres_database_url="postgresql://postgres:pass@localhost:5432/postgres",
        oss_region="cn-hangzhou",
        oss_bucket="filebucket",
        oss_endpoint="oss-cn-hangzhou.aliyuncs.com",
        oss_access_key_id="id",
        oss_access_key_secret="secret",
        oss_public_base_url="https://bucket.oss-cn-hangzhou.aliyuncs.com",
    )

    assert settings.assistant_enable_bm25 is False
    assert settings.assistant_enable_rule_retrieval is True
    assert settings.assistant_min_similarity_score == 0.45
    assert settings.assistant_vector_retrieval_top_k == 18
    assert settings.assistant_bm25_retrieval_top_k == 18
    assert settings.assistant_rule_retrieval_top_k == 12
    assert settings.assistant_rule_chunks_per_file == 2
    assert settings.assistant_vector_weight == 0.45
    assert settings.assistant_bm25_weight == 0.40
    assert settings.assistant_rule_weight == 0.15
    assert settings.assistant_recent_window_days == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ai_config.py -v`
Expected: FAIL because the new retrieval settings do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add the new retrieval settings to `backend/app/core/config.py`:

```python
assistant_enable_bm25: bool = False
assistant_enable_rule_retrieval: bool = True
assistant_min_similarity_score: float = 0.45
assistant_vector_retrieval_top_k: int = 18
assistant_bm25_retrieval_top_k: int = 18
assistant_rule_retrieval_top_k: int = 12
assistant_rule_chunks_per_file: int = 2
assistant_vector_weight: float = 0.45
assistant_bm25_weight: float = 0.40
assistant_rule_weight: float = 0.15
assistant_bonus_file_name_exact: float = 0.12
assistant_bonus_term_hit: float = 0.08
assistant_bonus_recent: float = 0.05
assistant_bonus_type_match: float = 0.05
assistant_recent_window_days: int = 7
```

Do not remove or repurpose the existing `assistant_retrieval_top_k`, `assistant_max_context_blocks`, or `assistant_max_related_files`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ai_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/test_ai_config.py
git commit -m "feat: add multi-retrieval config defaults"
```

### Task 2: Database Readiness Checks And BM25 Migration Script

**Files:**
- Create: `backend/sql/003_add_pg_search_bm25.sql`
- Modify: `backend/app/core/database.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_database_schema.py`

- [ ] **Step 1: Write the failing database readiness tests**

Extend `backend/tests/test_database_schema.py` with tests like:

```python
def test_ensure_pg_search_ready_requires_extension_when_bm25_enabled(monkeypatch) -> None:
    engine = FakeEngine()

    class FakeSettings:
        assistant_enable_bm25 = True
        pgvector_text_table = "uploaded_file_text_vector"

    monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())

    with pytest.raises(RuntimeError, match="pg_search extension is required"):
        ensure_pg_search_ready(engine=engine, extension_exists=False, index_exists=False)


def test_ensure_pg_search_ready_requires_named_bm25_index(monkeypatch) -> None:
    engine = FakeEngine()

    class FakeSettings:
        assistant_enable_bm25 = True
        pgvector_text_table = "uploaded_file_text_vector"

    monkeypatch.setattr("app.core.config.get_settings", lambda: FakeSettings())

    with pytest.raises(RuntimeError, match="idx_uploaded_file_text_vector_bm25"):
        ensure_pg_search_ready(engine=engine, extension_exists=True, index_exists=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_database_schema.py -v`
Expected: FAIL because `ensure_pg_search_ready()` and BM25 index naming do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement `ensure_pg_search_ready()` in `backend/app/core/database.py` with a helper like:

```python
def build_bm25_index_name(table_name: str) -> str:
    return f"idx_{table_name}_bm25"
```

Requirements:
- If `assistant_enable_bm25` is `False`, return immediately.
- If enabled, verify `pg_search` is installed.
- If enabled, verify `idx_<pgvector_text_table>_bm25` exists.
- Do not create the BM25 index at startup.
- Add a small helper to read and log the installed `pg_search` extension version so the implementation can lock SQL/query syntax to that exact version.

Create `backend/sql/003_add_pg_search_bm25.sql` as a parameterized `psql` script:

```sql
\set pgvector_text_table 'uploaded_file_text_vector'

CREATE EXTENSION IF NOT EXISTS pg_search;

SELECT format(
  'CREATE INDEX CONCURRENTLY IF NOT EXISTS %I ON %I USING bm25 (id, file_id, file_name, small_chunk_index, created_at, small_chunk_text) WITH (key_field = %L)',
  'idx_' || :'pgvector_text_table' || '_bm25',
  :'pgvector_text_table',
  'id'
) \gexec
```

During execution, pass the real table name from `Settings.pgvector_text_table`:

```bash
psql "<POSTGRES_DSN>" -v pgvector_text_table="<REAL_TABLE_NAME>" -f sql/003_add_pg_search_bm25.sql
```

Update `backend/app/main.py` to call `ensure_pg_search_ready(engine)` after the existing pgvector and schema setup.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_database_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/sql/003_add_pg_search_bm25.sql backend/app/core/database.py backend/app/main.py backend/tests/test_database_schema.py
git commit -m "feat: add pg_search readiness checks"
```

### Task 3: PgVector Service BM25 And Rule Query Helpers

**Files:**
- Modify: `backend/app/services/pgvector_service.py`
- Modify: `backend/tests/test_pgvector_service.py`

- [ ] **Step 1: Write the failing service tests**

Add tests to `backend/tests/test_pgvector_service.py` for:

```python
class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict]:
        return self.rows


def test_pgvector_service_builds_bm25_query_against_dynamic_text_table() -> None:
    service, engine = build_service()
    engine.connection.result = FakeResult([])

    service.search_text_bm25_chunks(
        user_id="u-1",
        query_text="claim policy",
        top_k=5,
    )

    sql = engine.connection.calls[0][0]
    assert "FROM uploaded_file_text_vector AS vectors" in sql
    assert "pdb.score(vectors.id) AS bm25_score" in sql
    assert "vectors.file_name ||| :query::pdb.boost(2)" in sql
    assert "JOIN uploaded_file AS uf ON uf.id = vectors.file_id" in sql
    assert "uf.user_id = :user_id" in sql
    assert "uf.text_vector_status = 'VECTORIZED'" in sql


def test_pgvector_service_builds_file_name_rule_query() -> None:
    service, engine = build_service()
    engine.connection.result = FakeResult([])

    service.search_rule_candidate_chunks(
        user_id="u-1",
        file_name_tokens=["claim"],
        per_file_limit=2,
        top_k=6,
    )

    sql = engine.connection.calls[0][0]
    assert "LOWER(uf.file_name) LIKE" in sql
    assert "ROW_NUMBER() OVER (PARTITION BY vectors.file_id ORDER BY vectors.small_chunk_index ASC)" in sql
    assert "uf.created_at AS created_at" in sql
    assert "ORDER BY uf.created_at DESC, uf.id DESC, vectors.small_chunk_index ASC" in sql
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_pgvector_service.py -v`
Expected: FAIL because BM25 and rule helper methods do not exist yet.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/pgvector_service.py`, add:

```python
def search_text_bm25_chunks(self, *, user_id: str, query_text: str, top_k: int) -> list[dict]:
    ...


def search_rule_candidate_chunks(
    self,
    *,
    user_id: str,
    file_name_tokens: list[str],
    per_file_limit: int,
    top_k: int,
) -> list[dict]:
    ...
```

Requirements:
- Use `self.settings.pgvector_text_table` for SQL table names.
- Join `uploaded_file` for `user_id` and `text_vector_status`.
- Return `file_id`, `file_name`, `mime_type`, `created_at`, `small_chunk_text`, `page_start`, `page_end`, `small_chunk_index`, and the route-specific score field.
- Keep existing vector search behavior unchanged.
- Add assertions in the new tests that BM25 and rule SQL both include `uf.text_vector_status = 'VECTORIZED'`.
- Update the fake DB helpers in `backend/tests/test_pgvector_service.py` so query methods can safely call `result.mappings().all()`.
- Keep BM25 semantics aligned with the spec: `file_name` must be boosted relative to `small_chunk_text`, and ordering must stay `pdb.score(...) DESC, uf.id DESC, vectors.small_chunk_index ASC`.
- In BM25 and rule queries, return `uf.created_at AS created_at`; do not use the chunk table `created_at` for recent bonus or tie-break logic.
- Implement rule candidate SQL with a window-function per-file cap, for example `row_number() over (partition by vectors.file_id order by vectors.small_chunk_index asc)`, then filter rows where `row_number <= :per_file_limit`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_pgvector_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pgvector_service.py backend/tests/test_pgvector_service.py
git commit -m "feat: add bm25 and rule retrieval sql helpers"
```

### Task 4: Query Analysis And Candidate Scoring Primitives

**Files:**
- Modify: `backend/app/ai/services/ai_rag_service.py`
- Modify: `backend/tests/test_ai_rag_service.py`

- [ ] **Step 1: Write the failing query-analysis tests**

Add tests like:

```python
def test_analyze_query_detects_recent_and_pdf_flags() -> None:
    service = AIRagService(settings=build_settings(), embedding_service=FakeEmbeddingService([]), pgvector_service=FakePgVectorService([]))

    features = service._analyze_query("帮我找最近上传的pdf资料")

    assert features.wants_recent is True
    assert features.wants_pdf is True
    assert "pdf" in features.requested_file_types


def test_normalize_bm25_scores_handles_equal_values() -> None:
    service = AIRagService(settings=build_settings(), embedding_service=FakeEmbeddingService([]), pgvector_service=FakePgVectorService([]))

    scores = service._normalize_bm25_scores([5.0, 5.0])

    assert scores == [0.0, 0.0]


def test_normalize_bm25_scores_single_candidate_becomes_one() -> None:
    service = AIRagService(settings=build_settings(), embedding_service=FakeEmbeddingService([]), pgvector_service=FakePgVectorService([]))

    scores = service._normalize_bm25_scores([3.2])

    assert scores == [1.0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_ai_rag_service.py -v`
Expected: FAIL because query analysis and BM25 normalization helpers do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add internal dataclasses/helpers in `backend/app/ai/services/ai_rag_service.py`:

```python
@dataclass(slots=True)
class QueryFeatures:
    normalized_query: str
    keywords: list[str]
    identifier_tokens: list[str]
    wants_recent: bool
    requested_file_types: set[str]
    wants_image: bool
    wants_pdf: bool
    wants_document: bool
```

Also add helper methods for:
- Lowercase token extraction
- Recent/type flag detection
- BM25 min-max normalization
- Stable sort tie-break fields

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_ai_rag_service.py -v`
Expected: PASS for the new helper tests and no regression in existing tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/services/ai_rag_service.py backend/tests/test_ai_rag_service.py
git commit -m "feat: add retrieval query analysis helpers"
```

### Task 5: Multi-Retrieval Candidate Merge, Rule Bonuses, And Response Mapping

**Files:**
- Modify: `backend/app/ai/services/ai_rag_service.py`
- Modify: `backend/tests/test_ai_rag_service.py`

- [ ] **Step 1: Write the failing orchestration tests**

Add tests to `backend/tests/test_ai_rag_service.py` like:

```python
def test_rag_service_merges_vector_bm25_and_rule_hits_by_file_id_and_chunk_index() -> None:
    pgvector_service = FakePgVectorService(
        vector_rows=[
            {
                "file_id": 11,
                "file_name": "claim-policy.pdf",
                "mime_type": "application/pdf",
                "created_at": datetime(2026, 3, 31, 9, 0, tzinfo=timezone.utc),
                "small_chunk_text": "claim policy section",
                "page_start": 1,
                "page_end": 1,
                "small_chunk_index": 0,
                "distance": 0.10,
            }
        ],
        bm25_rows=[
            {
                "file_id": 11,
                "file_name": "claim-policy.pdf",
                "mime_type": "application/pdf",
                "created_at": datetime(2026, 3, 31, 9, 0, tzinfo=timezone.utc),
                "small_chunk_text": "claim policy section",
                "page_start": 1,
                "page_end": 1,
                "small_chunk_index": 0,
                "bm25_score": 7.5,
            },
            {
                "file_id": 22,
                "file_name": "recent-manual.pdf",
                "mime_type": "application/pdf",
                "created_at": datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
                "small_chunk_text": "recent pdf appendix",
                "page_start": 3,
                "page_end": 3,
                "small_chunk_index": 4,
                "bm25_score": 4.1,
            },
        ],
        rule_rows=[
            {
                "file_id": 22,
                "file_name": "recent-manual.pdf",
                "mime_type": "application/pdf",
                "created_at": datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
                "small_chunk_text": "recent pdf appendix",
                "page_start": 3,
                "page_end": 3,
                "small_chunk_index": 4,
            }
        ],
    )
    service = AIRagService(
        settings=build_settings(assistant_enable_bm25=True, assistant_enable_rule_retrieval=True),
        embedding_service=FakeEmbeddingService([[0.2, 0.8]]),
        pgvector_service=pgvector_service,
    )

    response = service.retrieve(query="claim policy pdf", user_id="u-1")

    assert [snippet.text for snippet in response.snippets] == [
        "claim policy section",
        "recent pdf appendix",
    ]
    assert [file.upload_id for file in response.related_files] == [11, 22]


def test_rag_service_degrades_when_bm25_route_raises() -> None:
    pgvector_service = FakePgVectorService(
        vector_rows=[
            {
                "file_id": 11,
                "file_name": "claim-policy.pdf",
                "mime_type": "application/pdf",
                "created_at": datetime(2026, 3, 31, 9, 0, tzinfo=timezone.utc),
                "small_chunk_text": "claim policy section",
                "page_start": 1,
                "page_end": 1,
                "small_chunk_index": 0,
                "distance": 0.10,
            }
        ],
        bm25_error=RuntimeError("bm25 unavailable"),
        rule_rows=[],
    )

    service = AIRagService(
        settings=build_settings(assistant_enable_bm25=True, assistant_enable_rule_retrieval=True),
        embedding_service=FakeEmbeddingService([[0.2, 0.8]]),
        pgvector_service=pgvector_service,
    )

    response = service.retrieve(query="claim policy", user_id="u-1")

    assert [snippet.text for snippet in response.snippets] == ["claim policy section"]


def test_rag_service_uses_explicit_top_k_as_final_snippet_limit_only() -> None:
    settings = build_settings(
        assistant_enable_bm25=True,
        assistant_enable_rule_retrieval=True,
        assistant_retrieval_top_k=6,
        assistant_vector_retrieval_top_k=9,
        assistant_bm25_retrieval_top_k=8,
        assistant_rule_retrieval_top_k=4,
    )
    pgvector_service = FakePgVectorService(
        vector_rows=[
            {
                "file_id": 11,
                "file_name": "claim-policy.pdf",
                "mime_type": "application/pdf",
                "created_at": datetime(2026, 3, 31, 9, 0, tzinfo=timezone.utc),
                "small_chunk_text": "claim policy section",
                "page_start": 1,
                "page_end": 1,
                "small_chunk_index": 0,
                "distance": 0.10,
            },
            {
                "file_id": 22,
                "file_name": "recent-manual.pdf",
                "mime_type": "application/pdf",
                "created_at": datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
                "small_chunk_text": "recent pdf appendix",
                "page_start": 3,
                "page_end": 3,
                "small_chunk_index": 4,
                "distance": 0.20,
            },
            {
                "file_id": 33,
                "file_name": "other-guide.pdf",
                "mime_type": "application/pdf",
                "created_at": datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc),
                "small_chunk_text": "other guide",
                "page_start": 5,
                "page_end": 5,
                "small_chunk_index": 2,
                "distance": 0.30,
            },
        ],
        bm25_rows=[],
        rule_rows=[],
    )
    service = AIRagService(
        settings=settings,
        embedding_service=FakeEmbeddingService([[0.2, 0.8]]),
        pgvector_service=pgvector_service,
    )

    response = service.retrieve(query="find material", user_id="u-1", top_k=2)

    assert len(response.snippets) == 2
    assert pgvector_service.vector_calls[0]["top_k"] == settings.assistant_vector_retrieval_top_k
    assert pgvector_service.bm25_calls[0]["top_k"] == settings.assistant_bm25_retrieval_top_k
    assert pgvector_service.rule_calls[0]["top_k"] == settings.assistant_rule_retrieval_top_k
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_ai_rag_service.py -v`
Expected: FAIL because `retrieve()` is still single-route and the fake service does not support multi-route calls.

- [ ] **Step 3: Write minimal implementation**

Refactor `backend/app/ai/services/ai_rag_service.py` so `retrieve()` does this:

```python
features = self._analyze_query(query)
vector_candidates = self._retrieve_vector_candidates(...)
bm25_candidates = self._retrieve_bm25_candidates(...)
rule_candidates = self._retrieve_rule_candidates(...)
merged = self._merge_candidates(vector_candidates, bm25_candidates, rule_candidates)
ranked = self._rerank_candidates(merged, features)
return self._build_response_from_candidates(ranked, final_top_k=top_k or self.settings.assistant_retrieval_top_k)
```

Requirements:
- Internal dedupe key is `(file_id, small_chunk_index)`.
- Outbound `upload_id` remains derived from `file_id`.
- `hit_reasons` stay internal only.
- Keep the empty-response behavior unchanged.
- If BM25 is disabled, skip that branch cleanly.
- If rule retrieval is disabled, skip that branch cleanly.
- Apply and cap the configured bonuses: file-name exact match, term-hit, recent-window, and type-match.
- Implement a total bonus upper bound so rule bonuses cannot dominate the final score.
- Catch BM25/rule route errors, log them, and continue with empty results for that route; keep vector embedding/query failures as hard failures.
- Use `uploaded_file.created_at` for recent bonus calculation, stable tie-break ordering, and `related_files` aggregation.
- Cap total bonus explicitly with `min(total_bonus, 0.25)` and add a unit test so bonuses cannot reorder clearly worse base candidates by themselves.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_ai_rag_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/services/ai_rag_service.py backend/tests/test_ai_rag_service.py
git commit -m "feat: add multi-route rag retrieval"
```

### Task 6: Startup Wiring, SQL Execution, And Backend Regression

**Files:**
- Modify: `docs/deploy.md`
- Modify: `backend/.env.example`

- [ ] **Step 1: Write the failing deployment note update**

Add a short checklist section to `docs/deploy.md` and an example toggle block to `backend/.env.example` covering:

```dotenv
ASSISTANT_ENABLE_BM25=true
ASSISTANT_ENABLE_RULE_RETRIEVAL=true
ASSISTANT_VECTOR_RETRIEVAL_TOP_K=18
ASSISTANT_BM25_RETRIEVAL_TOP_K=18
ASSISTANT_RULE_RETRIEVAL_TOP_K=12
```

Also add a deployment note that `backend/sql/003_add_pg_search_bm25.sql` must be executed outside a transaction.

- [ ] **Step 2: Run targeted tests before SQL execution**

Run: `cd backend && pytest tests/test_ai_config.py tests/test_database_schema.py tests/test_pgvector_service.py tests/test_ai_rag_service.py tests/test_langgraph_assistant.py -v`
Expected: PASS

- [ ] **Step 3: Execute the BM25 SQL and verify database readiness**

Run these commands in order:

```bash
cd backend
python - <<'PY'
from app.core.config import get_settings
print(get_settings().postgres_database_url)
PY
```

Use the printed DSN to execute:

```bash
psql "<POSTGRES_DSN>" -c "SELECT extversion FROM pg_extension WHERE extname = 'pg_search';"
psql "<POSTGRES_DSN>" -v pgvector_text_table="<REAL_TABLE_NAME_FROM_SETTINGS>" -f sql/003_add_pg_search_bm25.sql
psql "<POSTGRES_DSN>" -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_search';"
psql "<POSTGRES_DSN>" -c "SELECT indexname FROM pg_indexes WHERE indexname = 'idx_<REAL_TABLE_NAME_FROM_SETTINGS>_bm25';"
```

Expected:
- the first query prints the installed `pg_search` version, and the implementation locks to that version's syntax
- the SQL file applies without transaction errors
- `pg_search` appears in `pg_extension`
- `idx_<REAL_TABLE_NAME_FROM_SETTINGS>_bm25` appears in `pg_indexes`

If index creation fails, recover with:

```bash
psql "<POSTGRES_DSN>" -c "DROP INDEX CONCURRENTLY IF EXISTS idx_<REAL_TABLE_NAME_FROM_SETTINGS>_bm25;"
```

- [ ] **Step 4: Run final backend regression**

Run: `cd backend && pytest tests/test_ai_config.py tests/test_database_schema.py tests/test_pgvector_service.py tests/test_ai_rag_service.py tests/test_langgraph_assistant.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/deploy.md backend/.env.example
git commit -m "docs: add pg_search rollout checklist"
```
