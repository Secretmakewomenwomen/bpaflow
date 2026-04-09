# Backend AI Stream 服务架构与 ReAct 实现梳理

## 文档目的

这份文档专门梳理 `backend` 目录中的后端 AI 服务，重点回答下面几个问题：

- 用户通过 stream 提问时，请求从哪里进入
- 后端内部有哪些核心服务、各自职责是什么
- 一次完整请求在服务内部如何流转
- 当前实现里的 ReAct 是怎么落地的
- LangGraph、MCP、RAG、会话持久化分别处在什么位置

本文基于当前仓库源码梳理，时间为 `2026-04-08 12:39:01 CST`。

---

## 一句话结论

这个后端 AI 服务不是“前端直连大模型”的简单聊天接口，而是一个分层的 Agent 编排系统：

1. HTTP 层通过 FastAPI 提供 `/api/ai/.../messages/stream` SSE 接口。
2. 编排层用 `LangGraphAssistantService` 把一次请求拆成“加载历史 -> 运行 agent loop -> 构建响应 -> 持久化消息”四个节点。
3. Agent 层由 `AgentFacade + LangGraphAgentRuntime` 执行 ReAct 风格循环。
4. 模型调用和工具调用都被 MCP 化：
   - 模型调用走 `/api/mcp/llm-gateway`
   - 工具调用走 `/api/mcp/rag`、`/api/mcp/business-tools`、`/api/mcp/memory`
5. 结果最终回写到会话消息表，stream 过程中的中间事件则通过 SSE 持续推给前端。

换句话说，外面看起来是一个流式聊天接口，里面其实是一个“LangGraph 驱动的 ReAct agent + MCP 工具系统 + 会话持久化”的组合。

---

## 代码目录里的核心角色

### 1. 接口入口层

- `backend/app/api/routes/ai.py`
- `backend/app/main.py`

职责：

- 对外暴露 AI 会话接口
- 提供 stream SSE 输出
- 初始化 AI 相关基础设施

### 2. 会话持久化层

- `backend/app/ai/services/ai_conversation_service.py`
- `backend/app/schemas/ai.py`

职责：

- 创建会话
- 持久化用户消息和 assistant 消息
- 把引用、工具 trace、pending action、artifact 等结构化信息写入数据库

### 3. LangGraph 编排层

- `backend/app/ai/services/langgraph_assistant.py`

职责：

- 定义 LangGraph 状态图
- 调用 agent loop
- 把 graph 内部事件转换为前端可消费的 SSE 事件
- 用 Postgres checkpointer 维护 thread 级可恢复执行

### 4. Agent 门面层

- `backend/app/ai/agent/facade.py`

职责：

- 组装 runtime、tool dispatcher、memory、termination、guardrails、tracer
- 处理 flow-chart interrupt/resume 等业务特殊分支
- 将 runtime 产物组装成统一 `AssistantResponse`

### 5. ReAct Runtime 层

- `backend/app/ai/agent/runtime/langgraph_runtime.py`
- `backend/app/ai/agent/reasoning/engine.py`
- `backend/app/ai/agent/reasoning/parser.py`
- `backend/app/ai/agent/reasoning/prompt_builder.py`

职责：

- 驱动一轮轮“思考 -> 工具调用 -> 观察 -> 再思考”
- 兼容 OpenAI tool-calling 和 legacy 文本 ReAct
- 生成 reasoning trace / tool trace

### 6. 工具分发与 MCP 层

- `backend/app/ai/agent/tools/registry.py`
- `backend/app/ai/agent/tools/dispatcher.py`
- `backend/app/ai/services/mcp_llm_proxy_client.py`
- `backend/app/api/routes/mcp_llm_gateway.py`
- `backend/app/api/routes/mcp_rag.py`
- `backend/app/api/routes/mcp_business_tools.py`
- `backend/app/api/routes/mcp_memory.py`

职责：

- 维护工具 schema
- 统一转发工具调用到 MCP server
- 把模型调用也包装成 MCP tool

### 7. 状态、终止与追踪层

- `backend/app/ai/agent/state/manager.py`
- `backend/app/ai/agent/memory/manager.py`
- `backend/app/ai/agent/termination/controller.py`
- `backend/app/ai/agent/tracing/tracer.py`

职责：

- 管理 session/step/tool_call/tool_observation 状态
- 控制死循环和重复调用
- 将执行过程写入 trace 表

---

## Stream 请求的主链路

下面先看用户通过 stream 提问时的主链路。

### Step 1. 前端调用 stream 接口

入口在 `backend/app/api/routes/ai.py`：

- 路由：`POST /api/ai/conversations/{conversation_id}/messages/stream`
- 方法：`stream_ai_conversation_message`

这个接口做了两件事：

1. 先调用 `AiConversationService.create_user_message(...)`，把用户这条消息立即落库。
2. 再进入一个 Python generator，在 generator 中调用 `LangGraphAssistantService.stream_invoke(...)`，把内部事件包装成 SSE。

SSE 封装格式由 `_format_sse(event, data)` 完成，最后通过 `StreamingResponse(..., media_type="text/event-stream")` 输出。

当前这层对前端暴露的事件类型至少包括：

- `user_message`
- `assistant_start`
- `assistant_reasoning`
- `assistant_debug`
- `assistant_delta`
- `assistant_done`
- `error`

这里要注意一个设计点：

用户消息是“先落库，再开始推理”，所以就算后面 agent 执行失败，用户问题本身也已经保存在历史会话里。

---

## LangGraph 编排层怎么接住 stream 请求

核心类是 `backend/app/ai/services/langgraph_assistant.py` 中的 `LangGraphAssistantService`。

### 1. 它不是直接写业务逻辑，而是先定义一张图

`_create_graph_definition()` 里定义了 4 个节点：

1. `load_history`
2. `run_agent_loop`
3. `build_response`
4. `persist_message`

边的顺序非常清晰：

`START -> load_history -> run_agent_loop -> build_response -> persist_message -> END`

这说明当前 stream AI 服务的主流程不是“很多 if/else 拼一起”，而是一个很收敛的 LangGraph 状态图。

### 2. graph state 里保存了什么

`AiAssistantState` 是一份 TypedDict，里面包含：

- 请求基础信息：`conversation_id`、`query`、`user_id`
- 上下文：`history_messages`
- agent 中间产物：`tool_trace`、`reasoning_trace`、`snippets`、`references`
- 最终产物：`response`、`assistant_message`
- stream 控制字段：`stream`、`response_streamed`
- 特殊交互字段：`pending_action`、`artifact`、`actions`

也就是说，LangGraph 在这里承担的是“状态收束器”的角色，把请求从输入一路带到可持久化的结构化结果。

### 3. stream 模式怎么输出中间事件

`LangGraphAssistantService.stream_invoke()` 本身不直接执行所有逻辑，而是委托给 `AgentFacade.stream_invoke(...)`。

graph 执行时使用：

- `stream_mode=["custom", "updates"]`

这两个 mode 分工很明确：

- `custom`：运行过程中的自定义事件，例如 `assistant_reasoning`、`assistant_delta`、`assistant_debug`
- `updates`：节点状态更新，例如最终的 `assistant_message` 或 interrupt 信息

这意味着 SSE 并不是从 OpenAI token 直接透传，而是从 LangGraph 自定义事件流中统一抽象出来的。

---

## 请求执行的完整时序

下面用时序方式把链路拉直。

### 1. HTTP 入口

前端
-> `POST /api/ai/conversations/{id}/messages/stream`
-> `stream_ai_conversation_message`

### 2. 立即落库用户消息

`stream_ai_conversation_message`
-> `AiConversationService.create_user_message`
-> 写入 `ai_message(role=user)`

然后 SSE 先发出：

- `event: user_message`

### 3. 进入 LangGraph

`stream_ai_conversation_message`
-> `LangGraphAssistantService.stream_invoke`
-> `AgentFacade.stream_invoke`
-> `graph.stream(...)`

graph 配置里把：

- `thread_id = conversation_id`

因此同一个 conversation 对应 LangGraph 的同一条执行线程。

### 4. 节点一：加载历史

`load_history`
-> `AiConversationService.get_recent_messages`

这里会拉最近若干条历史消息，数量由配置项 `assistant_max_context_blocks` 控制。

### 5. 节点二：运行 agent loop

`run_agent_loop`
-> `AgentFacade.run_agent_loop`
-> `LangGraphAgentRuntime.run`

这一步是核心。

### 6. 节点三：构建统一响应

`build_response`
-> `AgentFacade.build_response`
-> 生成 `AssistantResponse`

如果前面还没有增量输出完整文本，这里会补发一次 `assistant_delta`。

### 7. 节点四：持久化 assistant 消息

`persist_message`
-> `AiConversationService.create_assistant_message`
-> 写入 `ai_message(role=assistant)` 和引用表

### 8. LangGraph 流结束

`AgentFacade.stream_invoke`
-> SSE 发出 `assistant_done`

最终前端拿到完整 assistant 消息对象。

---

## 服务架构分层图

可以把当前实现理解为下面五层。

### 第一层：API / SSE 层

职责：

- 接受前端 HTTP 请求
- 输出 SSE 事件流

核心代码：

- `backend/app/api/routes/ai.py`

### 第二层：LangGraph 编排层

职责：

- 组织节点
- 管理 graph state
- 连接 checkpointer

核心代码：

- `backend/app/ai/services/langgraph_assistant.py`

### 第三层：Agent Runtime 层

职责：

- 执行 ReAct 循环
- 管理决策、工具调用、观察、自纠、终止

核心代码：

- `backend/app/ai/agent/facade.py`
- `backend/app/ai/agent/runtime/langgraph_runtime.py`

### 第四层：MCP 工具和模型代理层

职责：

- 把模型调用标准化为 MCP tool
- 把业务工具统一转发到 MCP server

核心代码：

- `backend/app/ai/services/mcp_llm_proxy_client.py`
- `backend/app/ai/agent/tools/dispatcher.py`
- `backend/app/api/routes/mcp_*.py`

### 第五层：数据与持久化层

职责：

- 保存会话、消息、引用
- 保存 graph checkpoint
- 保存 agent trace
- 提供 RAG 检索数据来源

核心代码：

- `backend/app/ai/services/ai_conversation_service.py`
- `backend/app/ai/agent/tracing/tracer.py`
- `backend/app/core/config.py`

---

## ReAct 在这里到底怎么实现

这一部分是重点。

结论先说清楚：

当前实现不是纯文本版 ReAct，也不是纯 OpenAI tool-calling，而是一个“双模兼容”的实现：

1. 优先使用 OpenAI 风格 `tool_calls`
2. 如果没有 `tool_calls`，再兼容解析 legacy 文本 ReAct

也就是“tool-calling 优先，文本 ReAct 兜底”。

### 1. PromptBuilder 负责给模型设定推理协议

`backend/app/ai/agent/reasoning/prompt_builder.py`

这里有两套规则：

- `DEFAULT_SYSTEM_RULES`
- `TEXT_REACT_PROTOCOL_RULES`

默认规则会告诉模型：

- 正常问题直接回答
- 需要查资料时使用工具
- 检索问题优先一次 `search_knowledge_base`
- 不要对同参数重复调用工具
- 多主题问题先汇总候选再综合回答

而文本 ReAct 模式下，会额外要求模型按这种格式输出：

- `Thought: ...`
- `Action: {"tool_name":"...", "tool_args": {...}}`

或者：

- `Thought: ...`
- `Final Answer: ...`

这就是经典 ReAct 协议。

### 2. ReasoningEngine 负责把模型输出判定成“下一步动作”

`backend/app/ai/agent/reasoning/engine.py`

核心方法是 `decide(...)`。

它的执行顺序是：

1. 用 `PromptBuilder.build_messages(...)` 组 prompt
2. 调用 `client.chat.completions.create(...)`
3. 读取第一条 choice 的 message
4. 优先解析 `tool_calls`
5. 如果没有 tool_calls，再尝试解析文本里的：
   - `Thought:`
   - `Action:`
   - `Final Answer:`

最后把结果转换成 `AgentDecision`，其 `decision_type` 主要有：

- `tool_call`
- `final_answer`
- `tool_arguments_error`
- `decision_error`

所以 ReasoningEngine 在架构上的作用，是把“模型输出”翻译成“runtime 可执行决策”。

### 3. Runtime 负责执行 ReAct 循环

`backend/app/ai/agent/runtime/langgraph_runtime.py`

`run(...)` 就是 ReAct 主循环。

它的抽象可以写成下面这样：

```text
for step in max_turns:
    1. 调模型做决策
    2. 如果是 Final Answer，结束
    3. 如果是 Tool Call，执行工具
    4. 把 Observation 追加回 messages
    5. 进入下一轮决策
```

这就是典型 ReAct：

- Reason：模型产生 `thought`
- Act：模型发起 `tool_call`
- Observe：runtime 执行工具并把结果回灌
- Reason again：模型基于 observation 继续思考

### 4. 为什么说它是真正“回灌 observation”的 ReAct

在 tool_call 分支里，runtime 会把两类消息追加到内部 `messages`：

1. 一条 `assistant` 消息，里面带本轮 `tool_calls`
2. 一条或多条 `tool` 消息，内容是工具执行结果 `observation_content`

也就是说，下一轮模型看到的上下文不是“只有最终答案”，而是：

- 上一轮 assistant 发起了什么工具调用
- 每个工具返回了什么 observation

这正是 ReAct 的核心闭环，而不是单轮函数调用。

### 5. 文本 ReAct 是怎么兼容的

`backend/app/ai/agent/reasoning/parser.py` 中定义了三个关键解析器：

- `extract_legacy_react_thought`
- `extract_legacy_react_action`
- `extract_legacy_react_final_answer`

它们会从文本里匹配：

- `Thought: ...`
- `Action: {...}`
- `Final Answer: ...`

因此如果上游模型不返回标准 tool_calls，但还能遵守文本协议，runtime 仍然可以继续执行。

### 6. 工具参数错误时的自纠机制

runtime 不是“一错就死”，而是允许一次模型自纠。

当出现：

- tool 参数 JSON 解析失败
- guardrail 拒绝
- MCP 返回 `INVALID_ARGUMENT`

runtime 会构造一条工具错误 observation，再继续一轮，让模型自己修正一次调用。

如果再次失败，或者错误本身是非 retryable，则直接终止。

这部分属于 ReAct 的“self-correction”增强实现。

### 7. ReAct 的输出如何映射到前端可见信息

runtime 会把内部过程转成两类 trace：

- `reasoning_trace`
- `tool_trace`

其中 `reasoning_trace` 里的 step_type 包括：

- `thought`
- `action`
- `observation`

stream 模式下，这些 step 会以 `assistant_reasoning` 事件实时推给前端。

所以前端如果愿意，完全可以把这条请求的推理轨迹展示出来。

---

## ReAct 请求在代码中的真实执行顺序

下面把关键代码动作映射为真实步骤。

### 阶段 A. 组装消息

runtime 首先用 `PromptBuilder.build_messages(...)` 生成初始消息列表：

- system rules
- 最近历史消息
- 当前用户 query

### 阶段 B. 向模型请求决策

通过 `ReasoningEngine.decide(...)` 调用模型。

这里的模型客户端不是 OpenAI 原生 client，而是：

- `McpLlmProxyClient`

也就是说，这一步实际是：

runtime
-> MCP llm proxy client
-> `/api/mcp/llm-gateway`
-> `LlmGatewayService`
-> OpenAI-compatible 上游模型

### 阶段 C. 解析模型返回

解析结果分三种主情况：

1. `tool_call`
2. `final_answer`
3. `tool_arguments_error`

如果是 `final_answer`，本轮结束。

### 阶段 D. 执行工具

如果是 `tool_call`：

runtime
-> `ToolDispatcher.execute`
-> 根据工具名映射到 MCP server

映射关系在 `backend/app/ai/agent/tools/dispatcher.py`：

- `search_knowledge_base` -> `rag`
- `query_users` / `list_recent_files` / `get_file_detail` -> `business_tools`
- `memory_*` -> `memory`
- `chat_completion` / `stream_completion` -> `llm_gateway`

### 阶段 E. 生成 observation

工具执行结果会被整理成：

- `ok/data`
- 或 `ok=false/error`

然后序列化成 `tool` role message 追加回 `messages`。

同时 runtime 会记录：

- `tool_trace`
- `reasoning_trace` 中的 `observation`
- trace 表中的 `action` / `observation`

### 阶段 F. 下一轮推理

模型再次看到：

- 自己刚才发起的工具调用
- 刚才拿到的工具 observation

然后继续决定：

- 继续调用工具
- 还是直接输出 Final Answer

直到满足终止条件。

---

## 为什么这里说是“LangGraph 外壳 + ReAct 内核”

这个问题很容易在看代码时混淆。

### LangGraph 管什么

LangGraph 负责：

- 整体节点编排
- 线程级 checkpoint
- interrupt / resume
- 流事件聚合

也就是“宏观工作流”。

### ReAct runtime 管什么

ReAct runtime 负责：

- 一轮轮 thought / action / observation 的闭环
- 工具调用和 observation 回灌
- 终止和自纠

也就是“单个 agent 节点内部的微观推理循环”。

所以这套实现不是二选一，而是：

- LangGraph 解决外层工作流与可恢复执行
- ReAct 解决内层推理与工具使用

---

## MCP 在这套架构里的位置

这是当前实现的一个很关键的架构选择。

### 1. 模型能力被 MCP 化

`backend/app/ai/services/mcp_llm_proxy_client.py`

runtime 调用的虽然是 `client.chat.completions.create(...)`，但背后其实会被转换成 MCP JSON-RPC：

- tool 名：`chat_completion`
- endpoint：`/api/mcp/llm-gateway`

也就是说：

模型本身在这套系统里被当成一个 MCP tool server 使用。

### 2. 业务工具也被 MCP 化

`ToolDispatcher` 不直接调 service 方法，而是统一发往各自 MCP endpoint。

这样做的好处是：

- 工具调用协议统一
- user_id / tenant_id / session_id / trace_id 上下文统一通过 header 注入
- 后续如果工具拆到独立服务，agent 层不用大改

### 3. 当前已接入的 MCP server

- `/api/mcp/llm-gateway`
- `/api/mcp/rag`
- `/api/mcp/business-tools`
- `/api/mcp/memory`

### 4. 这意味着什么

从架构视角看，当前 backend AI 服务其实是一个“agent orchestrator”：

- 它自己不直接做所有事
- 它负责驱动模型做决策
- 再通过 MCP 统一调模型能力和外部工具能力

---

## RAG 在整个链路中的位置

RAG 不是主流程之外的一块外挂，而是当前 agent 最核心的工具之一。

### 1. RAG 工具定义

在 `backend/app/ai/agent/tools/registry.py` 中，`search_knowledge_base` 被注册成工具。

参数大致为：

- `query`
- `top_k`

### 2. RAG 工具实际调用

runtime 决策出 `search_knowledge_base`
-> `ToolDispatcher`
-> `/api/mcp/rag`
-> `AIRagService.retrieve(...)`

### 3. 为什么这个工具很特殊

在 `LangGraphAgentRuntime.run()` 中，如果工具名是 `search_knowledge_base`，其结果会被提升为 `retrieval_response`。

后面当模型给出 `final_answer` 时：

- 如果存在 `retrieval_response`
  -> 最终 intent 被标记为 `rag_retrieval`
  -> 响应携带 `references`、`snippets`、`related_files`
- 否则
  -> 视为 `general_chat`

所以当前实现里，RAG 不只是一个普通工具调用，它会直接影响最终响应类型和响应结构。

---

## flow chart interrupt/resume 是怎么嵌进去的

`backend/app/ai/agent/facade.py`

在正式进入 runtime 前，`run_agent_loop(...)` 会先执行：

- `_maybe_interrupt_flow_chart_generation(...)`

如果用户问题被识别为“根据文件生成流程图”，并且匹配到候选文件，就不会立即进入普通 ReAct loop，而是先返回：

- `status = waiting_input`
- `pending_action = select_file`

这套机制使用了 LangGraph 的 `interrupt(...)` 能力。

恢复时走：

- `POST /api/ai/conversations/{conversation_id}/messages/resume`

恢复逻辑位于：

- `LangGraphAssistantService.resume_flow_chart_generation(...)`

说明这套 AI 后端除了普通 stream 问答，也已经支持“中途挂起，等用户选择后继续”的多阶段交互。

---

## 状态管理、死循环保护和 trace

### 1. AgentStateManager

`backend/app/ai/agent/state/manager.py`

它维护的不是简单的“当前消息”，而是完整 session state：

- `session_id`
- `step_count`
- `steps`
- `tool_history`
- `observations`
- `last_tool_call`
- `repeated_action_count`
- `consecutive_empty_steps`

这为终止控制提供了基础。

### 2. TerminationController

`backend/app/ai/agent/termination/controller.py`

当前会在以下场景终止：

- 达到最大步数 `max_steps`
- 重复调用次数过多
- 连续空步过多
- 已生成 final response
- 正在等待用户输入

这能防止模型陷入无意义工具循环。

### 3. SqlAlchemyAgentTracer

`backend/app/ai/agent/tracing/tracer.py`

它会将以下阶段写入 trace 表：

- `reason`
- `action`
- `observation`
- `termination`

因此从审计视角看，这套 agent 运行过程是可回放、可排查的，不只是最终结果可见。

---

## stream 事件设计说明

从当前实现看，前端看到的流并不是“底层模型 token 原样透传”，而是“后端加工后的结构化事件”。

### 事件大致可以分三类

#### 1. 生命周期事件

- `assistant_start`
- `assistant_done`
- `error`

#### 2. 推理事件

- `assistant_reasoning`
- `assistant_debug`

#### 3. 文本输出事件

- `assistant_delta`

### 这种设计的好处

- 前端可以做纯聊天模式，只消费 `assistant_delta`
- 也可以做可解释模式，同时展示 reasoning / tool 状态
- 即便未来底层模型更换，前端协议仍然稳定

---

## 配置层怎么看这套架构

`backend/app/core/config.py`

可以看出这套系统的关键配置分为三组：

### 1. RAG 配置

- `assistant_retrieval_top_k`
- `assistant_max_related_files`
- `assistant_enable_bm25`
- `assistant_vector_weight`
- `assistant_bm25_weight`
- `assistant_rule_weight`

### 2. LLM / MCP 配置

- `assistant_llm_base_url`
- `assistant_llm_api_key`
- `assistant_llm_model`
- `assistant_mcp_rag_url`
- `assistant_mcp_memory_url`
- `assistant_mcp_llm_gateway_url`
- `assistant_mcp_business_tools_url`

### 3. agent 行为配置

- `assistant_max_context_blocks`
- `assistant_mcp_request_timeout_seconds`
- `assistant_mcp_llm_timeout_seconds`

这说明当前系统设计上已经把“模型、工具、检索”拆成可配置基础设施，而不是硬编码在业务代码里。

---

## 这套后端 AI 服务的关键设计判断

### 1. 它不是一个单 Service 大函数

而是：

- API 路由层
- LangGraph 编排层
- Agent runtime 层
- MCP 层
- 数据/追踪层

职责边界相对清晰。

### 2. 它也不是“纯 LangGraph”

LangGraph 在这里主要做工作流壳子和 checkpoint；
ReAct 的真正闭环在 `LangGraphAgentRuntime` 里。

### 3. 模型和工具都被协议化了

通过 MCP，模型调用和工具调用都走统一协议，这对后续服务拆分很有利。

### 4. 当前 stream 是后端编排流，不是上游模型原生流

目前真正决定 agent 行为的是 `chat_completion` 决策调用；
SSE 里输出的 `assistant_delta` 主要来自 runtime/response 拼装，而不是始终直接透传上游 streaming token。

### 5. 当前 ReAct 已具备工程化能力

不是停留在 prompt 层面的“让模型按 Thought/Action 输出”，而是有：

- action/observation 回灌
- 工具参数校验
- guardrail
- 一次自纠
- step 终止控制
- trace 持久化

这已经是可落地的 agent runtime 了。

---

## 最后给你的结论版理解

如果你要向别人解释这套 backend AI 服务，可以直接这样说：

> 用户发起 stream 提问后，请求先进入 FastAPI 的 `/api/ai/conversations/{id}/messages/stream`，后端先把用户消息落库，然后交给 `LangGraphAssistantService`。这个 service 用 LangGraph 把流程拆成加载历史、运行 agent、构建响应、持久化消息四个节点。真正的 agent 推理在 `LangGraphAgentRuntime` 里执行，它实现的是一套 ReAct 风格循环：模型先做决策，如果需要工具，就通过 MCP 调用 RAG、文件、用户、memory 等工具，再把 observation 回灌给模型继续推理，直到输出 final answer。模型本身也不是直接调用，而是通过 MCP 的 `llm-gateway` 代理成统一协议。最后 assistant 消息和引用关系持久化到数据库，过程中产生的 reasoning、delta、done 等事件通过 SSE 持续返回给前端。整个系统的特点是：LangGraph 管外层编排，ReAct 管内层推理，MCP 统一模型和工具协议，数据库同时承担会话、引用、trace 和 checkpoint 持久化。

---

## 关键源码索引

- Stream 入口：`backend/app/api/routes/ai.py`
- 应用启动与路由挂载：`backend/app/main.py`
- 会话与消息持久化：`backend/app/ai/services/ai_conversation_service.py`
- LangGraph 编排：`backend/app/ai/services/langgraph_assistant.py`
- Agent 门面：`backend/app/ai/agent/facade.py`
- ReAct runtime：`backend/app/ai/agent/runtime/langgraph_runtime.py`
- 决策引擎：`backend/app/ai/agent/reasoning/engine.py`
- ReAct 文本解析：`backend/app/ai/agent/reasoning/parser.py`
- Prompt 构建：`backend/app/ai/agent/reasoning/prompt_builder.py`
- 工具注册：`backend/app/ai/agent/tools/registry.py`
- 工具分发：`backend/app/ai/agent/tools/dispatcher.py`
- 模型 MCP 代理：`backend/app/ai/services/mcp_llm_proxy_client.py`
- LLM gateway 路由：`backend/app/api/routes/mcp_llm_gateway.py`
- RAG MCP 路由：`backend/app/api/routes/mcp_rag.py`
- 业务工具 MCP 路由：`backend/app/api/routes/mcp_business_tools.py`
- Memory MCP 路由：`backend/app/api/routes/mcp_memory.py`
- 状态管理：`backend/app/ai/agent/state/manager.py`
- 终止控制：`backend/app/ai/agent/termination/controller.py`
- Trace 持久化：`backend/app/ai/agent/tracing/tracer.py`
- 配置：`backend/app/core/config.py`
