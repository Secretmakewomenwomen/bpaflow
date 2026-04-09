# Create Agent Migration Design

## Goal

Replace the custom ReAct-style agent loop under `backend/app/ai/agent` with a LangChain `create_agent` based implementation, and remove obsolete compatibility layers instead of preserving them.

## Current State

The backend currently uses LangGraph only as an outer orchestration shell. The actual agent loop is owned by local code:

- `runtime/langgraph_runtime.py` drives the decision loop
- `reasoning/*` builds prompts and parses model output
- `state/*` and `termination/*` support the custom loop
- `facade.py` stitches the runtime into `LangGraphAssistantService`

This architecture duplicates framework responsibilities that `langchain.agents.create_agent` now provides natively. It also forces the project to maintain custom handling for tool-calling, legacy text ReAct parsing, retry behavior, and loop termination.

## Target Architecture

After migration the system should have two layers:

1. `LangGraphAssistantService` remains the outer business workflow.
2. A new `create_agent` based inner agent becomes the only general-purpose tool-using runtime.

### Outer Layer Responsibilities

`backend/app/ai/services/langgraph_assistant.py` continues to own:

- loading conversation history
- orchestrating flow-chart-specific interrupt/resume behavior
- persisting the final assistant message
- exposing streaming and invocation entry points to the rest of the backend

### Inner Layer Responsibilities

A new create-agent integration layer under `backend/app/ai/agent/core/` owns:

- model adaptation
- tool exposure
- middleware registration
- invocation of the compiled agent graph
- mapping the agent result into `AssistantResponse`

The custom loop implementation is removed rather than wrapped.

## File-Level Migration Plan

### Files to Delete

The following files should be removed because their responsibilities are replaced by `create_agent`:

- `backend/app/ai/agent/runtime/langgraph_runtime.py`
- `backend/app/ai/agent/runtime/base.py`
- `backend/app/ai/agent/reasoning/engine.py`
- `backend/app/ai/agent/reasoning/parser.py`
- `backend/app/ai/agent/reasoning/prompt_builder.py`
- `backend/app/ai/agent/reasoning/models.py`
- `backend/app/ai/agent/state/manager.py`
- `backend/app/ai/agent/state/models.py`
- `backend/app/ai/agent/termination/controller.py`

The corresponding package `__init__` files should either be trimmed or removed if the package no longer exists.

### Files to Keep and Refactor

#### `backend/app/ai/agent/facade.py`

Keep as a thin orchestration facade, but refactor it to:

- build the `create_agent` instance through `core/agent_builder.py`
- invoke the agent with user query, history, and runtime context
- map the result into `AssistantResponse`
- keep business-specific flow-chart interrupt/resume logic outside the general agent loop

#### `backend/app/ai/agent/tools/registry.py`

Keep as the single source of truth for tool definitions.

#### `backend/app/ai/agent/tools/dispatcher.py`

Keep MCP-backed tool execution behavior, but make it the backend behind LangChain tool wrappers instead of a custom runtime.

#### `backend/app/ai/agent/guardrails/policy.py`

Keep the policy concept, but refactor its inputs to stop depending on:

- `AgentSessionState`
- `reasoning.models.ToolCall`

It should validate against a smaller context structure that is compatible with LangChain middleware/tool wrappers.

#### `backend/app/ai/agent/memory/manager.py`

Keep only the useful summary/extraction behavior. Remove assumptions about custom step state and use it as a helper for middleware-based memory writes.

#### `backend/app/ai/agent/tracing/tracer.py`

Keep persistence and serialization behavior. Change the call sites so traces are emitted from middleware and tool wrappers rather than from the deleted runtime loop.

### Files to Add

#### `backend/app/ai/agent/core/agent_builder.py`

Builds the `create_agent(...)` instance with:

- the adapted model
- generated tools
- configured middleware
- optional checkpointer or store if needed

#### `backend/app/ai/agent/core/model_adapter.py`

Wraps `McpLlmProxyClient` so it can be used as a LangChain `BaseChatModel`.

#### `backend/app/ai/agent/core/tool_factory.py`

Creates LangChain tools from `registry.py` plus `dispatcher.py`.

#### `backend/app/ai/agent/core/middleware.py`

Holds middleware for:

- guardrails
- tracing
- memory collection
- tool result capture

#### `backend/app/ai/agent/core/state.py`

Defines the new minimal agent state schema used by `create_agent`.

The new state should only contain fields needed for current product behavior, such as:

- conversation identifiers
- user and tenant context
- tool trace aggregation
- optional reasoning trace aggregation
- accumulated retrieval payloads

It should not recreate the deleted custom step-state hierarchy.

#### `backend/app/ai/agent/core/result_mapper.py`

Converts raw agent state and output messages into `AssistantResponse`.

## Runtime Data Flow

The runtime path after migration should be:

1. `LangGraphAssistantService` loads recent conversation history.
2. `AgentFacade` builds or fetches the configured `create_agent` graph.
3. `model_adapter` provides a LangChain-compatible model backed by `McpLlmProxyClient`.
4. `tool_factory` provides LangChain tools backed by the existing MCP dispatcher.
5. middleware intercepts model and tool execution to apply guardrails, tracing, and memory writes.
6. the agent executes until final output is produced.
7. `result_mapper` converts the resulting state into `AssistantResponse`.
8. `LangGraphAssistantService` persists the response as the assistant message.

## Error Handling

### Model Errors

Model transport and provider errors should be normalized inside `model_adapter` and surfaced as a unified failure path for `AgentFacade`.

### Tool Errors

Tool execution should continue to use the structured MCP error payload shape already emitted by `ToolDispatcher`.

Middleware should:

- trace the attempted call
- capture success or failure
- decide whether the error should remain available to the agent as tool output

The migration does not preserve the old custom retry semantics automatically. Retry behavior should be reintroduced only where it is still required and justified.

### Business Interrupts

Flow-chart file selection remains a business-specific interrupt path and should not be folded into the generic `create_agent` runtime. That logic stays in service/facade orchestration.

## Deliberate Removals

The following historical behaviors are intentionally removed:

- legacy text ReAct prompt mode
- custom parsing of `Thought / Action / Final Answer`
- custom step counting and repeated-action termination logic
- custom session-state graph designed only to support the deleted runtime

The migration goal is a cleaner native agent core, not compatibility with the previous internal architecture.

## Testing Strategy

The old unit tests for deleted runtime internals should be removed or rewritten.

### Tests to Remove or Replace

- `backend/tests/test_agent_reasoning_engine.py`
- `backend/tests/test_agent_termination.py`
- `backend/tests/test_agent_state_manager.py`
- runtime-specific tests tied to the deleted execution loop

### Tests to Add

- model adapter tests
- tool factory / wrapped tool tests
- middleware tests for guardrails, tracing, and memory writes
- result mapper tests
- facade integration tests against `create_agent`

### Tests to Keep and Update

- `backend/tests/test_langgraph_assistant.py`
- dispatcher tests
- tracer tests
- schema tests
- API and service integration tests that validate the externally visible assistant behavior

## Execution Order

Implementation should proceed in this order:

1. introduce `core/` scaffolding and a minimal create-agent invocation path
2. adapt model integration
3. adapt tool integration
4. port tracing, guardrails, and memory to middleware/wrappers
5. refactor `AgentFacade` to use the new core
6. update service and integration tests
7. remove obsolete runtime/reasoning/state/termination code

This order minimizes the time spent in a half-migrated state.

## Non-Goals

This migration does not attempt to:

- preserve the deleted internal abstractions
- keep legacy ReAct parsing behavior
- keep every historical trace shape identical if a simpler native structure works
- redesign unrelated assistant product behavior outside the agent core

## Success Criteria

The migration is complete when:

- the assistant no longer depends on the deleted custom ReAct runtime files
- general agent execution is powered by `langchain.agents.create_agent`
- MCP model and tool integrations still work through adapters/wrappers
- flow-chart interrupt behavior still works
- existing externally visible assistant flows remain operational through updated tests
