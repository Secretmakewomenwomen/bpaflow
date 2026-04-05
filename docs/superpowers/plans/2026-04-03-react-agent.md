# ReAct Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `backend/app/ai/services` 从单体式 LangGraph assistant 重构为标准化、可扩展、带 trace 持久化的 ReAct Agent 平台骨架，并完成现有 AI 能力迁移。

**Architecture:** 新增 `backend/app/ai/agent/` 作为平台层，拆分 `runtime/state/reasoning/tools/memory/guardrails/termination/tracing/facade`。保留 `LangGraph` 作为默认 runtime backend，但让 Prompt、State、Tool、Guardrails、Termination、Tracer 都走自有抽象。现有 `langgraph_assistant.py` 退化为兼容 facade/adapter，`ai_conversation_service.py` 继续负责最终消息持久化，新增 `ai_agent_trace` 用于 step 级 trace 持久化。

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, LangGraph, OpenAI Chat Completions, pytest

---

## File Structure

**Runtime Platform**
- Create: `backend/app/ai/agent/__init__.py`
- Create: `backend/app/ai/agent/facade.py`
- Create: `backend/app/ai/agent/runtime/__init__.py`
- Create: `backend/app/ai/agent/runtime/base.py`
- Create: `backend/app/ai/agent/runtime/langgraph_runtime.py`
- Create: `backend/app/ai/agent/runtime/loop_runtime.py`
- Create: `backend/app/ai/agent/state/__init__.py`
- Create: `backend/app/ai/agent/state/models.py`
- Create: `backend/app/ai/agent/state/manager.py`
- Create: `backend/app/ai/agent/reasoning/__init__.py`
- Create: `backend/app/ai/agent/reasoning/models.py`
- Create: `backend/app/ai/agent/reasoning/prompt_builder.py`
- Create: `backend/app/ai/agent/reasoning/parser.py`
- Create: `backend/app/ai/agent/reasoning/engine.py`
- Create: `backend/app/ai/agent/tools/__init__.py`
- Create: `backend/app/ai/agent/tools/models.py`
- Create: `backend/app/ai/agent/tools/registry.py`
- Create: `backend/app/ai/agent/tools/dispatcher.py`
- Create: `backend/app/ai/agent/memory/__init__.py`
- Create: `backend/app/ai/agent/memory/manager.py`
- Create: `backend/app/ai/agent/guardrails/__init__.py`
- Create: `backend/app/ai/agent/guardrails/policy.py`
- Create: `backend/app/ai/agent/termination/__init__.py`
- Create: `backend/app/ai/agent/termination/controller.py`
- Create: `backend/app/ai/agent/tracing/__init__.py`
- Create: `backend/app/ai/agent/tracing/tracer.py`

**Existing Backend Compatibility / Integration**
- Modify: `backend/app/ai/services/langgraph_assistant.py`
- Modify: `backend/app/ai/services/tool_models.py`
- Modify: `backend/app/ai/services/tool_registry.py`
- Modify: `backend/app/ai/services/tool_executor.py`
- Modify: `backend/app/ai/services/ai_conversation_service.py`
- Modify: `backend/app/ai/services/flow_chart_interrupt_service.py`
- Modify: `backend/app/api/routes/ai.py`
- Modify: `backend/app/schemas/ai.py`
- Modify: `backend/app/models/ai.py`
- Modify: `backend/app/core/database.py`
- Modify: `backend/app/models/__init__.py`

**Tests**
- Create: `backend/tests/test_agent_state_manager.py`
- Create: `backend/tests/test_agent_reasoning_engine.py`
- Create: `backend/tests/test_agent_tool_dispatcher.py`
- Create: `backend/tests/test_agent_guardrails.py`
- Create: `backend/tests/test_agent_termination.py`
- Create: `backend/tests/test_agent_tracer.py`
- Modify: `backend/tests/test_database_schema.py`
- Modify: `backend/tests/test_ai_schemas.py`
- Modify: `backend/tests/test_ai_tool_registry.py`
- Modify: `backend/tests/test_ai_tool_executor.py`
- Modify: `backend/tests/test_ai_conversation_service.py`
- Modify: `backend/tests/test_langgraph_assistant.py`
- Modify: `backend/tests/test_ai_route.py`

### Task 1: Add Agent Trace Persistence Foundation

**Files:**
- Modify: `backend/app/models/ai.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/database.py`
- Modify: `backend/tests/test_database_schema.py`
- Create: `backend/tests/test_agent_tracer.py`

- [ ] **Step 1: Write the failing persistence tests for `ai_agent_trace`**

```python
def test_create_tables_includes_ai_agent_trace() -> None:
    engine = create_engine("sqlite:///:memory:")
    create_tables(engine)
    inspector = inspect(engine)
    assert "ai_agent_trace" in inspector.get_table_names()
```

```python
def test_ensure_ai_agent_trace_schema_adds_missing_columns() -> None:
    engine = FakeEngine()
    inspector = FakeInspector(
        columns=["id", "conversation_id", "session_id", "step_index"],
        indexes=[],
        table_name="ai_agent_trace",
    )
    ensure_ai_agent_trace_schema(engine=engine, inspector=inspector)
    assert "ALTER TABLE ai_agent_trace ADD COLUMN phase VARCHAR(32) NOT NULL DEFAULT 'reason'" in engine.connection.statements
```

- [ ] **Step 2: Run the new tests to verify the trace table does not exist yet**

Run:

```bash
cd backend && pytest tests/test_database_schema.py tests/test_agent_tracer.py -q
```

Expected: FAIL because `AiAgentTrace` and its schema guard do not exist.

- [ ] **Step 3: Add the minimal trace model and startup schema guard**

Implement:
- `AiAgentTrace` SQLAlchemy model in `backend/app/models/ai.py`
- export from `backend/app/models/__init__.py`
- `ensure_ai_agent_trace_schema(...)` in `backend/app/core/database.py`
- include `AiAgentTrace.__table__.create(..., checkfirst=True)` in `create_tables(...)`

Minimal model sketch:

```python
class AiAgentTrace(Base):
    __tablename__ = "ai_agent_trace"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    step_index: Mapped[int] = mapped_column(nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_args_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    observation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)
```

- [ ] **Step 4: Add a minimal tracer persistence test**

```python
def test_tracer_persists_reason_and_action_rows(session: Session) -> None:
    tracer = SqlAlchemyAgentTracer(db=session)
    tracer.record_reason(...)
    tracer.record_action(...)
    rows = session.query(AiAgentTrace).order_by(AiAgentTrace.step_index.asc()).all()
    assert [row.phase for row in rows] == ["reason", "action"]
```

- [ ] **Step 5: Run the trace persistence tests again**

Run:

```bash
cd backend && pytest tests/test_database_schema.py tests/test_agent_tracer.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/ai.py backend/app/models/__init__.py backend/app/core/database.py backend/tests/test_database_schema.py backend/tests/test_agent_tracer.py
git commit -m "feat: add ai agent trace persistence"
```

### Task 2: Introduce Core Agent State and Runtime Models

**Files:**
- Create: `backend/app/ai/agent/state/models.py`
- Create: `backend/app/ai/agent/state/manager.py`
- Create: `backend/app/ai/agent/runtime/base.py`
- Create: `backend/tests/test_agent_state_manager.py`
- Modify: `backend/tests/test_langgraph_assistant.py`

- [ ] **Step 1: Write failing tests for session initialization and state progression**

```python
def test_state_manager_initializes_session_for_query() -> None:
    manager = AgentStateManager()
    state = manager.create_session(conversation_id="conv-1", user_id="user-1", query="帮我找理赔资料")
    assert state.conversation_id == "conv-1"
    assert state.step_count == 0
    assert state.status == "running"
```

```python
def test_state_manager_updates_counters_after_repeated_action() -> None:
    state = AgentSessionState(...)
    updated = manager.record_tool_call(state, tool_name="search_knowledge_base", arguments={"query": "理赔"})
    updated = manager.record_tool_call(updated, tool_name="search_knowledge_base", arguments={"query": "理赔"})
    assert updated.repeated_action_count == 1
```

- [ ] **Step 2: Run the state tests to verify the new runtime model is missing**

Run:

```bash
cd backend && pytest tests/test_agent_state_manager.py -q
```

Expected: FAIL with import errors for missing `AgentSessionState` / `AgentStateManager`.

- [ ] **Step 3: Implement the minimal runtime state models and manager**

Create:
- `AgentSessionState`
- `AgentStepState`
- `ToolCallRecord`
- `ToolObservationRecord`
- `AgentStateManager`

Keep first implementation focused on:
- session creation
- step increment
- repeated action count
- consecutive empty step count
- pending action / final response setters

- [ ] **Step 4: Add a lightweight `AgentRuntime` protocol**

```python
class AgentRuntime(Protocol):
    def run(self, *, session_state: AgentSessionState, stream: bool = False) -> AgentSessionState: ...
```

- [ ] **Step 5: Re-run the state tests**

Run:

```bash
cd backend && pytest tests/test_agent_state_manager.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/agent/state/models.py backend/app/ai/agent/state/manager.py backend/app/ai/agent/runtime/base.py backend/tests/test_agent_state_manager.py
git commit -m "feat: add ai agent state manager"
```

### Task 3: Standardize Tool Protocols and Dispatcher

**Files:**
- Create: `backend/app/ai/agent/tools/models.py`
- Create: `backend/app/ai/agent/tools/registry.py`
- Create: `backend/app/ai/agent/tools/dispatcher.py`
- Modify: `backend/app/ai/services/tool_models.py`
- Modify: `backend/app/ai/services/tool_registry.py`
- Modify: `backend/app/ai/services/tool_executor.py`
- Modify: `backend/tests/test_ai_tool_registry.py`
- Modify: `backend/tests/test_ai_tool_executor.py`
- Create: `backend/tests/test_agent_tool_dispatcher.py`

- [ ] **Step 1: Write failing tests for richer tool metadata**

```python
def test_registry_exposes_runtime_tool_metadata() -> None:
    tool = get_tool("search_knowledge_base")
    assert tool.output_schema["type"] == "object"
    assert tool.idempotent is True
    assert tool.requires_confirmation is False
```

```python
def test_dispatcher_standardizes_validation_errors() -> None:
    result = dispatcher.execute("get_file_detail", upload_id="bad")
    assert result.ok is False
    assert result.error.code == "INVALID_ARGUMENT"
    assert result.error.category == "validation"
```

- [ ] **Step 2: Run the dispatcher tests to confirm the old executor is too thin**

Run:

```bash
cd backend && pytest tests/test_ai_tool_registry.py tests/test_ai_tool_executor.py tests/test_agent_tool_dispatcher.py -q
```

Expected: FAIL because current tool metadata lacks `output_schema`, `idempotent`, `requires_confirmation`, and structured result models.

- [ ] **Step 3: Implement runtime tool models and registry**

Add:
- `ToolDefinition`
- `ToolCall`
- `ToolResult`
- `ToolError`
- `ToolRetryPolicy`

Update registry definitions to include:
- `output_schema`
- `idempotent`
- `requires_confirmation`
- `required_scopes`
- `retry_policy`

- [ ] **Step 4: Implement dispatcher with standardized error mapping**

Cover:
- unknown tool
- invalid argument
- permission denied
- service error
- context user injection

- [ ] **Step 5: Keep legacy imports working**

Make:
- `backend/app/ai/services/tool_models.py`
- `backend/app/ai/services/tool_registry.py`
- `backend/app/ai/services/tool_executor.py`

delegate to the new `backend/app/ai/agent/tools/` implementation so old call sites still import successfully during migration.

- [ ] **Step 6: Re-run the tool tests**

Run:

```bash
cd backend && pytest tests/test_ai_tool_registry.py tests/test_ai_tool_executor.py tests/test_agent_tool_dispatcher.py -q
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/ai/agent/tools/models.py backend/app/ai/agent/tools/registry.py backend/app/ai/agent/tools/dispatcher.py backend/app/ai/services/tool_models.py backend/app/ai/services/tool_registry.py backend/app/ai/services/tool_executor.py backend/tests/test_ai_tool_registry.py backend/tests/test_ai_tool_executor.py backend/tests/test_agent_tool_dispatcher.py
git commit -m "feat: standardize ai agent tool protocols"
```

### Task 4: Add Prompt Builder, Parser, and Reasoning Engine

**Files:**
- Create: `backend/app/ai/agent/reasoning/models.py`
- Create: `backend/app/ai/agent/reasoning/prompt_builder.py`
- Create: `backend/app/ai/agent/reasoning/parser.py`
- Create: `backend/app/ai/agent/reasoning/engine.py`
- Create: `backend/tests/test_agent_reasoning_engine.py`
- Modify: `backend/tests/test_langgraph_assistant.py`

- [ ] **Step 1: Write failing tests for prompt composition and decision parsing**

```python
def test_prompt_builder_includes_system_rules_and_recent_history() -> None:
    messages = builder.build_messages(query="帮我找理赔资料", history_messages=[...], memory_summary="最近已查过 claim-guide.pdf")
    assert messages[0]["role"] == "system"
    assert "优先使用一次 search_knowledge_base" in messages[0]["content"]
    assert messages[-1]["content"] == "帮我找理赔资料"
```

```python
def test_reasoning_engine_returns_tool_call_decision_for_tool_completion() -> None:
    engine = ReasoningEngine(client=fake_client)
    decision = engine.decide(...)
    assert decision.decision_type == "tool_call"
    assert decision.tool_calls[0].tool_name == "search_knowledge_base"
```

- [ ] **Step 2: Run the reasoning tests**

Run:

```bash
cd backend && pytest tests/test_agent_reasoning_engine.py -q
```

Expected: FAIL because no `PromptBuilder`, `AgentDecision`, or `ReasoningEngine` exists.

- [ ] **Step 3: Implement the prompt builder**

Move the current `_build_agent_loop_messages(...)` rules into `PromptBuilder`, split into:
- base system role
- tool use rules
- multi-topic retrieval rule
- error recovery rule

- [ ] **Step 4: Implement parser and engine**

Implement:
- `AgentDecision`
- `DecisionType`
- parser helpers for tool calls and final content
- `ReasoningEngine.decide(...)`

First version only needs to support:
- final answer
- one or more tool calls
- malformed tool args parse error

- [ ] **Step 5: Re-run the reasoning tests**

Run:

```bash
cd backend && pytest tests/test_agent_reasoning_engine.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/agent/reasoning/models.py backend/app/ai/agent/reasoning/prompt_builder.py backend/app/ai/agent/reasoning/parser.py backend/app/ai/agent/reasoning/engine.py backend/tests/test_agent_reasoning_engine.py
git commit -m "feat: add ai agent reasoning engine"
```

### Task 5: Add Guardrails, Memory, and Termination Policies

**Files:**
- Create: `backend/app/ai/agent/memory/manager.py`
- Create: `backend/app/ai/agent/guardrails/policy.py`
- Create: `backend/app/ai/agent/termination/controller.py`
- Create: `backend/tests/test_agent_guardrails.py`
- Create: `backend/tests/test_agent_termination.py`

- [ ] **Step 1: Write failing tests for tool validation and stop policies**

```python
def test_guardrails_block_confirmation_required_tool_without_user_confirmation() -> None:
    decision = AgentDecision(...)
    result = guardrails.validate_tool_call(session_state, tool_definition, tool_call)
    assert result.allowed is False
    assert result.error_code == "CONFIRMATION_REQUIRED"
```

```python
def test_termination_controller_stops_after_reaching_max_steps() -> None:
    state = AgentSessionState(step_count=6, ...)
    signal = controller.evaluate(state, last_decision=AgentDecision(decision_type="tool_call", ...))
    assert signal.should_stop is True
    assert signal.status == "max_steps"
```

- [ ] **Step 2: Run the policy tests**

Run:

```bash
cd backend && pytest tests/test_agent_guardrails.py tests/test_agent_termination.py -q
```

Expected: FAIL because guardrails and termination policies do not exist yet.

- [ ] **Step 3: Implement the minimal memory manager**

Support:
- recent history window
- observation summary list
- tool result summary extraction

Long-term memory should be a no-op interface for now.

- [ ] **Step 4: Implement guardrails and termination**

Guardrails must cover:
- schema validation handoff
- user context existence
- confirmation-required tool blocking hook

Termination must cover:
- max steps
- repeated action limit
- consecutive empty steps
- waiting input stop
- final answer stop

- [ ] **Step 5: Re-run the policy tests**

Run:

```bash
cd backend && pytest tests/test_agent_guardrails.py tests/test_agent_termination.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/agent/memory/manager.py backend/app/ai/agent/guardrails/policy.py backend/app/ai/agent/termination/controller.py backend/tests/test_agent_guardrails.py backend/tests/test_agent_termination.py
git commit -m "feat: add ai agent guardrails and termination"
```

### Task 6: Implement LangGraph Runtime and Facade Integration

**Files:**
- Create: `backend/app/ai/agent/tracing/tracer.py`
- Create: `backend/app/ai/agent/runtime/langgraph_runtime.py`
- Create: `backend/app/ai/agent/runtime/loop_runtime.py`
- Create: `backend/app/ai/agent/facade.py`
- Modify: `backend/app/ai/services/langgraph_assistant.py`
- Modify: `backend/app/ai/services/flow_chart_interrupt_service.py`
- Modify: `backend/tests/test_langgraph_assistant.py`
- Modify: `backend/tests/test_ai_conversation_service.py`

- [ ] **Step 1: Write failing integration tests for runtime-driven agent loop**

```python
def test_stream_invoke_uses_runtime_facade_and_persists_trace() -> None:
    service = _service(...)
    events = list(service.stream_invoke(conversation_id="conv-1", query="帮我找理赔资料", user_id="user-1"))
    assert events[0]["event"] == "assistant_start"
    assert any(event["event"] == "assistant_done" for event in events)
```

```python
def test_runtime_preserves_flow_chart_waiting_input_behavior() -> None:
    state = facade.run(conversation_id="conv-1", query="根据文件生成流程图", user_id="user-1", stream=False)
    assert state.final_response.status == "waiting_input"
```

- [ ] **Step 2: Run the runtime integration tests**

Run:

```bash
cd backend && pytest tests/test_langgraph_assistant.py tests/test_ai_conversation_service.py -k "runtime or stream or flow_chart" -q
```

Expected: FAIL because `LangGraphAssistantService` still owns the old agent loop directly.

- [ ] **Step 3: Implement tracer and facade**

Create:
- `SqlAlchemyAgentTracer`
- `AgentFacade`

Facade should own:
- state creation
- runtime selection
- final `AssistantResponse` mapping
- flow-chart resume orchestration handoff

- [ ] **Step 4: Implement `LangGraphAgentRuntime`**

Responsibilities:
- load recent history
- call reasoning engine
- execute tools through dispatcher
- record traces
- consult guardrails and termination
- support streaming callbacks

Keep `LoopAgentRuntime` as a stub:

```python
class LoopAgentRuntime(AgentRuntime):
    def run(self, *, session_state: AgentSessionState, stream: bool = False) -> AgentSessionState:
        raise NotImplementedError("LoopAgentRuntime is not implemented in phase 1")
```

- [ ] **Step 5: Refactor `langgraph_assistant.py` into a compatibility adapter**

Keep these public methods:
- `stream_invoke(...)`
- `resume_flow_chart_generation(...)`
- `export_graph_mermaid()`

Internally delegate to `AgentFacade`.

- [ ] **Step 6: Re-run the runtime integration tests**

Run:

```bash
cd backend && pytest tests/test_langgraph_assistant.py tests/test_ai_conversation_service.py -k "runtime or stream or flow_chart" -q
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/ai/agent/tracing/tracer.py backend/app/ai/agent/runtime/langgraph_runtime.py backend/app/ai/agent/runtime/loop_runtime.py backend/app/ai/agent/facade.py backend/app/ai/services/langgraph_assistant.py backend/app/ai/services/flow_chart_interrupt_service.py backend/tests/test_langgraph_assistant.py backend/tests/test_ai_conversation_service.py
git commit -m "refactor: move ai assistant runtime into react facade"
```

### Task 7: Map Runtime Output Back to API Schemas and Routes

**Files:**
- Modify: `backend/app/schemas/ai.py`
- Modify: `backend/app/ai/services/ai_conversation_service.py`
- Modify: `backend/app/api/routes/ai.py`
- Modify: `backend/tests/test_ai_schemas.py`
- Modify: `backend/tests/test_ai_route.py`

- [ ] **Step 1: Write failing tests for API compatibility with runtime output**

```python
def test_assistant_response_accepts_runtime_tool_trace_and_waiting_input() -> None:
    response = AssistantResponse.model_validate(
        {
            "intent": "generate_flow_from_file",
            "status": "waiting_input",
            "answer": "请选择文件。",
            "tool_trace": [{"tool_name": "list_recent_files", "tool_args": {}, "status": "success"}],
            "pending_action": {...},
        }
    )
    assert response.status == "waiting_input"
```

```python
def test_stream_route_returns_runtime_generated_events(client) -> None:
    response = client.post("/ai/conversations/conv-1/messages/stream", json={"query": "帮我找理赔资料"})
    assert response.status_code == 200
    assert "event: assistant_done" in response.text
```

- [ ] **Step 2: Run schema and route tests**

Run:

```bash
cd backend && pytest tests/test_ai_schemas.py tests/test_ai_route.py -q
```

Expected: FAIL if route wiring or schema mapping still depends on old internal structures.

- [ ] **Step 3: Update schema and persistence mapping**

Ensure:
- `AssistantResponse` remains API-facing
- `ConversationMessageResponse` can reconstruct `pending_action`, `artifact`, `actions`, `tool_trace`
- `AiConversationService` only persists final assistant message payload, not runtime state

- [ ] **Step 4: Update route wiring**

Keep route contracts stable, but instantiate assistant service/facade with:
- conversation service
- upload service
- work service
- optional trace persistence dependencies

- [ ] **Step 5: Re-run schema and route tests**

Run:

```bash
cd backend && pytest tests/test_ai_schemas.py tests/test_ai_route.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/ai.py backend/app/ai/services/ai_conversation_service.py backend/app/api/routes/ai.py backend/tests/test_ai_schemas.py backend/tests/test_ai_route.py
git commit -m "feat: map react runtime output to ai api schemas"
```

### Task 8: Full Regression Verification and Cleanup

**Files:**
- Modify: `backend/tests/test_langgraph_assistant.py`
- Modify: `backend/tests/test_ai_route.py`
- Modify: `backend/tests/test_ai_conversation_service.py`
- Modify: `backend/tests/test_agent_tracer.py`
- Modify: compatibility wrappers if needed

- [ ] **Step 1: Add final regression tests for the three supported capabilities**

```python
def test_general_chat_returns_final_answer_without_tools() -> None:
    ...
```

```python
def test_rag_retrieval_uses_search_tool_and_returns_references() -> None:
    ...
```

```python
def test_generate_flow_from_file_preserves_resume_flow() -> None:
    ...
```

- [ ] **Step 2: Run the focused backend regression suite**

Run:

```bash
cd backend && pytest \
  tests/test_agent_state_manager.py \
  tests/test_agent_reasoning_engine.py \
  tests/test_agent_tool_dispatcher.py \
  tests/test_agent_guardrails.py \
  tests/test_agent_termination.py \
  tests/test_agent_tracer.py \
  tests/test_ai_tool_registry.py \
  tests/test_ai_tool_executor.py \
  tests/test_ai_conversation_service.py \
  tests/test_ai_schemas.py \
  tests/test_langgraph_assistant.py \
  tests/test_ai_route.py \
  tests/test_database_schema.py -q
```

Expected: PASS

- [ ] **Step 3: Run a broader smoke suite for AI-adjacent behavior**

Run:

```bash
cd backend && pytest tests/test_ai_rag_service.py tests/test_agent_api.py tests/test_main_startup.py -q
```

Expected: PASS or only fail for unrelated pre-existing issues that must be documented.

- [ ] **Step 4: Remove or shrink dead compatibility code only after green tests**

Checklist:
- no active call site depends on old `run_agent_loop` internals
- old tool wrapper modules are thin delegators only
- no duplicate prompt logic remains in `langgraph_assistant.py`

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai backend/app/api/routes/ai.py backend/app/models/ai.py backend/app/core/database.py backend/tests
git commit -m "refactor: finalize react agent runtime migration"
```

