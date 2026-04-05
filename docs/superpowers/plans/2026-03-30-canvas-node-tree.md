# Canvas Node Tree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为画布系统增加可持久化的左侧节点树，并将画布读写维度从用户级单例改为 `user_id + node_id`。

**Architecture:** 后端新增 `canvas_tree_node` 表承载节点树，`canvas_document` 改为按 `node_id` 持久化单节点画布；前端新增节点树面板，维护 `activeNodeId`，所有画布加载/保存请求都携带 `nodeId`。当用户首次进入且没有树数据时，后端自动创建默认根节点，确保刷新后可恢复。

**Tech Stack:** Vue 3 + TypeScript + Ant Design Vue + FastAPI + SQLAlchemy + PostgreSQL

---

### Task 1: 后端契约测试先行

**Files:**
- Modify: `backend/tests/test_canvas_service.py`
- Modify: `backend/tests/test_canvas_api.py`

- [ ] 为节点树查询、根节点创建、子节点创建、按 `nodeId` 读写画布补充失败测试
- [ ] 运行 `./.venv/bin/pytest backend/tests/test_canvas_service.py backend/tests/test_canvas_api.py -q` 验证测试先失败

### Task 2: 后端模型与服务

**Files:**
- Modify: `backend/app/models/canvas.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/database.py`
- Modify: `backend/app/schemas/canvas.py`
- Modify: `backend/app/services/canvas_service.py`
- Modify: `backend/app/api/routes/canvas.py`

- [ ] 新增 `CanvasTreeNode` 模型与 `CanvasDocument.node_id`
- [ ] 扩展 schema，支持节点树返回与 `nodeId` 维度画布请求
- [ ] 实现节点树的创建/查询与默认根节点初始化
- [ ] 实现按 `user_id + node_id` 读取和保存画布
- [ ] 运行后端测试直至通过

### Task 3: 前端 API 与类型

**Files:**
- Modify: `src/types/canvas.ts`
- Modify: `src/lib/canvas.ts`
- Modify: `src/lib/canvas.test.ts`

- [ ] 增加节点树类型定义
- [ ] 为节点树查询/创建、按 `nodeId` 的画布读写补充失败测试
- [ ] 运行 `pnpm test -- src/lib/canvas.test.ts` 验证通过

### Task 4: 左侧节点树与画布联动

**Files:**
- Modify: `src/components/DocumentRail.vue`
- Modify: `src/pages/CanvasPage.vue`
- Modify: `src/components/AiAssistantPopover.test.ts`

- [ ] 将左侧静态文档栏改造成节点树面板，并保留原有组件拖拽区
- [ ] 支持新增根节点/子节点与选中节点
- [ ] 切换节点时按 `nodeId` 加载对应画布，无数据则显示空白种子画布
- [ ] 保存时携带当前 `nodeId`
- [ ] 运行相关前端测试

### Task 5: 验证

**Files:**
- None

- [ ] 运行后端相关测试
- [ ] 运行前端相关测试
- [ ] 如有必要补充最小回归测试，确保用户隔离与刷新恢复不回退
