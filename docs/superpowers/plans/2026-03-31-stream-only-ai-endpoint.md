# Stream Only AI Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除 AI 非流式发送链路，只保留 `/messages/stream` 和 `stream_invoke()`。

**Architecture:** 路由层移除 `POST /conversations/{conversation_id}/messages`，服务层移除 `invoke()`，测试层删除所有 invoke 相关断言，仅保留 stream 路径与其回归用例。

**Tech Stack:** FastAPI, LangGraph, pytest, Python

---

### Task 1: 锁定 stream-only 行为

**Files:**
- Modify: `backend/tests/test_ai_route.py`
- Modify: `backend/tests/test_langgraph_assistant.py`

- [ ] **Step 1: 删除 invoke 相关测试**
- [ ] **Step 2: 增加 `/messages` 返回 404 的测试**
- [ ] **Step 3: 运行定向测试，确认旧实现失败**

### Task 2: 删除 invoke 链路

**Files:**
- Modify: `backend/app/api/routes/ai.py`
- Modify: `backend/app/ai/services/langgraph_assistant.py`
- Modify: `backend/app/schemas/ai.py`

- [ ] **Step 1: 删除非流式路由**
- [ ] **Step 2: 删除 `LangGraphAssistantService.invoke()`**
- [ ] **Step 3: 清理未使用的响应 schema 和测试桩**

### Task 3: 验证回归

**Files:**
- Test: `backend/tests/test_ai_route.py`
- Test: `backend/tests/test_langgraph_assistant.py`
- Test: `backend/tests/test_langchain_stream_tools.py`

- [ ] **Step 1: 运行定向 pytest**
- [ ] **Step 2: 确认只剩 stream 路径可用**
