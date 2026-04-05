# AI Assistant RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-stage AI assistant in the workbench: a left-top AI entry opens a full-height floating panel that classifies intent and supports user-scoped RAG retrieval with related download links.

**Architecture:** The frontend adds a dedicated AI assistant panel mounted from the header and managed by `CanvasPage`. The backend adds a FastAPI AI route backed by a minimal LangGraph workflow that classifies intent, performs PostgreSQL/pgvector retrieval for the current user, synthesizes an answer when a generation model is configured, and returns a stable structured payload. Download links are served through an authenticated redirect endpoint on the existing uploads route.

**Tech Stack:** Vue 3, Ant Design Vue, Vitest, FastAPI, SQLAlchemy, PostgreSQL + pgvector, LangGraph, pytest

---

### Task 1: Backend Dependency And Config Foundation

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_ai_config.py`

- [ ] **Step 1: Write the failing config test**

```python
from app.core.config import Settings


def test_ai_assistant_settings_have_safe_defaults():
    settings = Settings(
        postgres_database_url="postgresql://demo:demo@localhost:5432/demo",
        oss_region="cn-test",
        oss_bucket="bucket",
        oss_endpoint="oss-cn-test.aliyuncs.com",
        oss_access_key_id="key",
        oss_access_key_secret="secret",
        oss_public_base_url="https://example.com",
    )

    assert settings.assistant_retrieval_top_k == 6
    assert settings.assistant_max_context_blocks == 4
    assert settings.assistant_max_related_files == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ai_config.py -v`
Expected: FAIL because assistant settings are not defined yet.

- [ ] **Step 3: Write minimal implementation**

Add `langgraph` to `backend/requirements.txt`, then add these settings to `backend/app/core/config.py`:

```python
assistant_retrieval_top_k: int = 6
assistant_max_context_blocks: int = 4
assistant_max_related_files: int = 5
assistant_llm_base_url: str | None = None
assistant_llm_api_key: str | None = None
assistant_llm_model: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ai_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/app/core/config.py backend/tests/test_ai_config.py
git commit -m "feat: add ai assistant backend config"
```

### Task 2: AI Backend Schemas And Intent Rules

**Files:**
- Create: `backend/app/schemas/ai.py`
- Create: `backend/tests/test_ai_schemas.py`
- Create: `backend/tests/test_ai_intent.py`
- Create: `backend/app/services/langgraph_assistant.py`

- [ ] **Step 1: Write the failing schema and intent tests**

```python
from app.services.langgraph_assistant import classify_intent


def test_classify_intent_defaults_to_rag():
    assert classify_intent("理赔审核环节要求是什么") == "rag_retrieval"


def test_classify_intent_detects_generate_xml():
    assert classify_intent("请帮我生成xml") == "generate_xml"
```

```python
from app.schemas.ai import AiAssistantQueryResponse


def test_ai_response_schema_allows_empty_rag_result():
    payload = AiAssistantQueryResponse(
        intent="rag_retrieval",
        message="未检索到相关资料。",
        answer="",
        snippets=[],
        related_files=[],
    )

    assert payload.intent == "rag_retrieval"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_ai_schemas.py tests/test_ai_intent.py -v`
Expected: FAIL because AI schemas and helper are missing.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/schemas/ai.py` with:

```python
class AiSnippetResponse(BaseModel):
    upload_id: int
    file_name: str
    text: str
    page_start: int | None = None
    page_end: int | None = None
    small_chunk_index: int
    score: float


class AiRelatedFileResponse(BaseModel):
    upload_id: int
    file_name: str
    mime_type: str
    created_at: datetime
    download_url: str


class AiAssistantQueryRequest(BaseModel):
    query: str


class AiAssistantQueryResponse(BaseModel):
    intent: Literal["rag_retrieval", "generate_xml"]
    message: str | None = None
    answer: str = ""
    snippets: list[AiSnippetResponse] = Field(default_factory=list)
    related_files: list[AiRelatedFileResponse] = Field(default_factory=list)
```

Create `backend/app/services/langgraph_assistant.py` with a pure-rule `classify_intent(query: str) -> str`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_ai_schemas.py tests/test_ai_intent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/ai.py backend/app/services/langgraph_assistant.py backend/tests/test_ai_schemas.py backend/tests/test_ai_intent.py
git commit -m "feat: add ai assistant schemas and intent rules"
```

### Task 3: Pgvector Retrieval Service

**Files:**
- Create: `backend/app/services/ai_rag_service.py`
- Create: `backend/tests/test_ai_rag_service.py`
- Modify: `backend/app/services/pgvector_service.py`

- [ ] **Step 1: Write the failing retrieval tests**

```python
def test_similarity_score_uses_one_minus_cosine_distance():
    assert build_similarity_score(0.12) == 0.88


def test_similarity_score_is_clamped_to_zero_one():
    assert build_similarity_score(-0.2) == 1.0
    assert build_similarity_score(1.4) == 0.0
```

```python
def test_map_rows_to_snippets_uses_small_chunk_text():
    rows = [{
        "upload_id": 7,
        "file_name": "a.docx",
        "small_chunk_text": "short text",
        "large_chunk_text": "long text",
        "page_start": None,
        "page_end": None,
        "small_chunk_index": 2,
        "distance": 0.2,
        "mime_type": "application/docx",
        "created_at": now,
    }]

    result = service._build_result(rows)

    assert result.snippets[0].text == "short text"
    assert result.related_files[0].upload_id == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_ai_rag_service.py -v`
Expected: FAIL because retrieval service does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement `backend/app/services/ai_rag_service.py` with:

```python
def build_similarity_score(distance: float) -> float:
    return max(0.0, min(1.0, round(1 - distance, 6)))
```

```python
class AiRagService:
    def retrieve(self, *, query: str, user_id: str) -> AiAssistantQueryResponse:
        query_vector = self.embedding_service.embed_texts([query])[0]
        rows = self.pgvector_service.search_text_chunks(
            query_vector=query_vector,
            user_id=user_id,
            top_k=self.settings.assistant_retrieval_top_k,
        )
        ...
```

Add a new method to `backend/app/services/pgvector_service.py`:

```python
def search_text_chunks(self, *, query_vector: list[float], user_id: str, top_k: int) -> list[dict]:
    ...
```

The SQL must:
- join `uploaded_file_text_vector` with `uploaded_file`
- filter by `uploaded_file.user_id`
- filter by `uploaded_file.text_vector_status = 'VECTORIZED'`
- order by cosine distance ascending
- return `small_chunk_text`, `large_chunk_text`, `page_start`, `page_end`, `small_chunk_index`, file metadata, and raw distance

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_ai_rag_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ai_rag_service.py backend/app/services/pgvector_service.py backend/tests/test_ai_rag_service.py
git commit -m "feat: add ai rag retrieval service"
```

### Task 4: Answer Synthesis And LangGraph Workflow

**Files:**
- Modify: `backend/app/services/langgraph_assistant.py`
- Create: `backend/tests/test_langgraph_assistant.py`

- [ ] **Step 1: Write the failing workflow tests**

```python
def test_generate_xml_intent_short_circuits_to_placeholder():
    response = workflow.invoke({"query": "生成xml", "user_id": "u1"})
    assert response["intent"] == "generate_xml"
    assert response["message"] == "XML 生成功能将在下一阶段开放。"
```

```python
def test_rag_intent_degrades_when_summary_model_missing():
    response = workflow.invoke({"query": "理赔流程", "user_id": "u1"})
    assert response["intent"] == "rag_retrieval"
    assert response["answer"] == ""
    assert "摘要生成能力未配置" in response["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_langgraph_assistant.py -v`
Expected: FAIL because the graph workflow is incomplete.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/langgraph_assistant.py`:

```python
class LangGraphAssistantService:
    def build_graph(self):
        graph = StateGraph(AiAssistantState)
        graph.add_node("classify_intent", self.classify_intent_node)
        graph.add_node("retrieve_documents", self.retrieve_documents_node)
        graph.add_node("synthesize_answer", self.synthesize_answer_node)
        graph.add_node("build_response", self.build_response_node)
        ...
```

Rules:
- `generate_xml` goes straight from `classify_intent` to `build_response`
- `rag_retrieval` goes through retrieve + synthesize
- if summary model config is absent, keep snippets and related files, set `answer=""`, and set the configured degrade message
- implement summary generation with the `openai` package already present in `backend/requirements.txt`
- create a tiny helper in the same file, for example `generate_summary(context_blocks: list[str], query: str) -> str`
- initialize `OpenAI(base_url=settings.assistant_llm_base_url, api_key=settings.assistant_llm_api_key)` only when all three assistant LLM settings are present
- call `client.chat.completions.create(...)` with `model=settings.assistant_llm_model`
- build the prompt from the query plus deduplicated `large_chunk_text` blocks, capped by `assistant_max_context_blocks`
- if the call fails, catch the exception and return the degrade response defined by the spec instead of failing the whole request

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_langgraph_assistant.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/langgraph_assistant.py backend/tests/test_langgraph_assistant.py
git commit -m "feat: add ai assistant langgraph workflow"
```

### Task 5: AI API Route

**Files:**
- Create: `backend/app/api/routes/ai.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_ai_route.py`

- [ ] **Step 1: Write the failing route tests**

```python
def test_ai_query_requires_auth(client):
    response = client.post("/api/ai/assistant/query", json={"query": "理赔流程"})
    assert response.status_code == 401
```

```python
def test_ai_query_returns_structured_payload(authenticated_client):
    response = authenticated_client.post("/api/ai/assistant/query", json={"query": "理赔流程"})
    assert response.status_code == 200
    payload = response.json()
    assert "intent" in payload
    assert "snippets" in payload
    assert "related_files" in payload
```

```python
def test_ai_query_returns_retrieval_error_payload(authenticated_client):
    response = authenticated_client.post("/api/ai/assistant/query", json={"query": "理赔流程"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AI_RETRIEVAL_FAILED"
```
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_ai_route.py -v`
Expected: FAIL because the route is not registered.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/api/routes/ai.py` with:

```python
router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/assistant/query", response_model=AiAssistantQueryResponse)
def query_ai_assistant(...):
    ...
```

Route behavior:
- require auth via `get_current_user`
- map request body to service call
- raise `HTTPException(status_code=503, detail={"code": "AI_RETRIEVAL_FAILED", "message": ...})` for missing embedding config or invalid pgvector operator
- raise `HTTPException(status_code=500, detail={"code": "AI_RETRIEVAL_FAILED", "message": ...})` for retrieval execution failure

Register the router in `backend/app/main.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_ai_route.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/ai.py backend/app/main.py backend/tests/test_ai_route.py
git commit -m "feat: add ai assistant api route"
```

### Task 6: Upload Download Redirect Endpoint

**Files:**
- Modify: `backend/app/api/routes/uploads.py`
- Modify: `backend/app/services/upload_service.py`
- Create: `backend/tests/test_upload_download_route.py`

- [ ] **Step 1: Write the failing download tests**

```python
def test_download_requires_file_ownership(authenticated_client):
    response = authenticated_client.get("/api/uploads/12/download")
    assert response.status_code in {403, 404}
```

```python
def test_download_redirects_to_public_url_for_owner(authenticated_client, seeded_upload):
    response = authenticated_client.get(f"/api/uploads/{seeded_upload.id}/download", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == seeded_upload.public_url
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_upload_download_route.py -v`
Expected: FAIL because the download endpoint does not exist.

- [ ] **Step 3: Write minimal implementation**

Add an authenticated download method to `UploadService`, for example:

```python
def get_download_url(self, upload_id: int, user_id: str) -> str:
    record = self._require_owned_file(upload_id, user_id)
    return record.public_url
```

Expose it from `backend/app/api/routes/uploads.py` as a `302` redirect response.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_upload_download_route.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/uploads.py backend/app/services/upload_service.py backend/tests/test_upload_download_route.py
git commit -m "feat: add upload download redirect"
```

### Task 7: Frontend AI Types And API Client

**Files:**
- Create: `src/types/ai.ts`
- Create: `src/lib/ai.ts`
- Create: `src/lib/ai.test.ts`

- [ ] **Step 1: Write the failing frontend API tests**

```ts
it('posts ai assistant queries to the backend', async () => {
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({
      intent: 'rag_retrieval',
      message: null,
      answer: 'demo',
      snippets: [],
      related_files: []
    }), { status: 200 })
  );

  await queryAiAssistant('理赔流程');

  expect(fetchSpy.mock.calls[0]?.[0]).toBe('/api/ai/assistant/query');
});
```

```ts
it('throws backend error messages from structured ai failures', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({
      detail: { code: 'AI_RETRIEVAL_FAILED', message: '检索失败，请稍后重试。' }
    }), { status: 500 })
  );

  await expect(queryAiAssistant('理赔流程')).rejects.toThrow('检索失败，请稍后重试。');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- src/lib/ai.test.ts`
Expected: FAIL because the AI client does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/types/ai.ts` with frontend interfaces matching the backend snake_case response. Create `src/lib/ai.ts` with:

```ts
export async function queryAiAssistant(query: string): Promise<AiAssistantQueryResponse> {
  const response = await apiFetch('/api/ai/assistant/query', {
    method: 'POST',
    body: JSON.stringify({ query })
  });
  ...
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- src/lib/ai.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/types/ai.ts src/lib/ai.ts src/lib/ai.test.ts
git commit -m "feat: add ai assistant frontend client"
```

### Task 8: AI Assistant Panel UI

**Files:**
- Create: `src/components/AiAssistantPopover.vue`
- Modify: `src/components/AppHeader.vue`
- Modify: `src/pages/CanvasPage.vue`
- Modify: `src/styles/workbench.css`
- Create: `src/components/AiAssistantPopover.test.ts`

- [ ] **Step 1: Write the failing UI tests**

```ts
it('opens the ai panel from the header button', async () => {
  render(CanvasPage);
  await user.click(screen.getByRole('button', { name: /ai/i }));
  expect(screen.getByText('AI 助手')).toBeInTheDocument();
});
```

```ts
it('renders rag results including snippets and related files', async () => {
  render(AiAssistantPopover, { props: { open: true, result: demoResult } });
  expect(screen.getByText('摘要答案')).toBeInTheDocument();
  expect(screen.getByText('命中的文本片段')).toBeInTheDocument();
  expect(screen.getByText('相关文件')).toBeInTheDocument();
});
```

```ts
it('shows generate xml placeholder message', async () => {
  render(AiAssistantPopover, { props: { open: true, result: xmlPlaceholderResult } });
  expect(screen.getByText('XML 生成功能将在下一阶段开放。')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- src/components/AiAssistantPopover.test.ts`
Expected: FAIL because the component and header integration do not exist.

- [ ] **Step 3: Write minimal implementation**

Implement `src/components/AiAssistantPopover.vue` with:
- fixed header section
- textarea or input for `query`
- submit button
- loading, empty, error, and result states
- result cards for summary, snippets, and related files

Update `src/components/AppHeader.vue`:
- add a left-top AI icon button near the brand block
- emit `toggle-ai-assistant`

Update `src/pages/CanvasPage.vue`:
- manage `aiPopoverOpen`, `aiQuery`, `aiSubmitting`, `aiResult`, `aiError`
- wire submit handler to `queryAiAssistant`

Update `src/styles/workbench.css`:
- width `420px`
- full available height under the header
- result area scrolls independently
- z-index above header/canvas, below modal confirm overlays

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- src/components/AiAssistantPopover.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/components/AiAssistantPopover.vue src/components/AppHeader.vue src/pages/CanvasPage.vue src/styles/workbench.css src/components/AiAssistantPopover.test.ts
git commit -m "feat: add ai assistant panel ui"
```

### Task 9: End-To-End Verification

**Files:**
- Modify: `docs/superpowers/plans/2026-03-30-ai-assistant-rag.md`

- [ ] **Step 1: Run focused backend tests**

Run: `cd backend && pytest tests/test_ai_config.py tests/test_ai_schemas.py tests/test_ai_intent.py tests/test_ai_rag_service.py tests/test_langgraph_assistant.py tests/test_ai_route.py tests/test_upload_download_route.py -v`
Expected: PASS

- [ ] **Step 2: Run focused frontend tests**

Run: `npm test -- src/lib/ai.test.ts src/components/AiAssistantPopover.test.ts`
Expected: PASS

- [ ] **Step 3: Run broader safety checks**

Run: `npm test`
Expected: PASS with existing frontend tests still green

Run: `cd backend && pytest -v`
Expected: PASS or, if unrelated legacy failures exist, capture them explicitly before completion

- [ ] **Step 4: Update plan checklist state**

Mark completed steps in this plan file as work finishes. If any command fails due to pre-existing issues, record the exact blocker next to the relevant step before proceeding.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-03-30-ai-assistant-rag.md
git commit -m "docs: finalize ai assistant rag implementation plan"
```
