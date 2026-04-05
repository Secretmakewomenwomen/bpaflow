# Findings & Decisions

## Confirmed User Requirements
- Need two detailed documents.
- Document A is an internal architecture document focused on the current ReAct AI service.
- Document B is an interview/presentation document focused on the AI service from 0 to 1.
- Both documents should be written from an architect's perspective.
- Both documents should include future evolution analysis.
- Both documents should include diagram-oriented content.

## Current ReAct Agent Evidence
- API entrypoint for the new agent service is in `backend/app/api/routes/agent.py`.
- `AgentFacade` in `backend/app/ai/agent/facade.py` is the orchestration entry that assembles reasoning, tools, guardrails, memory, termination, tracer, and the current ReAct runtime.
- The current runtime implementation is `LangGraphAgentRuntime`; `LoopAgentRuntime` has been removed from the active code path.
- `ReasoningEngine` in `backend/app/ai/agent/reasoning/engine.py` supports:
  - OpenAI tool-call parsing
  - Legacy text ReAct parsing (`Thought/Action/Final Answer` style)
  - Final-answer fallback for plain text responses
- Tool protocol is centralized in `backend/app/ai/agent/tools/registry.py` and executed by `backend/app/ai/agent/tools/dispatcher.py`.
- Runtime state is modeled in `backend/app/ai/agent/state/models.py` and managed by `backend/app/ai/agent/state/manager.py`.
- Safety boundaries are separated into:
  - `backend/app/ai/agent/guardrails/policy.py`
  - `backend/app/ai/agent/termination/controller.py`
- Step-level observability is handled by `backend/app/ai/agent/tracing/tracer.py`, with persistence into `AiAgentTrace`.

## Legacy / Transitional Architecture Evidence
- The previous architecture direction is documented in `docs/superpowers/specs/2026-04-01-ai-assistant-tool-calling-design.md`.
- The current standardized ReAct platform direction is documented in `docs/superpowers/specs/2026-04-03-react-agent-design.md`.
- `backend/app/ai/services/langgraph_assistant.py` shows the transitional state:
  - LangGraph still provides the graph/checkpoint/stream shell.
  - The core agent loop is already delegated to `AgentFacade`.
  - The graph has been simplified to `load_history -> run_agent_loop -> build_response -> persist_message`.
- This means the project is no longer in the original rule-driven tool-routing mode, but it is also not yet a fully independent pure runtime platform.

## Data & Storage Findings
- Business conversation persistence remains in:
  - `AiConversation`
  - `AiMessage`
  - `AiMessageReference`
- Runtime observability persistence is separated into `AiAgentTrace`.
- This separation supports a strong documentation point: user-visible business messages and internal runtime traces are stored independently.

## RAG / Database Findings
- Retrieval is implemented in `backend/app/ai/services/ai_rag_service.py`.
- Retrieval strategy is multi-route:
  - vector retrieval
  - BM25 retrieval
  - deterministic rule-based retrieval
- Vector and lexical retrieval both reuse PostgreSQL-based storage through `backend/app/services/pgvector_service.py`.
- `backend/sql/004_add_pg_search_bm25.sql` shows the project uses PostgreSQL `pg_search` BM25 indexing.
- `backend/sql/003_add_dual_channel_vector_fields.sql` shows file-level vectorization lifecycle state is stored directly on `uploaded_file`.
- Database choice is therefore not “a separate vector DB”, but “PostgreSQL as the unified transactional + vector + lexical retrieval store”.

## Architecture Narrative Candidates
- The strongest narrative is not “we replaced tool-calling with ReAct completely”.
- The stronger and more accurate narrative is:
  - Stage 1: rule-driven intent + tool routing
  - Stage 2: model-driven tool-calling loop
  - Stage 3: standardized ReAct runtime abstraction with decoupled reasoning/state/tool/safety/tracing
  - Stage 4: future optional evolution to planner-executor, multi-agent, longer-term memory, and dynamic tooling

## Risks / Accuracy Constraints
- Need to distinguish “implemented now” from “architectural target”.
- Need to avoid claiming that LangGraph has been fully removed; current code shows it is still part of one runtime backend and stream/checkpoint shell.
- Need to describe the current runtime accurately: LangGraph still exists as the execution shell, but the old standalone `loop` runtime no longer exists in the active implementation.
