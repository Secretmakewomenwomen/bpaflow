# Canvas Save User Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每个登录用户保存唯一的当前画布，持久化 `xml` 和节点 `info`，并在重新进入画布页时自动恢复。

**Architecture:** 后端新增独立 `canvas_document` 模型、schema、service、route，由 JWT 提供 `user_id` 作为唯一隔离边界。前端通过画布组件导出/导入快照，页面层负责加载与保存。

**Tech Stack:** FastAPI, SQLAlchemy, Vue 3, mxGraph, Vitest, Pytest

---

### Task 1: 后端画布存储

**Files:**
- Create: `backend/app/models/canvas.py`
- Create: `backend/app/schemas/canvas.py`
- Create: `backend/app/services/canvas_service.py`
- Create: `backend/app/api/routes/canvas.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/database.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_canvas_service.py`
- Test: `backend/tests/test_canvas_api.py`

- [ ] Step 1: 写失败测试，覆盖创建、覆盖保存、跨用户隔离、鉴权访问
- [ ] Step 2: 运行对应 `pytest`，确认按预期失败
- [ ] Step 3: 实现最小后端模型、schema、service 和 route
- [ ] Step 4: 重新运行后端测试，确认通过

### Task 2: 前端画布快照导出与恢复

**Files:**
- Create: `src/lib/canvas.ts`
- Create: `src/types/canvas.ts`
- Create: `src/lib/canvas.test.ts`
- Modify: `src/components/ArchitectureCanvas.vue`
- Modify: `src/pages/CanvasPage.vue`

- [ ] Step 1: 先写失败测试，定义 API 请求结构和快照数据结构
- [ ] Step 2: 运行 `vitest`，确认失败
- [ ] Step 3: 实现导出 XML / 节点信息和加载画布快照
- [ ] Step 4: 接入页面初始化加载与手动保存
- [ ] Step 5: 运行前端测试与构建验证
