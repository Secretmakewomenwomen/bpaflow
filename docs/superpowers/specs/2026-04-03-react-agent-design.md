# AI 助手标准 ReAct Agent 架构设计

## 背景

当前 AI 助手主链路集中在 `backend/app/ai/services/langgraph_assistant.py`。虽然已经具备：

- 基于 OpenAI tool calling 的工具调用能力
- LangGraph 驱动的 streaming 与 checkpoint
- 会话消息持久化
- 文件选择类 human-in-the-loop 中断能力

但现有实现仍然是“一个 service 承载几乎所有职责”的形态，存在明显工程问题：

- Prompt、状态推进、工具协议、工具执行、错误恢复、终止判断、trace 记录耦合在同一类中
- Runtime 内部状态直接混用 API 层的响应模型，边界不清
- Tool registry 与 tool executor 仅有雏形，尚未形成稳定的工程协议
- 终止条件、重试规则、重复 action 限制等安全边界分散在 loop 逻辑里
- 缺少 step 级 trace 持久化，问题排查和后续运营分析能力不足

从工程视角看，当前实现更接近“能工作的 agent loop”，而不是“可持续演进的 ReAct Agent 平台”。

本次设计目标是把 AI 服务升级为标准化、可扩展、可观测、可替换 runtime backend 的 ReAct Agent 架构。

## 目标

本次改造完成后，AI 助手应具备以下能力：

- 形成明确的三层架构：
  - `LLM Layer`
  - `Agent Runtime Layer`
  - `Tool / Environment Layer`
- 以自有 `AgentRuntime` 抽象承载 ReAct 主循环，而不是把架构绑死在 `LangGraph` 上
- 保留 `LangGraph` 作为默认 runtime backend，复用 streaming 与 checkpoint 能力
- 把 Prompt、State、Reasoning、Tool、Guardrails、Termination、Tracer 拆成独立模块
- 保留并迁移当前已有能力：
  - `general_chat`
  - `rag_retrieval`
  - `generate_flow_from_file`
  - 当前已暴露工具
- 具备标准化工具协议：
  - 明确 input schema
  - 明确 output schema
  - 明确错误码与 retryable 语义
  - 明确权限与确认要求
- 具备标准化停止条件：
  - 最大步数限制
  - 重复 action 限制
  - 空转限制
- 具备 step 级 trace 持久化能力
- 保持未来可以新增 `LoopAgentRuntime`，在不改上层接口的前提下替换 LangGraph backend

## 非目标

本次不做以下内容：

- 一次性移除 `LangGraph`
- 引入 multi-agent、planner、plan-execute 等更复杂架构
- 构建完整长期记忆学习系统
- 引入数据库驱动的动态工具市场或运营后台
- 重做前端 AI 消息协议
- 把所有领域服务都重写成统一插件框架

## 设计原则

- 模型负责“建议下一步”，Runtime 负责“决定是否执行”
- `AssistantResponse` 是 API 协议，不是 runtime 内部状态模型
- 工具协议集中管理，不允许 schema、执行、错误结构散落在多个地方
- 短期记忆与长期记忆边界分离，不混用
- 不持久化完整原始 chain-of-thought，仅持久化可审计摘要
- 保持对现有能力的兼容迁移，优先渐进式重构
- 让 `LangGraph` 成为可替换 backend，而不是架构中心

## 方案对比

### 方案一：LangGraph-first 拆分类内逻辑

保留当前 `LangGraphAssistantService` 为核心，只把大方法拆成多个 helper/service。

优点：

- 迁移成本低
- 对现有链路影响最小

缺点：

- Runtime 仍然被单个 service 绑定
- 无法形成清晰的平台接口
- 后续切换到纯自研 runtime 成本仍然很高

### 方案二：Pure runtime

直接移除 LangGraph，完全自研 ReAct loop、state machine、streaming 与 checkpoint。

优点：

- 边界最干净
- 可控性最高

缺点：

- 一次性迁移风险高
- 需要同步重做流式与 checkpoint 能力

### 方案三：自有 Runtime 抽象 + 可插拔 backend

定义自有 `AgentRuntime`、`StateManager`、`ReasoningEngine`、`ToolDispatcher`、`Guardrails`、`TerminationController`、`Tracer` 等核心协议。

底层默认提供：

- `LangGraphAgentRuntime`
- `LoopAgentRuntime` 骨架

当前生产链路先挂 `LangGraphAgentRuntime`，后续可平滑切换到纯 loop backend。

这是本次推荐方案，因为它同时满足：

- 工程上可落地
- 风险可控
- 平台骨架可持续演进

## 总体架构

### 三层分层

#### 1. LLM Layer

负责推理，不直接接触外部系统。

模块包括：

- `PromptBuilder`
- `ReasoningEngine`
- `ReasoningParser`

职责：

- 构造 system prompt、工具协议、输出约束
- 根据压缩后的上下文调用模型
- 把模型输出解析成标准 `AgentDecision`

#### 2. Agent Runtime Layer

负责循环、状态、路由、终止控制。

模块包括：

- `AgentRuntime`
- `StateManager`
- `MemoryManager`
- `Guardrails`
- `TerminationController`
- `Tracer`
- `AgentFacade`

职责：

- 初始化和推进 `AgentSessionState`
- 执行 ReAct step
- 调用 guardrails 和 termination policy
- 记录 trace
- 组装 runtime 结果并映射到 API 层响应

#### 3. Tool / Environment Layer

负责真实外部动作。

模块包括：

- `ToolRegistry`
- `ToolDispatcher`
- `AIRagService`
- `UploadService`
- `WorkService`
- `FlowChartInterruptService`

职责：

- 注册工具及 schema
- 真正执行工具
- 标准化工具返回结构
- 承载业务领域能力

### 分层关系

```text
API / SSE / Resume
  -> AgentFacade
  -> AgentRuntime
  -> StateManager / MemoryManager / Guardrails / TerminationController / Tracer
  -> PromptBuilder / ReasoningEngine / ReasoningParser
  -> ToolRegistry / ToolDispatcher
  -> Domain Services
```

## 目录与模块设计

建议新增目录：

- `backend/app/ai/agent/runtime/`
- `backend/app/ai/agent/state/`
- `backend/app/ai/agent/reasoning/`
- `backend/app/ai/agent/tools/`
- `backend/app/ai/agent/memory/`
- `backend/app/ai/agent/guardrails/`
- `backend/app/ai/agent/termination/`
- `backend/app/ai/agent/tracing/`

建议模块如下：

### Runtime

- `backend/app/ai/agent/runtime/base.py`
  - `AgentRuntime` 抽象接口
- `backend/app/ai/agent/runtime/langgraph_runtime.py`
  - 基于 LangGraph 的默认 runtime backend
- `backend/app/ai/agent/runtime/loop_runtime.py`
  - 纯 loop runtime 骨架，首期不作为默认执行器

### State

- `backend/app/ai/agent/state/models.py`
  - 运行时核心状态模型
- `backend/app/ai/agent/state/manager.py`
  - 状态初始化、恢复、推进、压缩

### Reasoning

- `backend/app/ai/agent/reasoning/prompt_builder.py`
  - system prompt 与工具协议拼装
- `backend/app/ai/agent/reasoning/engine.py`
  - OpenAI 调用封装
- `backend/app/ai/agent/reasoning/parser.py`
  - 决策解析与异常兜底

### Tools

- `backend/app/ai/agent/tools/models.py`
  - 工具协议模型
- `backend/app/ai/agent/tools/registry.py`
  - 工具注册与 schema 暴露
- `backend/app/ai/agent/tools/dispatcher.py`
  - 工具执行与错误标准化

### Memory

- `backend/app/ai/agent/memory/manager.py`
  - 短期记忆实现
  - 长期记忆接口挂点

### Guardrails

- `backend/app/ai/agent/guardrails/policy.py`
  - 参数校验
  - 权限校验
  - 高风险动作确认策略

### Termination

- `backend/app/ai/agent/termination/controller.py`
  - 最大步数
  - 重复 action 限制
  - 空转限制
  - 停止判定

### Tracing

- `backend/app/ai/agent/tracing/tracer.py`
  - step trace 记录与持久化

### Facade

- `backend/app/ai/agent/facade.py`
  - 对上层暴露统一入口
- `backend/app/ai/services/langgraph_assistant.py`
  - 削薄为兼容 facade / adapter

## 核心对象模型

### AgentSessionState

`AgentSessionState` 表示一次 agent 会话的运行状态，建议包含：

- `session_id`
- `conversation_id`
- `user_id`
- `goal`
- `status`
- `step_count`
- `consecutive_empty_steps`
- `repeated_action_count`
- `short_term_memory`
- `long_term_memory_refs`
- `pending_action`
- `final_response`
- `last_decision`

### AgentStepState

`AgentStepState` 表示单个 ReAct step 的状态，建议包含：

- `step_index`
- `prompt_context`
- `decision`
- `tool_calls`
- `tool_results`
- `observation_summary`
- `termination_signal`

### AgentDecision

`ReasoningEngine` 输出统一的 `AgentDecision`：

- `decision_type`
  - `final`
  - `tool_call`
  - `ask_user`
  - `error`
- `thought_summary`
- `final_answer`
- `tool_calls`
- `parse_error`

说明：

- `thought_summary` 是可审计摘要，不是原始 CoT
- `ask_user` 用于进入 `waiting_input` 或二次确认

### ToolDefinition

工具元数据应至少包含：

- `name`
- `description`
- `input_schema`
- `output_schema`
- `idempotent`
- `requires_confirmation`
- `required_scopes`
- `retry_policy`

### ToolCall / ToolResult / ToolError

`ToolCall`：

- `call_id`
- `tool_name`
- `arguments`

`ToolResult`：

- `call_id`
- `ok`
- `data`
- `error`
- `metadata`

`ToolError`：

- `code`
- `message`
- `retryable`
- `category`
  - `validation`
  - `permission`
  - `service`
  - `timeout`
  - `not_found`

### TerminationSignal

停止控制统一输出：

- `should_stop`
- `reason`
- `status`
  - `completed`
  - `waiting_input`
  - `failed`
  - `max_steps`
  - `blocked`
- `user_message`

## 标准 ReAct Step 数据流

每个 step 采用以下流程：

1. `StateManager` 根据当前 session state 产出最小上下文
2. `PromptBuilder` 组装：
   - system prompt
   - 工具协议
   - 压缩后的历史与记忆
   - 当前用户目标
3. `ReasoningEngine` 调用模型，产出 `AgentDecision`
4. 若 decision 为 `tool_call`：
   - `Guardrails` 做参数与权限校验
   - `ToolDispatcher` 执行工具
   - `MemoryManager` 更新 observation 与短期记忆
   - `Tracer` 记录 `reason / action / observation`
5. 若 decision 为 `final` 或 `ask_user`：
   - `TerminationController` 判断是否停止
   - `Tracer` 记录 `termination`
6. Runtime 根据 `TerminationSignal` 决定继续下一步还是返回最终结果

核心原则是：

- 模型不直接操作外部系统
- Runtime 永远有最终执行权
- 工具失败后由 Runtime 决定重试、降级或结束

## Prompt 与上下文控制

### Prompt Layer 目标

Prompt Layer 需要明确三件事：

- 助手角色
- 工具协议
- 输出约束

建议把当前写在 `_build_agent_loop_messages` 里的 system prompt 迁到 `PromptBuilder`，并拆成：

- 基础角色 prompt
- 工具调用规则
- 多主题检索规则
- 错误恢复规则
- 输出格式约束

### 上下文压缩策略

本次首期只做工程上足够稳定的压缩：

- 最近消息窗口
- 当前 step 之前的 observation 摘要
- 最近有效工具结果摘要
- 当前用户问题

不建议把全部会话历史直接塞给模型。

长期记忆在本期只保留接口挂点，不做复杂召回逻辑。

## 工具协议标准化

### 工具注册

当前 `backend/app/ai/services/tool_registry.py` 演进为新 `ToolRegistry`。

要求：

- 所有工具统一在 registry 中注册
- 工具定义必须包含 schema 与执行元数据
- registry 可导出 OpenAI tool schema
- registry 负责把领域 service 与 tool metadata 对齐

### 工具执行

当前 `backend/app/ai/services/tool_executor.py` 演进为新 `ToolDispatcher`。

执行职责包括：

- 参数校验
- 权限上下文注入
- 调用底层 service
- 异常捕获
- 错误标准化
- 结果结构统一化

建议统一返回：

```json
{
  "ok": true,
  "data": {}
}
```

或：

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "upload_id is required",
    "retryable": true,
    "category": "validation"
  }
}
```

## Guardrails 与安全边界

`Guardrails` 负责把“模型想做什么”和“系统允许做什么”分开。

首期至少实现：

- 参数 schema 校验
- 用户上下文校验
- 工具级权限控制
- `requires_confirmation` 工具拦截挂点
- 非法参数或未注册工具的标准错误返回

虽然当前工具多为读取型操作，但框架中应预留对高风险工具的二次确认能力。

## 错误恢复策略

本期错误恢复保持简单且可控：

- 参数错误允许自纠一次
- retryable 工具错误允许一次重试
- 非 retryable 错误直接进入降级回答或失败终止
- 不允许无限循环重试

错误恢复策略不应继续散落在 loop 中，而应成为 runtime policy 的一部分。

## 停止条件

`TerminationController` 必须统一控制：

- 最大步数上限
- 重复 action 次数上限
- 连续空转次数上限
- 进入 `waiting_input` 的停止
- 明确得到 `final` 的停止

本期建议默认值：

- 最大步数：6
- 相同 action 重复上限：2
- 连续空转上限：2

超过上限时，必须返回清晰的降级消息，而不是继续调用模型。

## Memory 分层

### 短期记忆

短期记忆用于当前 session 内：

- 最近消息
- 最近 observation 摘要
- 当前 pending action
- 当前工具结果摘要

### 长期记忆

长期记忆用于未来扩展：

- 用户偏好
- 用户历史事实
- 检索摘要缓存

本期只保留接口和 repository 挂点，不要求完整实现召回链路。

## Trace 持久化设计

### 设计动机

ReAct 架构上线后，问题通常不在“有没有 loop”，而在：

- 为什么模型做了这个决策
- 为什么选了这个工具
- 为什么工具结果没有推进到最终回答
- 为什么卡在重复调用或空转

没有 step 级 trace 持久化，这些问题很难定位。

### Trace 模型

建议新增表：`ai_agent_trace`

字段建议：

- `id`
- `conversation_id`
- `session_id`
- `step_index`
- `phase`
  - `reason`
  - `action`
  - `observation`
  - `termination`
- `decision_type`
- `tool_name`
- `tool_args_json`
- `observation_json`
- `status`
  - `success`
  - `error`
  - `blocked`
  - `terminated`
- `reason_summary`
- `error_code`
- `error_message`
- `created_at`

索引建议：

- `(conversation_id, created_at)`
- `(session_id, step_index)`
- 可选 `(tool_name, created_at)`

### Trace 写入策略

- 模型完成一次决策后写 `reason`
- 工具执行前写 `action`
- 工具返回后写 `observation`
- 本轮结束时写 `termination`

注意：

- 不持久化完整原始 thought
- 仅持久化 `reason_summary` 这类审计摘要

## 与现有代码的映射

### `langgraph_assistant.py`

现有 `backend/app/ai/services/langgraph_assistant.py` 将被削薄：

- `_build_agent_loop_messages`
  - 迁到 `reasoning/prompt_builder.py`
- `run_agent_loop`
  - 迁到 `runtime/langgraph_runtime.py`
- `_parse_tool_arguments`
  - 迁到 `reasoning/parser.py`
- `_build_tool_schemas`
  - 迁到 `tools/registry.py`
- `tool_trace.append(...)`
  - 迁到 `tracing/tracer.py`
- `retry_used`、`max_turns`
  - 迁到 `termination/controller.py`

`_maybe_interrupt_flow_chart_generation` 保留为领域级 hook，不进入 runtime 核心通用层。

`resume_flow_chart_generation` 迁到 facade 协调，具体 artifact 仍由 `FlowChartInterruptService` 生成。

### `tool_registry.py`

现有 `backend/app/ai/services/tool_registry.py` 迁到 `agent/tools/registry.py`，并短期保留兼容导出。

### `tool_executor.py`

现有 `backend/app/ai/services/tool_executor.py` 迁到 `agent/tools/dispatcher.py`，并短期保留兼容导出。

### `ai_conversation_service.py`

现有 `backend/app/ai/services/ai_conversation_service.py` 保留：

- 会话创建
- 用户消息保存
- assistant 最终消息保存
- 历史消息读取

不再负责 runtime step 级状态。

### `schemas/ai.py`

`backend/app/schemas/ai.py` 中的 `AssistantResponse` 继续保留为 API 层响应模型。

Runtime 内部不直接使用它贯穿全流程，而是在运行结束后由 facade 完成映射。

## 实施范围

### 本次必须落地

- 新建 `backend/app/ai/agent/` 目录和基础模块
- 落地 `AgentRuntime` 抽象
- 落地 `LangGraphAgentRuntime`
- 落地 `PromptBuilder`
- 落地 `StateManager`
- 落地 `ReasoningEngine`
- 落地 `ToolRegistry`
- 落地 `ToolDispatcher`
- 落地 `Guardrails`
- 落地 `TerminationController`
- 落地 `Tracer`
- 新增 `ai_agent_trace` 持久化
- 迁移现有能力：
  - `general_chat`
  - `rag_retrieval`
  - `generate_flow_from_file`
  - 现有已暴露工具
- 让现有 `langgraph_assistant.py` 转调新 facade

### 本次只做接口和挂点

- `LoopAgentRuntime` 骨架
- 长期记忆 repository 与 manager 接口
- 高风险工具二次确认机制挂点
- 更复杂的上下文压缩策略

### 本次不做

- 完全去除 LangGraph
- 真正长期记忆召回
- 多 agent
- 工具市场

## 推荐迁移顺序

1. 建立 `agent/` 目录与核心对象模型
2. 建 `ai_agent_trace` 持久化模型与 repository
3. 迁移工具协议到 `tools/`
4. 迁移 prompt、parser、reasoning 到 `reasoning/`
5. 落地 `StateManager`、`Guardrails`、`TerminationController`
6. 落地 `LangGraphAgentRuntime`
7. 让旧 `langgraph_assistant.py` 转调新 facade
8. 跑通现有三类能力
9. 补 trace 与回归测试
10. 最后清理兼容层

## 风险与应对

### 风险一：`pending_action` 与 runtime 状态边界耦合

应对：

- 把 `pending_action` 视为 `TerminationSignal(status=waiting_input)` 的一个结果
- 不让领域中断逻辑散落在各层

### 风险二：流式输出和最终消息落库顺序不一致

应对：

- 明确 runtime stream 只负责事件输出
- 最终消息持久化仍由 facade 统一收口

### 风险三：现有 prompt 中的隐式规则迁移遗漏

应对：

- 把 prompt 分成多个可单测的片段
- 先迁移现有规则，再逐步优化

### 风险四：trace 粒度过粗或过细

应对：

- 首期仅记录 `reason/action/observation/termination`
- 不记录冗余原始文本或完整 CoT

## 结论

本次推荐采用“自有 Runtime 抽象 + LangGraph 默认 backend”的渐进式重构方案。

其核心收益是：

- 保持现有能力稳定迁移
- 形成标准化 ReAct Agent 工程骨架
- 为未来替换 runtime backend、扩展工具、增强记忆与安全策略预留稳定接口
- 通过 trace 持久化提升问题排查、可观测性和后续平台化能力

这是当前项目从“可运行 agent”迈向“可维护 agent 平台”的最稳妥路径。
