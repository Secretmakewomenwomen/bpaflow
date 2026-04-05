# Stream Graph Checkpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/ai/conversations/{conversation_id}/messages/stream` 改为走 `graph.stream(...)`，并在流式请求中启用同一套 LangGraph checkpoint。

**Architecture:** 保留现有 `StateGraph` 节点定义，不再让 `stream_invoke()` 直接驱动独立 LangChain agent。流式输出通过 LangGraph `get_stream_writer()` 从图节点内发出自定义 delta 事件，最终仍由 `persist_message` 节点统一落库。

**Tech Stack:** FastAPI, LangGraph, OpenAI SDK, pytest

---

### Task 1: 锁定流式 graph 行为

**Files:**
- Modify: `backend/tests/test_langgraph_assistant.py`

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run the targeted tests and confirm the old stream path fails the new expectation**
- [ ] **Step 3: Cover graph.stream + checkpoint + thread_id + delta SSE conversion**

### Task 2: 重构流式执行链路

**Files:**
- Modify: `backend/app/ai/services/langgraph_assistant.py`

- [ ] **Step 1: 让 `stream_invoke()` 使用 `build_graph(...).stream(...)`**
- [ ] **Step 2: 在图节点里接入 `get_stream_writer()` 输出 `assistant_delta`**
- [ ] **Step 3: 统一由 `persist_message` 返回最终 assistant message**

### Task 3: 验证回归

**Files:**
- Test: `backend/tests/test_langgraph_assistant.py`

- [ ] **Step 1: 运行定向 pytest**
- [ ] **Step 2: 检查流式与非流式都保留现有意图和持久化行为**
