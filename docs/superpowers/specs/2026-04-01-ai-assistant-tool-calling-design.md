# AI 助手 LLM 自主工具调用设计

## 背景

当前 AI 助手主链路位于 `backend/app/ai/services/langgraph_assistant.py`，整体思路是：

- 先做规则意图分类
- 再做规则工具识别
- 命中规则工具时由后端直接执行
- 未命中时再进入普通聊天或 RAG 摘要链路

这种设计的核心问题是，工具选择权不在模型，而在后端规则。对于“让大模型自行判断是否需要工具、调用哪个工具、调用几次工具”的目标来说，当前实现与目标不一致。

项目中曾经存在过 LangChain agent 与工具定义雏形，但主链路并未真正接入；迁移完成后，这部分重复实现已删除，避免继续形成第二套能力来源。

本次设计要把 AI 助手改成真正的 tool-calling assistant：

- 工具 schema 直接交给模型
- 由模型判断是否调用工具
- 支持单轮内多工具串联
- 工具失败后允许模型自纠一次
- 不再依赖规则工具分流

## 目标

本次改造完成后，AI 助手应具备以下能力：

- 所有可用工具都直接暴露给模型，由模型自行决定是否调用
- 支持单轮对话内连续调用多个工具
- 工具执行失败时，把结构化错误回填给模型，允许模型重试一次
- LangGraph 主图收敛为通用 agent loop，不再按 `intent` 做工具分流
- SSE 可以向前端暴露工具执行过程
- 最终响应不再强依赖 `Intent.general_chat / rag_retrieval / generate_xml`

## 非目标

本次不做以下内容：

- 基于数据库的动态工具注册、租户化工具配置、运营后台管理工具
- 规则兜底式工具选择
- 多次模型自纠或无限重试
- 新增独立 Agent 框架或引入第二套主执行栈
- 工具市场、MCP 动态注册或远程插件系统

## 设计原则

- 模型负责决策，后端负责执行边界与可观测性
- 工具定义集中管理，不允许 schema、执行逻辑、返回结构分散在多个文件里
- 先兼容现有 API 与 SSE，再逐步移除 `intent` 驱动
- 不为本次改造引入新的顶层框架，优先复用现有 OpenAI client 与 LangGraph 骨架

## 总体架构

### 主链路

LangGraph 主流程从当前的多分支图收敛成四个节点：

1. `load_history`
2. `run_agent_loop`
3. `build_response`
4. `persist_message`

流程如下：

```text
START
  -> load_history
  -> run_agent_loop
  -> build_response
  -> persist_message
  -> END
```

其中：

- `load_history` 负责加载最近会话消息
- `run_agent_loop` 负责向模型提交 `messages + tools`，执行工具调用循环
- `build_response` 负责组装最终 API 响应与 SSE 结束态
- `persist_message` 负责把最终结果写入会话消息表

### Agent Loop

`run_agent_loop` 内部不再拆成多个 LangGraph 节点，而是在单节点内执行工具调用循环。这样工具是否调用、调用顺序、是否继续调用，全部由模型决定。

单轮流程如下：

1. 组装 `system + history + current user + prior tool results`
2. 把 `messages + tools schema` 发送给模型
3. 如果模型返回普通文本且没有 tool call，则结束
4. 如果模型返回一个或多个 tool call，则逐个执行
5. 把每个工具结果作为 tool message 回填给模型
6. 若工具失败，则把结构化错误回填给模型，允许一次自纠
7. 达到工具轮次上限或模型给出最终文本后结束

## 工具注册与执行模型

### 工具注册表

所有工具都定义在代码内的静态工具注册表中，不存数据库。每个工具必须在同一处声明以下内容：

- `name`
- `description`
- `input_schema`
- `executor`
- `result_formatter`
- `reference_mapper`
- `exposed`

推荐新增：

- `backend/app/ai/services/tool_registry.py`

工具注册表是真正的“可调用能力边界”，而不是业务数据。数据库只负责保存调用结果或会话消息，不负责保存工具协议本身。

### 工具执行器

推荐新增：

- `backend/app/ai/services/tool_executor.py`

执行器统一负责：

- 参数校验
- 查找工具定义
- 调用底层 service
- 捕获异常
- 生成标准化结果
- 生成 `tool_trace`

标准工具结果格式固定为：

```json
{
  "ok": true,
  "data": {}
}
```

或

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "upload_id is required",
    "retryable": true
  }
}
```

### 首批暴露给模型的工具

第一批工具包括：

- `query_users`
- `list_recent_files`
- `get_file_detail`
- `search_knowledge_base`
- `generate_xml_placeholder`

其中：

- `query_users` 绑定 `WorkService.queryUsers()`
- `list_recent_files` / `get_file_detail` 绑定 `UploadService`
- `search_knowledge_base` 绑定 `AIRagService.retrieve(...)`
- `generate_xml_placeholder` 继续作为占位能力，但也通过模型工具调用触发

对外暴露的工具命名必须保持业务语义明确，例如统一使用 `query_users`，而不是保留历史性的测试命名。

## 响应结构

### 设计动机

本次改造后，单轮回答可能包含：

- 纯自然语言回答
- RAG 检索结果
- 文件详情
- 多工具串联后的综合结论

继续使用单一 `intent` 来驱动前后端会越来越别扭，因此响应结构需要从“强分类”改成“弱分类、强事实”。

### 建议结构

最终响应建议以以下字段为中心：

- `answer`
- `message`
- `references`
- `tool_trace`

其中：

- `answer` 是最终给用户的自然语言结果
- `message` 是系统提示、降级说明或异常提示
- `references` 是前端可展示的文件、片段、工具结果摘要
- `tool_trace` 是过程追踪，用于调试、可观测性和前端过程面板

迁移期可以保留旧 `intent` 字段做兼容，但主逻辑不得再依赖它做工具路由。

## SSE 事件设计

当前 SSE 机制已经存在，后续保留事件框架，但语义调整为以 tool-calling 为中心。

建议保留四类事件：

- `assistant_start`
- `assistant_debug`
- `assistant_delta`
- `assistant_done`

其中：

- `assistant_start` 表示本轮 agent loop 开始
- `assistant_debug` 表示工具执行过程
- `assistant_delta` 只承载最终自然语言的增量输出
- `assistant_done` 返回最终持久化消息

`assistant_debug` 建议统一使用如下事件体：

```json
{
  "stage": "tool_start",
  "tool_name": "get_file_detail",
  "tool_args": {
    "upload_id": 123
  },
  "message": "正在获取文件详情"
}
```

当前实现中的 `stage` 包括：

- `tool_start`
- `tool_result`

前端应将工具过程作为独立面板或可折叠区展示，而不是把原始 JSON 混入最终聊天文本。

## 状态设计

`AiAssistantState` 建议调整为以 agent loop 为中心，核心字段包括：

- `conversation_id`
- `query`
- `user_id`
- `stream`
- `history_messages`
- `agent_messages`
- `tool_trace`
- `references`
- `answer`
- `message`
- `response_streamed`
- `response`
- `assistant_message`

新增字段作用如下：

- `agent_messages`：保存 agent loop 中完整的模型消息与 tool message
- `tool_trace`：保存本轮工具调用轨迹
- `references`：保存用于前端展示的引用信息

## 文件级改动方案

### 保留的文件

以下文件保留原有业务职责，不承担模型决策：

- `backend/app/services/upload_service.py`
- `backend/app/services/work_service.py`
- `backend/app/ai/services/ai_rag_service.py`
- `backend/app/api/routes/ai.py`

### 需要重写的文件

- `backend/app/ai/services/langgraph_assistant.py`

该文件需要移除以下设计：

- `classify_intent`
- `detect_tool_request`
- `_resolve_tool_request`
- `_invoke_tool_node`
- 基于 `Intent` 的工具路由

并替换为：

- `load_history`
- `run_agent_loop`
- `build_response`
- `persist_message`

### 建议新增的文件

- `backend/app/ai/services/tool_registry.py`
- `backend/app/ai/services/tool_executor.py`
- `backend/app/ai/services/tool_models.py`

### 已移除的重复实现

主链路切换到原生 OpenAI tool-calling 后，以下 LangChain 遗留文件已经移除，避免继续保留第二套未接线运行时：

- `backend/app/ai/services/langchain_agent_factory.py`
- `backend/app/ai/services/langchain_tools.py`

### 需要联动修改的文件

- `backend/app/schemas/ai.py`
- `backend/app/ai/services/ai_conversation_service.py`
- 前端 AI SSE 消费与消息渲染相关文件

## 错误处理与停止条件

### 错误处理

本次明确不做规则兜底。工具执行失败后，后端仅做以下处理：

1. 把错误包装为标准化错误对象
2. 回填给模型
3. 允许模型基于错误自纠一次

不允许失败后再走 `_resolve_tool_request` 一类规则补救。

### 停止条件

`run_agent_loop` 需要显式限制：

- 最大工具轮次，例如 `max_tool_rounds = 4`
- 单次工具失败后的最大模型自纠次数，例如 `1`

满足任意条件即停止：

- 模型返回最终文本且没有新 tool call
- 工具轮次达到上限
- 自纠次数达到上限
- 模型返回空文本且无 tool call

## 迁移步骤

建议按以下顺序迁移，避免一次性推翻主链路：

1. 抽离工具注册表，不改 API 接口
2. 实现统一工具执行器
3. 在 `langgraph_assistant.py` 中新增 `run_agent_loop`
4. 增加响应结构兼容层，短期保留旧字段
5. 切换主链路为 agent loop
6. 清理旧规则节点与 LangChain 遗留文件

迁移期间优先保证：

- SSE 持续可用
- 会话消息持久化不回归
- 前端可以逐步切换，而不是与后端同日强绑定上线

## 测试策略

### 单元测试

- 工具 schema 是否正确
- 工具参数校验是否生效
- 工具成功和失败返回是否符合统一结构
- `build_response` 是否能正确组装 `references` 和 `tool_trace`

### 集成测试

至少覆盖以下请求：

- “查询用户”
- “最近上传了哪些文件”
- “upload_id 123 的文件状态”
- “根据制度手册总结请假流程”
- “生成 XML”

测试重点不是文本内容本身，而是：

- 模型是否通过 tool-calling 触发能力
- 是否支持多工具串联
- 工具失败后是否只允许一次自纠

### 端到端测试

- SSE 事件顺序是否稳定
- 前端是否能看到工具执行过程
- 最终消息是否正确落库

## 验收标准

本次改造完成后，应满足以下条件：

- 后端不再存在规则工具入口作为主链路
- 主链路的工具选择全部来自模型 tool-calling
- 支持单轮多工具串联
- 工具失败后允许一次模型自纠
- SSE 可向前端暴露工具执行过程
- 最终响应不再强依赖 `intent`
- 自动化测试覆盖核心工具调用场景

## 结论

本次改造的核心不是“增加几个工具”，而是把 AI 助手的控制模型从“后端规则分流”切换为“LLM 决策、后端执行”。LangGraph 继续负责编排与持久化，但工具选择权、调用顺序和组合方式都交给模型。这更符合 AI 助手的产品初衷，也为后续扩展更多能力提供了统一基础。
