# AI Assistant Chatbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current single-turn AI retrieval panel with a chatbox assistant backed by LangGraph `PostgresSaver` and PostgreSQL-persisted conversation history.

**Architecture:** The backend introduces conversation/message APIs, SQLAlchemy models for AI history, and a LangGraph workflow keyed by `conversation_id` with `PostgresSaver` as checkpointer. The frontend keeps the existing left-top entry but rewrites the panel into a classic chatbox that loads message history, sends new messages, and renders AI references inline under assistant responses.

**Tech Stack:** Vue 3, Vitest, FastAPI, SQLAlchemy, PostgreSQL, LangGraph, PostgresSaver, pytest

---

### Task 1: Backend Dependency And Schema Foundation

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/core/database.py`
- Create: `backend/app/models/ai.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_ai_conversation_service.py`

- [ ] Add `langgraph-checkpoint-postgres` to `backend/requirements.txt`.
- [ ] Create SQLAlchemy models for `ai_conversation`, `ai_message`, and `ai_message_reference`.
- [ ] Register the new models in `create_tables`.
- [ ] Add schema bootstrap for any required indexes.
- [ ] Write and run backend tests for conversation/message persistence.

### Task 2: Conversation Service And API

**Files:**
- Modify: `backend/app/schemas/ai.py`
- Create: `backend/app/services/ai_conversation_service.py`
- Modify: `backend/app/api/routes/ai.py`
- Test: `backend/tests/test_ai_route.py`

- [ ] Expand AI schemas to cover conversation create/list/send payloads.
- [ ] Implement a service for creating conversations, loading history, and persisting messages/references.
- [ ] Replace the old single query route with conversation-based routes.
- [ ] Preserve authenticated user isolation.
- [ ] Update route tests for create, history, and send flows.

### Task 3: LangGraph PostgresSaver Integration

**Files:**
- Modify: `backend/app/services/langgraph_assistant.py`
- Test: `backend/tests/test_langgraph_assistant.py`

- [ ] Wire `PostgresSaver` into graph compilation.
- [ ] Use `conversation_id` as `thread_id`.
- [ ] Add history-loading and persistence hooks around the existing intent/RAG flow.
- [ ] Keep the existing intent contract and XML placeholder behavior.
- [ ] Update tests to validate conversation-aware invocation.

### Task 4: Frontend Chatbox Conversion

**Files:**
- Modify: `src/types/ai.ts`
- Modify: `src/lib/ai.ts`
- Modify: `src/components/AiAssistantPopover.vue`
- Modify: `src/pages/CanvasPage.vue`
- Modify: `src/styles/workbench.css`
- Test: `src/components/AiAssistantPopover.test.ts`
- Test: `src/lib/ai.test.ts`

- [ ] Replace single-query types with conversation/message shapes.
- [ ] Add API helpers for create conversation, fetch messages, and send message.
- [ ] Rewrite `AiAssistantPopover.vue` into a chatbox layout with message bubbles and inline evidence cards.
- [ ] Keep the current AI entry point and close behavior.
- [ ] Update tests for history loading, sending, and assistant reply rendering.

### Task 5: Verification

**Files:**
- Verify only

- [ ] Run targeted backend AI tests.
- [ ] Run targeted frontend AI tests.
- [ ] Run full frontend test suite and build.
- [ ] Document any unrelated pre-existing backend failures separately.
