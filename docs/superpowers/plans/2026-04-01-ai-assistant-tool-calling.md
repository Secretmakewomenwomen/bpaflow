# AI Assistant Tool-Calling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 AI 助手主链路从“规则分流 + 局部工具直调”改成“LLM 自主 tool-calling + 后端统一执行与追踪”。

**Architecture:** 保留现有 FastAPI + LangGraph + OpenAI client 主栈，在 `langgraph_assistant.py` 中收敛为 `load_history -> run_agent_loop -> build_response -> persist_message` 四节点图；新增静态工具注册表与统一执行器，所有工具 schema 直接暴露给模型，失败后只做结构化错误回填和一次模型自纠，不做规则兜底。响应结构和 SSE 逐步从 `intent` 驱动迁移到 `answer + references + tool_trace`。

**Tech Stack:** FastAPI, LangGraph, OpenAI Chat Completions tool-calling, pytest, Vue 3, TypeScript

---

### Task 1: 锁定工具注册表与执行器行为

**Files:**
- Create: `backend/tests/test_ai_tool_registry.py`
- Create: `backend/tests/test_ai_tool_executor.py`
- Check: `backend/app/services/upload_service.py`
- Check: `backend/app/services/work_service.py`
- Check: `backend/app/ai/services/ai_rag_service.py`

- [ ] **Step 1: 写 `tool_registry` 失败测试，锁定首批工具名称与 schema**

```python
def test_registry_exposes_expected_tool_names() -> None:
    registry = build_tool_registry(...)
    assert sorted(tool.name for tool in registry.list_exposed()) == [
        "generate_xml_placeholder",
        "get_file_detail",
        "list_recent_files",
        "query_users",
        "search_knowledge_base",
    ]
```

- [ ] **Step 2: 写 `tool_executor` 失败测试，覆盖成功执行、参数错误和 service 异常**

```python
def test_execute_returns_retryable_error_for_invalid_arguments() -> None:
    result = executor.execute("get_file_detail", {"upload_id": "bad"})
    assert result.ok is False
    assert result.error["code"] == "INVALID_ARGUMENT"
    assert result.error["retryable"] is True
```

- [ ] **Step 3: 运行定向测试，确认当前代码尚未提供 registry/executor**

Run: `cd backend && pytest tests/test_ai_tool_registry.py tests/test_ai_tool_executor.py -v`
Expected: FAIL with import or assertion errors for missing tool registry / executor.

- [ ] **Step 4: 实现最小 `tool_models.py`、`tool_registry.py`、`tool_executor.py`**

```python
@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    executor: Callable[[dict[str, Any]], Any]
```

- [ ] **Step 5: 再跑定向测试，确认工具能力边界稳定**

Run: `cd backend && pytest tests/test_ai_tool_registry.py tests/test_ai_tool_executor.py -v`
Expected: PASS

- [ ] **Step 6: 提交本任务**

```bash
git add backend/app/ai/services/tool_models.py backend/app/ai/services/tool_registry.py backend/app/ai/services/tool_executor.py backend/tests/test_ai_tool_registry.py backend/tests/test_ai_tool_executor.py
git commit -m "feat: add ai tool registry and executor"
```

### Task 2: 锁定 `run_agent_loop` 的 tool-calling 循环

**Files:**
- Modify: `backend/tests/test_langgraph_assistant.py`
- Check: `backend/app/ai/services/langgraph_assistant.py`
- Check: `backend/app/schemas/ai.py`

- [ ] **Step 1: 写失败测试，覆盖单工具调用后返回最终答案**

```python
def test_agent_loop_executes_tool_call_then_returns_final_answer() -> None:
    client = FakeOpenAIClient(responses=[
        _completion_with_tool_calls(_tool_call("query_users", "{}")),
        _completion_with_content("已查询到 1 个用户。"),
    ])
    service = _service(settings=_settings(...), openai_client=client, work_service=FakeWorkService())
    response = service.invoke_agent_loop_for_test(...)
    assert response["answer"] == "已查询到 1 个用户。"
```

- [ ] **Step 2: 写失败测试，覆盖多工具串联**

```python
def test_agent_loop_allows_multiple_tool_calls() -> None:
    ...
    assert [item["tool_name"] for item in state["tool_trace"]] == [
        "list_recent_files",
        "get_file_detail",
    ]
```

- [ ] **Step 3: 写失败测试，覆盖工具错误回填后仅允许一次模型自纠**

```python
def test_agent_loop_retries_once_after_tool_error() -> None:
    ...
    assert retry_count == 1
```

- [ ] **Step 4: 运行定向测试，确认旧的规则节点实现无法满足新行为**

Run: `cd backend && pytest tests/test_langgraph_assistant.py -k "tool_call or agent_loop or retry" -v`
Expected: FAIL because current implementation still depends on `_resolve_tool_request` and `Intent` routing.

- [ ] **Step 5: 在 `langgraph_assistant.py` 中实现 `run_agent_loop`，并保留最小兼容适配**

```python
while tool_rounds < max_tool_rounds:
    completion = client.chat.completions.create(
        model=settings.assistant_llm_model,
        messages=messages,
        tools=tool_schemas,
        tool_choice="auto",
        stream=False,
    )
```

- [ ] **Step 6: 再跑定向测试，确认 agent loop 基本闭环成立**

Run: `cd backend && pytest tests/test_langgraph_assistant.py -k "tool_call or agent_loop or retry" -v`
Expected: PASS

- [ ] **Step 7: 提交本任务**

```bash
git add backend/app/ai/services/langgraph_assistant.py backend/tests/test_langgraph_assistant.py
git commit -m "feat: add ai tool-calling agent loop"
```

### Task 3: 移除规则工具分流并收敛 LangGraph 主图

**Files:**
- Modify: `backend/tests/test_langgraph_assistant.py`
- Modify: `backend/tests/test_ai_route.py`
- Modify: `backend/app/ai/services/langgraph_assistant.py`

- [ ] **Step 1: 写失败测试，锁定新图结构只包含四节点主路径**

```python
def test_export_graph_mermaid_uses_agent_loop_path() -> None:
    mermaid = service.export_graph_mermaid()
    assert "run_agent_loop" in mermaid
    assert "detect_tool_request" not in mermaid
```

- [ ] **Step 2: 写失败测试，锁定 `assistant_start` 不再依赖硬编码 `intent`**

```python
def test_stream_start_payload_is_not_intent_driven() -> None:
    events = list(service.stream_invoke(...))
    assert events[0]["event"] == "assistant_start"
    assert "intent" not in events[0]["data"]
```

- [ ] **Step 3: 运行定向测试，确认旧图结构未被清理**

Run: `cd backend && pytest tests/test_langgraph_assistant.py tests/test_ai_route.py -k "graph or assistant_start" -v`
Expected: FAIL

- [ ] **Step 4: 删除 `classify_intent`、`detect_tool_request`、`_resolve_tool_request`、`_invoke_tool_node` 及其路由**

```python
graph.add_node("run_agent_loop", self._run_agent_loop_node)
graph.add_edge("load_history", "run_agent_loop")
graph.add_edge("run_agent_loop", "build_response")
```

- [ ] **Step 5: 再跑定向测试，确认主图已收敛**

Run: `cd backend && pytest tests/test_langgraph_assistant.py tests/test_ai_route.py -k "graph or assistant_start" -v`
Expected: PASS

- [ ] **Step 6: 提交本任务**

```bash
git add backend/app/ai/services/langgraph_assistant.py backend/tests/test_langgraph_assistant.py backend/tests/test_ai_route.py
git commit -m "refactor: replace rule-based ai graph routing"
```

### Task 4: 迁移响应结构与消息持久化

**Files:**
- Modify: `backend/tests/test_ai_schemas.py`
- Modify: `backend/tests/test_langgraph_assistant.py`
- Modify: `backend/tests/test_ai_route.py`
- Modify: `backend/app/schemas/ai.py`
- Modify: `backend/app/ai/services/ai_conversation_service.py`
- Modify: `backend/app/ai/services/langgraph_assistant.py`

- [ ] **Step 1: 写失败测试，锁定 `AssistantResponse` 支持 `references` 与 `tool_trace`**

```python
def test_assistant_response_supports_tool_trace() -> None:
    payload = AssistantResponse(answer="done", references=[], tool_trace=[...])
    assert payload.tool_trace[0].tool_name == "query_users"
```

- [ ] **Step 2: 写失败测试，锁定持久化消息在 `intent` 缺失时仍能落库并返回内容**

```python
def test_create_assistant_message_without_intent_persists_content() -> None:
    ...
    assert message.content == "done"
```

- [ ] **Step 3: 运行定向测试，确认旧 schema 仍强依赖 `intent`**

Run: `cd backend && pytest tests/test_ai_schemas.py tests/test_langgraph_assistant.py tests/test_ai_route.py -k "tool_trace or references or intent" -v`
Expected: FAIL

- [ ] **Step 4: 实现 `references`、`tool_trace` 结构，并在 `build_response` / `create_assistant_message` 中接线**

```python
class AssistantToolTrace(BaseModel):
    tool_name: str
    tool_args: dict[str, Any]
    status: Literal["success", "error"]
```

- [ ] **Step 5: 再跑定向测试，确认 schema 和持久化兼容通过**

Run: `cd backend && pytest tests/test_ai_schemas.py tests/test_langgraph_assistant.py tests/test_ai_route.py -k "tool_trace or references or intent" -v`
Expected: PASS

- [ ] **Step 6: 提交本任务**

```bash
git add backend/app/schemas/ai.py backend/app/ai/services/ai_conversation_service.py backend/app/ai/services/langgraph_assistant.py backend/tests/test_ai_schemas.py backend/tests/test_langgraph_assistant.py backend/tests/test_ai_route.py
git commit -m "feat: add ai response references and tool trace"
```

### Task 5: 暴露工具过程 SSE 并改前端消费类型

**Files:**
- Modify: `backend/tests/test_ai_route.py`
- Modify: `backend/tests/test_langgraph_assistant.py`
- Modify: `src/types/ai.ts`
- Modify: `src/lib/ai.ts`
- Modify: `src/components/AiAssistantPopover.vue`
- Modify: `src/components/AiAssistantPopover.test.ts`

- [ ] **Step 1: 写前后端失败测试，锁定 `assistant_debug` 事件结构**

```python
def test_stream_route_includes_assistant_debug_events() -> None:
    ...
    assert 'event: assistant_debug' in body
```

```ts
it('captures assistant_debug tool progress events', async () => {
  expect(debugEvents[0].stage).toBe('tool_call_started');
});
```

- [ ] **Step 2: 运行后端和前端定向测试，确认当前类型与消费逻辑还不支持过程事件**

Run: `cd backend && pytest tests/test_ai_route.py tests/test_langgraph_assistant.py -k assistant_debug -v`
Expected: FAIL

Run: `npm test -- --runInBand src/components/AiAssistantPopover.test.ts`
Expected: FAIL because types and stream handlers do not include debug payloads.

- [ ] **Step 3: 在后端补齐 `assistant_debug` 事件，在前端增加 `onAssistantDebug` 和过程 UI**

```ts
export interface StreamAiConversationHandlers {
  onAssistantDebug?: (payload: AiAssistantDebugEvent) => void;
}
```

- [ ] **Step 4: 再跑定向测试，确认工具过程可见**

Run: `cd backend && pytest tests/test_ai_route.py tests/test_langgraph_assistant.py -k assistant_debug -v`
Expected: PASS

Run: `npm test -- --runInBand src/components/AiAssistantPopover.test.ts`
Expected: PASS

- [ ] **Step 5: 提交本任务**

```bash
git add backend/tests/test_ai_route.py backend/tests/test_langgraph_assistant.py src/types/ai.ts src/lib/ai.ts src/components/AiAssistantPopover.vue src/components/AiAssistantPopover.test.ts
git commit -m "feat: surface ai tool progress events"
```

### Task 6: 清理遗留实现并做回归验证

**Files:**
- Modify: `backend/tests/test_langchain_stream_tools.py`
- Modify: `backend/tests/test_ai_route.py`
- Delete: `backend/app/ai/services/langchain_agent_factory.py`
- Delete: `backend/app/ai/services/langchain_tools.py`
- Modify: `docs/superpowers/specs/2026-04-01-ai-assistant-tool-calling-design.md`

- [ ] **Step 1: 写失败测试，锁定主链路不再依赖 LangChain 工具包装**

```python
def test_tool_calling_stack_does_not_require_langchain_tool_builders() -> None:
    ...
```

- [ ] **Step 2: 运行全量 AI 定向测试，确认仍有遗留依赖**

Run: `cd backend && pytest tests/test_langgraph_assistant.py tests/test_ai_route.py tests/test_ai_schemas.py tests/test_ai_rag_service.py -v`
Expected: FAIL until imports and dead code are cleaned up.

- [ ] **Step 3: 删除不再使用的 LangChain agent/tool 文件，清理导入和文档引用**

```bash
git rm backend/app/ai/services/langchain_agent_factory.py backend/app/ai/services/langchain_tools.py
```

- [ ] **Step 4: 跑后端 AI 全量测试和前端 AI 相关测试**

Run: `cd backend && pytest tests/test_langgraph_assistant.py tests/test_ai_route.py tests/test_ai_schemas.py tests/test_ai_rag_service.py tests/test_ai_intent.py -v`
Expected: PASS, or remove/replace obsolete `intent` assertions where appropriate.

Run: `npm test -- --runInBand src/components/AiAssistantPopover.test.ts src/lib/ai.test.ts`
Expected: PASS

- [ ] **Step 5: 跑关键 smoke**

Run: `cd backend && pytest tests/test_langgraph_assistant.py tests/test_ai_route.py -v`
Expected: PASS

- [ ] **Step 6: 提交本任务**

```bash
git add docs/superpowers/specs/2026-04-01-ai-assistant-tool-calling-design.md backend/tests/test_langchain_stream_tools.py backend/tests/test_langgraph_assistant.py backend/tests/test_ai_route.py backend/tests/test_ai_schemas.py src/components/AiAssistantPopover.test.ts src/lib/ai.test.ts
git commit -m "refactor: remove legacy ai tool routing"
```

