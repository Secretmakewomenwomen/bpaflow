# AI Assistant Flow Chart File Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a human-in-the-loop AI assistant flow that interrupts for single-file selection, resumes with one `uploadId`, generates chapter flow JSON, and lets the frontend import or reselect the file.

**Architecture:** Keep the assistant as the primary orchestrator. Use a deterministic backend pipeline for file-to-flow generation after the user confirms a single file, and persist structured assistant message payloads so the frontend can render pending actions and completed artifacts. On the frontend, extend the existing AI popover to show a single-select file dialog and convert the returned `graphPayload` into the current canvas snapshot format for import.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, LangGraph/OpenAI chat completions, Vue 3, TypeScript, Vitest

---

## File Structure

**Backend**
- Modify: `backend/app/models/ai.py`
  Add structured payload persistence on AI assistant messages.
- Modify: `backend/app/core/database.py`
  Add startup schema guard for new AI message payload columns.
- Modify: `backend/app/schemas/ai.py`
  Add pending action, artifact, action button, and richer message status schema.
- Modify: `backend/app/ai/services/ai_conversation_service.py`
  Persist and restore assistant message payload JSON.
- Create: `backend/app/ai/services/flow_chart_interrupt_service.py`
  Encapsulate candidate-file lookup and chapter-flow artifact generation.
- Modify: `backend/app/ai/services/langgraph_assistant.py`
  Detect `generate_flow_from_file`, return `waiting_input`, and resume generation after user confirmation.
- Modify: `backend/app/api/routes/ai.py`
  Add a resume endpoint and wire the richer assistant response flow.
- Test: `backend/tests/test_ai_schemas.py`
- Test: `backend/tests/test_ai_route.py`
- Test: `backend/tests/test_langgraph_assistant.py`
- Test: `backend/tests/test_database_schema.py`
- Test: `backend/tests/test_ai_conversation_service.py` (create if missing)

**Frontend**
- Modify: `src/types/ai.ts`
  Add pending action, artifact, action button, and resume request/response types.
- Modify: `src/lib/ai.ts`
  Parse richer SSE payloads and add the resume API call.
- Create: `src/lib/chapter-flow-import.ts`
  Convert assistant `graphPayload` into `CanvasSnapshotPayload`.
- Test: `src/lib/chapter-flow-import.test.ts`
- Modify: `src/components/AiAssistantPopover.vue`
  Show file picker interrupt, render `导入`/`重新选择文件`, and emit import actions upward.
- Modify: `src/components/AiAssistantPopover.test.ts`
- Modify: `src/pages/CanvasPage.vue`
  Receive imported snapshot from AI popover and load it into the current canvas.
- Modify: `src/pages/CanvasPage.test.ts`

## Task 1: Persist Rich Assistant Message Payloads

**Files:**
- Modify: `backend/app/models/ai.py`
- Modify: `backend/app/core/database.py`
- Modify: `backend/app/schemas/ai.py`
- Modify: `backend/app/ai/services/ai_conversation_service.py`
- Test: `backend/tests/test_ai_schemas.py`
- Test: `backend/tests/test_database_schema.py`
- Test: `backend/tests/test_ai_conversation_service.py`

- [ ] **Step 1: Write the failing schema and persistence tests**

```python
def test_conversation_message_supports_pending_action_and_artifact() -> None:
    message = ConversationMessageResponse.model_validate(
        {
            "message_id": "msg-1",
            "role": "assistant",
            "intent": "general_chat",
            "content": "请选择文件。",
            "status": "waiting_input",
            "pending_action": {
                "action_id": "action-1",
                "action_type": "select_file",
                "payload": {
                    "selection_mode": "single",
                    "candidates": [{"upload_id": 101, "file_name": "手册.docx"}],
                },
            },
            "artifact": None,
            "actions": [],
            "created_at": "2026-04-02T00:00:00Z",
            "references": [],
        }
    )
    assert message.pending_action is not None
```

```python
def test_create_assistant_message_persists_payload_json() -> None:
    response = AssistantResponse(
        answer="请选择文件。",
        status="waiting_input",
        pending_action=AssistantPendingAction(...),
    )
    saved = service.create_assistant_message(...)
    assert saved.pending_action.action_type == "select_file"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
pytest tests/test_ai_schemas.py tests/test_database_schema.py tests/test_ai_conversation_service.py -q
```

Expected: FAIL because `ConversationMessageResponse` and `AiMessage` do not yet support assistant payload JSON.

- [ ] **Step 3: Add the minimal persistence model**

Implement:
- `AiMessage.payload_json: Text | nullable`
- `ensure_ai_message_schema(...)` in `backend/app/core/database.py`
- new Pydantic models in `backend/app/schemas/ai.py`:
  - `AssistantPendingActionCandidate`
  - `AssistantPendingAction`
  - `AssistantArtifact`
  - `AssistantActionButton`
- extend:
  - `AssistantResponse`
  - `ConversationMessageResponse`
- in `AiConversationService`, serialize/deserialize payload JSON alongside existing `content` and `references`.

Minimal model sketch:

```python
class AssistantPendingAction(BaseModel):
    action_id: str
    action_type: Literal["select_file"]
    payload: dict[str, Any]


class AssistantResponse(BaseModel):
    intent: Intent | None = None
    status: Literal["completed", "waiting_input", "processing", "failed"] = "completed"
    answer: str
    pending_action: AssistantPendingAction | None = None
    artifact: dict[str, Any] | None = None
    actions: list[dict[str, str]] = Field(default_factory=list)
```

- [ ] **Step 4: Run the tests again to verify they pass**

Run:

```bash
pytest tests/test_ai_schemas.py tests/test_database_schema.py tests/test_ai_conversation_service.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/ai.py backend/app/core/database.py backend/app/schemas/ai.py backend/app/ai/services/ai_conversation_service.py backend/tests/test_ai_schemas.py backend/tests/test_database_schema.py backend/tests/test_ai_conversation_service.py
git commit -m "feat: persist assistant pending actions and artifacts"
```

## Task 2: Add Backend Flow-Chart Interrupt Orchestration

**Files:**
- Create: `backend/app/ai/services/flow_chart_interrupt_service.py`
- Modify: `backend/app/ai/services/langgraph_assistant.py`
- Test: `backend/tests/test_langgraph_assistant.py`

- [ ] **Step 1: Write the failing orchestration tests**

```python
def test_run_agent_loop_returns_waiting_input_when_flow_chart_file_candidates_found() -> None:
    result = service.run_agent_loop(
        query="根据保险产品设计与销售流程手册生成流程图",
        history_messages=[],
        user_id="user-a",
    )
    assert result["status"] == "waiting_input"
    assert result["pending_action"]["action_type"] == "select_file"
    assert result["pending_action"]["payload"]["selection_mode"] == "single"
```

```python
def test_resume_flow_chart_generation_returns_artifact_for_single_upload() -> None:
    result = service.resume_flow_chart_generation(
        conversation_id="conv-1",
        user_id="user-a",
        action_id="action-1",
        upload_id=101,
    )
    assert result["artifact"]["artifact_type"] == "chapter_flow_json"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/test_langgraph_assistant.py -q
```

Expected: FAIL because the assistant does not yet know `generate_flow_from_file` or resume generation.

- [ ] **Step 3: Implement the minimal orchestration service**

Add `backend/app/ai/services/flow_chart_interrupt_service.py` with two responsibilities:
- `find_candidate_files(query, user_id) -> list[dict]`
- `build_artifact(upload_id, user_id) -> dict`

Use:
- `UploadService.list_uploads(...)` for initial candidate set
- simple filename/title matching for first pass
- existing `ChapterFlowService.parse_upload(...)` for artifact generation

Keep `LangGraphAssistantService` thin:
- detect flow-chart prompt before normal tool loop
- return `waiting_input + pending_action`
- expose a dedicated resume method that validates a single `upload_id`

Minimal handler sketch:

```python
if self._is_generate_flow_request(query):
    candidates = self.flow_chart_interrupt_service.find_candidate_files(query=query, user_id=user_id)
    if candidates:
        return {
            "intent": "generate_flow_from_file",
            "status": "waiting_input",
            "pending_action": {...},
            "chat_answer": "我找到了相关文件，请选择一个文件生成流程图。",
        }
```

- [ ] **Step 4: Run the tests again**

Run:

```bash
pytest tests/test_langgraph_assistant.py -q
```

Expected: PASS for the new interrupt and resume behaviors.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/services/flow_chart_interrupt_service.py backend/app/ai/services/langgraph_assistant.py backend/tests/test_langgraph_assistant.py
git commit -m "feat: add flow chart file-selection interrupt flow"
```

## Task 3: Expose AI Resume API and Streaming Message Contract

**Files:**
- Modify: `backend/app/api/routes/ai.py`
- Modify: `backend/app/schemas/ai.py`
- Modify: `backend/app/ai/services/ai_conversation_service.py`
- Test: `backend/tests/test_ai_route.py`

- [ ] **Step 1: Write the failing route tests**

```python
def test_stream_message_can_finish_with_waiting_input_assistant_message() -> None:
    response = client.post(
        "/api/ai/conversations/conv-1/messages/stream",
        json={"query": "根据文件生成流程图"},
    )
    assert response.status_code == 200
    assert "waiting_input" in response.text
    assert "select_file" in response.text
```

```python
def test_resume_message_accepts_single_upload_id() -> None:
    response = client.post(
        "/api/ai/conversations/conv-1/messages/resume",
        json={"actionId": "action-1", "decision": "confirm", "payload": {"uploadId": 101}},
    )
    assert response.status_code == 200
    assert response.json()["artifact"]["artifactType"] == "chapter_flow_json"
```

- [ ] **Step 2: Run the route tests to confirm failure**

Run:

```bash
pytest tests/test_ai_route.py -q
```

Expected: FAIL because the route layer only supports message streaming and has no resume contract.

- [ ] **Step 3: Implement the route contract**

Add:
- `ResumeConversationMessageRequest` to `backend/app/schemas/ai.py`
- `POST /api/ai/conversations/{conversation_id}/messages/resume` in `backend/app/api/routes/ai.py`

Route behavior:
- validate `payload.uploadId` exists
- call assistant resume method
- persist returned assistant message
- return the completed/waiting_input message payload

Minimal request sketch:

```python
class ResumeConversationMessageRequest(BaseModel):
    actionId: str
    decision: Literal["confirm"]
    payload: dict[str, Any]
```

- [ ] **Step 4: Re-run the route tests**

Run:

```bash
pytest tests/test_ai_route.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/ai.py backend/app/schemas/ai.py backend/app/ai/services/ai_conversation_service.py backend/tests/test_ai_route.py
git commit -m "feat: add ai resume endpoint for file selection interrupts"
```

## Task 4: Add Frontend AI Types and Resume API

**Files:**
- Modify: `src/types/ai.ts`
- Modify: `src/lib/ai.ts`
- Test: `src/lib/ai.test.ts`

- [ ] **Step 1: Write the failing frontend protocol tests**

```ts
it('parses assistant messages with pending actions and artifacts', async () => {
  const payload = {
    message_id: 'msg-ai',
    role: 'assistant',
    intent: 'general_chat',
    content: '请选择文件。',
    status: 'waiting_input',
    pending_action: {
      action_id: 'action-1',
      action_type: 'select_file',
      payload: { selection_mode: 'single', candidates: [{ upload_id: 101, file_name: '手册.docx' }] }
    },
    artifact: null,
    actions: [],
    created_at: '2026-04-02T00:00:00Z',
    references: []
  };
  expect(isConversationMessage(payload)).toBe(true);
});
```

```ts
it('posts a single uploadId to the resume endpoint', async () => {
  await resumeAiConversationMessage('conv-1', {
    actionId: 'action-1',
    decision: 'confirm',
    payload: { uploadId: 101 }
  });
  expect(apiFetch).toHaveBeenCalledWith('/api/ai/conversations/conv-1/messages/resume', expect.anything());
});
```

- [ ] **Step 2: Run the frontend AI tests and confirm failure**

Run:

```bash
npm test -- src/lib/ai.test.ts
```

Expected: FAIL because the type guards and API wrapper do not understand pending actions or resume.

- [ ] **Step 3: Implement the minimal protocol changes**

Add types:
- `AiPendingActionCandidate`
- `AiPendingAction`
- `AiAssistantArtifact`
- `AiAssistantActionButton`
- `ResumeAiConversationMessageRequest`

Add API helper:

```ts
export async function resumeAiConversationMessage(
  conversationId: string,
  payload: ResumeAiConversationMessageRequest
): Promise<AiConversationMessage> {
  const response = await apiFetch(`/api/ai/conversations/${conversationId}/messages/resume`, {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  return parseConversationMessage(await response.json());
}
```

- [ ] **Step 4: Re-run the frontend AI tests**

Run:

```bash
npm test -- src/lib/ai.test.ts
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/types/ai.ts src/lib/ai.ts src/lib/ai.test.ts
git commit -m "feat: support ai file-selection interrupt protocol on frontend"
```

## Task 5: Add Single-Select File Modal, Import, and Reselect UI

**Files:**
- Create: `src/lib/chapter-flow-import.ts`
- Test: `src/lib/chapter-flow-import.test.ts`
- Modify: `src/components/AiAssistantPopover.vue`
- Modify: `src/components/AiAssistantPopover.test.ts`
- Modify: `src/pages/CanvasPage.vue`
- Modify: `src/pages/CanvasPage.test.ts`

- [ ] **Step 1: Write the failing UI and adapter tests**

```ts
it('shows a single-select file dialog when assistant returns select_file', async () => {
  emitStreamReply(handlers, waitingInputReply);
  expect(wrapper.text()).toContain('请选择一个文件');
  expect(wrapper.findAll('[data-testid="ai-file-option"]')).toHaveLength(2);
});
```

```ts
it('imports graphPayload into a canvas snapshot', () => {
  const snapshot = buildCanvasSnapshotFromChapterFlow(graphPayload);
  expect(snapshot.xmlContent).toContain('<mxGraphModel');
  expect(Object.keys(snapshot.nodeInfo)).toHaveLength(2);
});
```

```ts
it('reopens the selector when clicking reselect', async () => {
  await wrapper.get('[data-testid="ai-reselect-file"]').trigger('click');
  expect(wrapper.text()).toContain('请选择一个文件');
});
```

- [ ] **Step 2: Run the tests and confirm failure**

Run:

```bash
npm test -- src/components/AiAssistantPopover.test.ts src/pages/CanvasPage.test.ts src/lib/chapter-flow-import.test.ts
```

Expected: FAIL because the popover has no file-selection UI and no import adapter exists.

- [ ] **Step 3: Implement the adapter and UI**

Create `src/lib/chapter-flow-import.ts`:
- map chapter -> swimlane
- map section -> node
- generate `CanvasSnapshotPayload` with:
  - `xmlContent`
  - `nodeInfo`

Recommended adapter shape:

```ts
export function buildCanvasSnapshotFromChapterFlow(graphPayload: AiAssistantArtifact['graphPayload']): CanvasSnapshotPayload {
  return {
    name: 'AI 导入流程图',
    xmlContent: buildMxGraphXml(graphPayload),
    nodeInfo: buildNodeInfo(graphPayload)
  };
}
```

Modify `AiAssistantPopover.vue`:
- render single-select candidate dialog
- hold `selectedUploadId`
- call `resumeAiConversationMessage(...)`
- render `导入` and `重新选择文件`
- emit:

```ts
const emit = defineEmits<{
  (event: 'close'): void;
  (event: 'import-flow', snapshot: CanvasSnapshotPayload): void;
}>();
```

Modify `CanvasPage.vue`:
- listen for `import-flow`
- set `initialCanvasSnapshot`
- optionally trigger save once imported snapshot is loaded

- [ ] **Step 4: Re-run the UI tests**

Run:

```bash
npm test -- src/components/AiAssistantPopover.test.ts src/pages/CanvasPage.test.ts src/lib/chapter-flow-import.test.ts
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lib/chapter-flow-import.ts src/lib/chapter-flow-import.test.ts src/components/AiAssistantPopover.vue src/components/AiAssistantPopover.test.ts src/pages/CanvasPage.vue src/pages/CanvasPage.test.ts
git commit -m "feat: add ai-assisted file selection and flow import UI"
```

## Task 6: Run End-to-End Verification

**Files:**
- Verify only, no intentional file creation

- [ ] **Step 1: Run the backend regression suite for touched AI and parsing paths**

Run:

```bash
pytest tests/test_ai_route.py tests/test_ai_schemas.py tests/test_ai_conversation_service.py tests/test_langgraph_assistant.py tests/test_chapter_flow_service.py tests/test_upload_flow_api.py -q
```

Expected: PASS

- [ ] **Step 2: Run the frontend regression suite for touched assistant and canvas paths**

Run:

```bash
npm test -- src/lib/ai.test.ts src/components/AiAssistantPopover.test.ts src/pages/CanvasPage.test.ts src/lib/chapter-flow-import.test.ts
```

Expected: PASS

- [ ] **Step 3: Run one focused manual flow**

Manual verification:
- upload a `docx`
- open AI assistant
- enter `根据 xxx 文件生成流程图`
- confirm single file selection
- verify `导入` and `重新选择文件`
- verify import updates the canvas

- [ ] **Step 4: Commit the integrated feature**

```bash
git add backend app src docs
git commit -m "feat: add ai interrupt flow for file-based flow chart generation"
```

