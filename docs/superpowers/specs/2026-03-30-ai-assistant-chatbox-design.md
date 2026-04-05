# AI 助手 Chatbox 设计

## 背景

当前第一阶段 AI 助手已经具备左上角入口、单轮意图识别和 RAG 检索能力，但交互形态仍是结果面板，不符合“chatbox 形式的 AI 助手”目标。

本次迭代将 AI 助手升级为经典聊天窗，同时引入 LangGraph checkpoint 和 PostgreSQL 会话持久化能力，使用户可以进行多轮对话，并在服务重启后恢复历史消息。

## 目标

- 将 AI 助手改造成经典 chatbox
- 使用 `LangGraph` 维护会话编排
- 使用 `PostgresSaver` 存储 checkpoint
- 使用 PostgreSQL 业务表存储会话、消息与引用证据
- 页面重新打开或服务重启后，可恢复历史消息并继续对话

## 非目标

- 多会话列表页
- 流式输出
- XML 生成功能闭环
- 图片向量检索
- 复杂工具调用编排

## 用户体验

### 入口与容器

- 入口仍位于左上角 `AI` 标识
- 点击后打开完整高度的 chatbox
- 容器包含：
  - 头部：标题、会话状态、关闭按钮
  - 中部：消息流
  - 底部：输入框和发送按钮

### 消息形态

- 用户消息显示为右侧气泡
- AI 消息显示为左侧气泡
- AI 消息正文下方展示结构化引用区：
  - 命中片段
  - 相关文件

### 会话行为

- 第一次打开时自动创建默认会话
- 再次打开时继续当前会话
- 历史消息从 PostgreSQL 回放
- 发送新消息时基于同一 `conversation_id` 继续 LangGraph 线程

## 系统设计

### 前端

新增或调整：

- `src/components/AiAssistantPopover.vue`
- `src/lib/ai.ts`
- `src/types/ai.ts`
- `src/pages/CanvasPage.vue`

职责：

- `CanvasPage.vue` 维护当前 `conversationId` 和消息列表加载
- `AiAssistantPopover.vue` 渲染 chatbox 消息流与输入区
- `lib/ai.ts` 负责会话创建、消息拉取、发送消息 API

### 后端

新增或调整：

- `backend/app/api/routes/ai.py`
- `backend/app/schemas/ai.py`
- `backend/app/services/langgraph_assistant.py`
- `backend/app/services/ai_conversation_service.py`
- `backend/app/models/ai.py`
- `backend/app/core/database.py`

职责：

- `ai.py` 提供 conversation/message REST 接口
- `schemas/ai.py` 定义会话、消息、引用结构
- `langgraph_assistant.py` 使用 `PostgresSaver` 编排多轮对话
- `ai_conversation_service.py` 负责会话历史持久化
- `models/ai.py` 定义数据库实体

## 数据模型

### ai_conversation

- `id`
- `user_id`
- `title`
- `created_at`
- `updated_at`
- `last_message_at`

### ai_message

- `id`
- `conversation_id`
- `role`
- `intent`
- `content`
- `status`
- `created_at`

### ai_message_reference

- `id`
- `message_id`
- `reference_type`
- `upload_id`
- `file_name`
- `snippet_text`
- `page_start`
- `page_end`
- `score`
- `download_url`
- `created_at`

## LangGraph 设计

### 线程与 checkpoint

- `thread_id = conversation_id`
- `PostgresSaver` 作为 graph checkpointer
- checkpoint 保存 graph 状态与短期上下文
- 业务表保存可回放的聊天历史

### 状态

- `conversation_id`
- `user_id`
- `query`
- `history_messages`
- `intent`
- `retrieval_response`
- `answer`
- `message`
- `response`

### 节点

1. `load_history`
2. `classify_intent`
3. `retrieve_documents`
4. `synthesize_answer`
5. `persist_messages`
6. `build_response`

## API 设计

### `POST /api/ai/conversations`

- 新建会话
- 返回 `conversation_id`

### `GET /api/ai/conversations/{conversation_id}/messages`

- 拉取会话历史
- 按时间升序返回

### `POST /api/ai/conversations/{conversation_id}/messages`

- 接收用户消息
- 触发 LangGraph
- 返回本轮新增的用户消息和 AI 消息

## 持久化策略

- 聊天历史以业务表为真源
- checkpoint 以 `PostgresSaver` 为运行态快照
- 服务重启后：
  - 前端先回放 PostgreSQL 历史
  - 后端继续用相同 `conversation_id` 驱动 LangGraph

## 验证

- 后端：
  - conversation API 测试
  - LangGraph checkpoint 测试
  - 消息持久化测试
- 前端：
  - chatbox 渲染测试
  - 历史回放测试
  - 发送消息与 AI 回复测试
