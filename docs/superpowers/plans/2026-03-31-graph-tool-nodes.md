# Graph Tool Nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将上传文件查询和用户查询这类工具调用并回 `LangGraph`，不再依赖独立 agent 路由。

**Architecture:** 在现有 `StateGraph` 中新增“工具识别”和“工具执行”节点，先用规则识别可直接处理的查询，再进入统一的 `build_response -> persist_message` 链路。流式和非流式都走同一张图，工具结果通过已有响应结构输出。

**Tech Stack:** LangGraph, FastAPI, pytest, Python

---

### Task 1: 锁定 graph 工具节点行为

**Files:**
- Modify: `backend/tests/test_langgraph_assistant.py`

- [ ] **Step 1: 写失败测试，覆盖 `queryUsers` 工具路由**
- [ ] **Step 2: 写失败测试，覆盖上传详情工具路由和流式输出**
- [ ] **Step 3: 运行定向测试，确认旧实现无法通过**

### Task 2: 实现 graph 工具节点

**Files:**
- Modify: `backend/app/ai/services/langgraph_assistant.py`

- [ ] **Step 1: 新增工具识别状态和路由节点**
- [ ] **Step 2: 新增工具执行节点和结果格式化**
- [ ] **Step 3: 接入 `build_response` 与现有 stream delta 输出**

### Task 3: 验证回归

**Files:**
- Test: `backend/tests/test_langgraph_assistant.py`
- Test: `backend/tests/test_ai_route.py`
- Test: `backend/tests/test_langchain_stream_tools.py`

- [ ] **Step 1: 运行定向 pytest**
- [ ] **Step 2: 确认 invoke/stream/checkpoint 都保持可用**
