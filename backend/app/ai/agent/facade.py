from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any, Callable

from langgraph.types import interrupt

from app.ai.agent.guardrails.policy import GuardrailsPolicy
from app.ai.agent.memory.manager import MemoryManager
from app.ai.agent.reasoning.engine import ReasoningEngine
from app.ai.agent.reasoning.prompt_builder import PromptBuilder
from app.ai.agent.runtime.langgraph_runtime import LangGraphAgentRuntime
from app.ai.agent.state.manager import AgentStateManager
from app.ai.agent.termination.controller import TerminationController
from app.ai.agent.tools.dispatcher import ToolDispatcher
from app.ai.agent.tracing.tracer import NoopAgentTracer, SqlAlchemyAgentTracer
from app.ai.services.mcp_llm_proxy_client import McpLlmProxyClient
from app.schemas.ai import (
    AssistantActionButton,
    AssistantArtifact,
    AssistantPendingAction,
    AssistantReasoningStep,
    AssistantReference,
    AssistantReferenceType,
    AssistantResponse,
    AssistantToolTrace,
    ConversationMessageResponse,
    Intent,
)


class AgentFacade:
    def __init__(
        self,
        *,
        settings: Any,
        conversation_service: Any,
        tenant_id: str | None = None,
        rag_service: Any | None = None,
        upload_service: Any | None = None,
        work_service: Any | None = None,
        flow_chart_interrupt_service: Any | None = None,
        openai_client: Any | None = None,
        openai_client_factory: Callable[[], Any] | None = None,
        mcp_client: Any | None = None,
    ) -> None:
        self.settings = settings
        self.conversation_service = conversation_service
        self.tenant_id = tenant_id
        self.rag_service = rag_service
        self.upload_service = upload_service
        self.work_service = work_service
        self.flow_chart_interrupt_service = flow_chart_interrupt_service
        self._openai_client = openai_client
        self._openai_client_factory = openai_client_factory
        self._mcp_client = mcp_client

        self.state_manager = AgentStateManager()
        self.prompt_builder = PromptBuilder(max_history=4)
        self._reasoning_engine: ReasoningEngine | None = None
        self.tool_dispatcher = ToolDispatcher(
            settings=self.settings,
            work_service=self.work_service,
            upload_service=self.upload_service,
            ai_rag_service=self.rag_service,
            current_user_id=None,
            current_tenant_id=self.tenant_id,
            mcp_client=self._mcp_client,
        )
        self.guardrails = GuardrailsPolicy()
        self.termination = TerminationController()
        self.memory = MemoryManager()

    def _get_reasoning_engine(self) -> ReasoningEngine:
        if self._reasoning_engine is None:
            self._reasoning_engine = ReasoningEngine(
                client=self._get_openai_client(),
                prompt_builder=self.prompt_builder,
                model=getattr(self.settings, "assistant_llm_model", ""),
                temperature=0.2,
            )
        return self._reasoning_engine

    def _get_openai_client(self) -> Any:
        if self._openai_client is not None:
            return self._openai_client
        if self._openai_client_factory is None:
            raise RuntimeError("OpenAI client is not configured.")
        self._openai_client = self._openai_client_factory()
        return self._openai_client

    def _build_tracer(self) -> Any:
        db = getattr(self.conversation_service, "db", None)
        if db is None:
            return NoopAgentTracer()
        return SqlAlchemyAgentTracer(db)

    def stream_invoke(
        self,
        *,
        conversation_id: str,
        query: str,
        user_id: str,
        build_graph: Callable[..., Any],
        checkpointer_context: Callable[[], Any],
        create_assistant_message: Callable[..., ConversationMessageResponse],
    ) -> Iterator[dict[str, Any]]:
        yield {"event": "assistant_start", "data": {}}
        with checkpointer_context() as checkpointer:
            graph = build_graph(checkpointer=checkpointer)
            assistant_message: ConversationMessageResponse | None = None
            interrupt_value: dict[str, Any] | None = None
            for stream_item in graph.stream(
                {
                    "conversation_id": conversation_id,
                    "query": query,
                    "user_id": user_id,
                    "stream": True,
                },
                config={"configurable": {"thread_id": conversation_id}},
                stream_mode=["custom", "updates"],
            ):
                stream_mode, payload = self._normalize_graph_stream_item(stream_item)
                if stream_mode == "custom":
                    event = self._extract_custom_stream_event(payload)
                    if event is not None:
                        yield event
                    continue
                interrupt_value = self._extract_interrupt_value_from_updates(payload) or interrupt_value
                assistant_message = self._extract_assistant_message_from_updates(payload) or assistant_message
        if assistant_message is None and interrupt_value is not None:
            response = AssistantResponse.model_validate(interrupt_value)
            assistant_message = create_assistant_message(
                conversation_id=conversation_id,
                user_id=user_id,
                response=response,
            )
        if assistant_message is None:
            raise RuntimeError("LangGraph stream completed without assistant message.")
        yield {"event": "assistant_done", "data": {"message": assistant_message.model_dump(mode="json")}}

    def export_graph_mermaid(self, *, build_graph: Callable[..., Any]) -> str:
        compiled_graph = build_graph(checkpointer=None)
        return compiled_graph.get_graph().draw_mermaid()

    def run_agent_loop(
        self,
        *,
        conversation_id: str | None,
        query: str,
        history_messages: list[ConversationMessageResponse],
        user_id: str,
        stream: bool = True,
        max_turns: int = 6,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
        runtime_backend: str | None = None,
    ) -> dict[str, Any]:
        interrupt_state = self._maybe_interrupt_flow_chart_generation(query=query, user_id=user_id)
        if interrupt_state is not None:
            resume_payload = self._interrupt_for_flow_chart_selection(interrupt_state)
            if resume_payload is None:
                return interrupt_state
            return self._complete_flow_chart_after_resume(
                interrupt_state=interrupt_state,
                resume_payload=resume_payload,
                user_id=user_id,
            )

        session_state = self.state_manager.create_session(
            conversation_id=conversation_id or "",
            user_id=user_id,
            query=query,
        )

        runtime = self._select_runtime(
            runtime_backend=runtime_backend,
            conversation_id=conversation_id or "",
            user_id=user_id,
            history_messages=history_messages,
            stream=stream,
            max_turns=max_turns,
            emit_event=emit_event,
        )
        session_state = runtime.run(session_state=session_state, stream=stream)
        if session_state.final_response is None:
            return {
                "message": "普通对话生成失败，请稍后再试。",
                "chat_answer": "",
                "response_streamed": False,
                "tool_trace": [],
                "reasoning_trace": [],
            }
        return dict(session_state.final_response)

    def _select_runtime(
        self,
        *,
        runtime_backend: str | None,
        conversation_id: str,
        user_id: str,
        history_messages: list[ConversationMessageResponse],
        stream: bool,
        max_turns: int,
        emit_event: Callable[[str, dict[str, Any]], None] | None,
    ) -> Any:
        reasoning_client = McpLlmProxyClient(
            endpoint=getattr(self.settings, "assistant_mcp_llm_gateway_url"),
            user_id=user_id,
            tenant_id=self.tenant_id,
            session_id=conversation_id,
            timeout_seconds=float(
                getattr(
                    self.settings,
                    "assistant_mcp_llm_timeout_seconds",
                    getattr(self.settings, "assistant_mcp_request_timeout_seconds", 20.0),
                )
            ),
            http_client=self._mcp_client,
        )
        return LangGraphAgentRuntime(
            settings=self.settings,
            client=reasoning_client,
            conversation_service=None,
            history_messages=history_messages,
            tool_dispatcher=ToolDispatcher(
                settings=self.settings,
                work_service=self.work_service,
                upload_service=self.upload_service,
                ai_rag_service=self.rag_service,
                current_user_id=user_id,
                current_tenant_id=self.tenant_id,
                current_session_id=conversation_id,
                mcp_client=self._mcp_client,
            ),
            reasoning_engine=ReasoningEngine(
                client=reasoning_client,
                prompt_builder=self.prompt_builder,
                model=getattr(self.settings, "assistant_llm_model", ""),
                temperature=0.2,
            ),
            state_manager=self.state_manager,
            memory_manager=self.memory,
            guardrails=self.guardrails,
            termination=TerminationController(max_steps=max_turns),
            tracer=self._build_tracer(),
            emit_event=emit_event,
            max_turns=max_turns,
        )

    def build_response(self, *, state: Mapping[str, Any]) -> AssistantResponse:
        intent = self._coerce_intent(state.get("intent"))
        references = list(state.get("references") or [])
        if not references:
            references = self._build_references_from_legacy(
                snippets=list(state.get("snippets") or []),
                related_files=list(state.get("related_files") or []),
            )
        tool_trace = list(state.get("tool_trace") or [])
        reasoning_trace = list(state.get("reasoning_trace") or [])
        status = state.get("status", "completed")

        pending_action = state.get("pending_action")
        artifact = state.get("artifact")
        actions = list(state.get("actions") or [])

        response_kwargs: dict[str, Any] = {
            "intent": intent,
            "status": status,
            "message": state.get("message"),
            "pending_action": pending_action,
            "artifact": artifact,
            "actions": actions,
            "references": references,
            "tool_trace": tool_trace,
            "reasoning_trace": reasoning_trace,
        }

        if intent == Intent.rag_retrieval:
            response_kwargs.update(
                {
                    "answer": state.get("answer", ""),
                    "snippets": list(state.get("snippets") or []),
                    "related_files": list(state.get("related_files") or []),
                }
            )
        else:
            response_kwargs.update(
                {
                    "answer": state.get("chat_answer", ""),
                    "snippets": [],
                    "related_files": [],
                }
            )
        return AssistantResponse.model_validate(response_kwargs)

    def resume_flow_chart_generation(
        self,
        *,
        conversation_id: str,
        user_id: str,
        action_id: str,
        upload_id: int,
    ) -> AssistantResponse:
        if isinstance(upload_id, bool) or not isinstance(upload_id, int) or upload_id <= 0:
            raise ValueError("resume_flow_chart_generation requires a single upload_id.")
        if self.flow_chart_interrupt_service is None:
            raise RuntimeError("Flow chart interrupt service is not configured.")
        self.validate_pending_flow_chart_action(
            conversation_id=conversation_id,
            user_id=user_id,
            action_id=action_id,
            upload_id=upload_id,
        )
        artifact = self.flow_chart_interrupt_service.build_artifact(upload_id=upload_id, user_id=user_id)
        return AssistantResponse(
            intent=Intent.generate_flow_from_file,
            status="completed",
            message=None,
            answer="已根据所选文件生成流程图。",
            pending_action=None,
            artifact=artifact,
            actions=[
                {
                    "action_id": action_id,
                    "label": "导入",
                    "action_type": "import_flow",
                },
                {
                    "action_id": action_id,
                    "label": "重新选择文件",
                    "action_type": "reselect_file",
                },
            ],
        )

    def validate_pending_flow_chart_action(
        self,
        *,
        conversation_id: str,
        user_id: str,
        action_id: str,
        upload_id: int,
    ) -> None:
        conversation_messages = self.conversation_service.get_messages(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        for message in reversed(conversation_messages):
            for action in getattr(message, "actions", []) or []:
                if action.action_id == action_id:
                    raise ValueError("resume_flow_chart_generation action has already been handled.")
            pending_action = getattr(message, "pending_action", None)
            if pending_action is None:
                continue
            if pending_action.action_id != action_id:
                continue
            candidate_ids = {candidate.upload_id for candidate in pending_action.payload.candidates}
            if upload_id not in candidate_ids:
                raise ValueError("resume_flow_chart_generation upload_id is not in the pending candidate list.")
            return
        raise ValueError("resume_flow_chart_generation requires a matching pending action.")

    def _interrupt_for_flow_chart_selection(self, interrupt_state: Mapping[str, Any]) -> dict[str, Any] | None:
        payload = self._to_jsonable(dict(interrupt_state))
        try:
            resumed = interrupt(payload)
        except RuntimeError:
            # Compatibility path for direct calls outside LangGraph execution context.
            return None
        if not isinstance(resumed, dict):
            raise ValueError("resume_flow_chart_generation payload must be an object.")
        return dict(resumed)

    def _complete_flow_chart_after_resume(
        self,
        *,
        interrupt_state: Mapping[str, Any],
        resume_payload: Mapping[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        if self.flow_chart_interrupt_service is None:
            raise RuntimeError("Flow chart interrupt service is not configured.")
        pending_action = interrupt_state.get("pending_action")
        if not isinstance(pending_action, Mapping):
            raise ValueError("resume_flow_chart_generation requires pending action metadata.")
        expected_action_id = str(pending_action.get("action_id") or "").strip()
        action_id = str(resume_payload.get("action_id") or "").strip()
        if not action_id:
            raise ValueError("resume_flow_chart_generation action_id is required.")
        if action_id != expected_action_id:
            raise ValueError("resume_flow_chart_generation action_id does not match pending action.")
        upload_id = resume_payload.get("upload_id")
        if isinstance(upload_id, bool) or not isinstance(upload_id, int) or upload_id <= 0:
            raise ValueError("resume_flow_chart_generation requires a single upload_id.")
        payload = pending_action.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("resume_flow_chart_generation pending payload is invalid.")
        candidate_upload_ids: set[int] = set()
        raw_candidates = payload.get("candidates")
        if isinstance(raw_candidates, list):
            for candidate in raw_candidates:
                if not isinstance(candidate, Mapping):
                    continue
                candidate_upload_id = candidate.get("upload_id")
                if isinstance(candidate_upload_id, bool) or not isinstance(candidate_upload_id, int):
                    continue
                candidate_upload_ids.add(candidate_upload_id)
        if upload_id not in candidate_upload_ids:
            raise ValueError("resume_flow_chart_generation upload_id is not in the pending candidate list.")
        artifact = self.flow_chart_interrupt_service.build_artifact(upload_id=upload_id, user_id=user_id)
        return {
            "intent": Intent.generate_flow_from_file.value,
            "status": "completed",
            "message": None,
            "chat_answer": "已根据所选文件生成流程图。",
            "pending_action": None,
            "artifact": artifact,
            "actions": [
                {
                    "action_id": action_id,
                    "label": "导入",
                    "action_type": "import_flow",
                },
                {
                    "action_id": action_id,
                    "label": "重新选择文件",
                    "action_type": "reselect_file",
                },
            ],
            "response_streamed": False,
            "tool_trace": [],
            "reasoning_trace": [],
        }

    def _maybe_interrupt_flow_chart_generation(self, *, query: str, user_id: str) -> dict[str, Any] | None:
        if not self._is_generate_flow_from_file_request(query):
            return None
        if self.flow_chart_interrupt_service is None:
            return None
        candidates = self.flow_chart_interrupt_service.find_candidate_files(query=query, user_id=user_id)
        if not candidates:
            return None
        return {
            "intent": Intent.generate_flow_from_file.value,
            "status": "waiting_input",
            "pending_action": {
                "action_id": f"select-file-{uuid.uuid4().hex}",
                "action_type": "select_file",
                "payload": {
                    "selection_mode": "single",
                    "candidates": candidates,
                },
            },
            "chat_answer": "我找到了相关文件，请选择一个文件生成流程图。",
            "response_streamed": False,
            "tool_trace": [],
            "reasoning_trace": [],
        }

    @staticmethod
    def _is_generate_flow_from_file_request(query: str) -> bool:
        normalized = query.strip()
        if not normalized:
            return False
        has_flow_signal = "流程图" in normalized
        has_file_signal = any(token in normalized for token in ("文件", "文档"))
        has_generate_signal = "生成" in normalized
        has_source_signal = "根据" in normalized
        return has_flow_signal and has_generate_signal and (has_file_signal or has_source_signal)

    @staticmethod
    def _normalize_graph_stream_item(stream_item: Any) -> tuple[str, Any]:
        if isinstance(stream_item, tuple) and len(stream_item) == 2:
            stream_mode, payload = stream_item
            if isinstance(stream_mode, str):
                return stream_mode, payload
        return "updates", stream_item

    @staticmethod
    def _extract_custom_stream_event(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        event = payload.get("event")
        data = payload.get("data")
        if not isinstance(event, str) or not isinstance(data, dict):
            return None
        return {"event": event, "data": data}

    @staticmethod
    def _extract_assistant_message_from_updates(payload: Any) -> ConversationMessageResponse | None:
        if not isinstance(payload, dict):
            return None
        persist_update = payload.get("persist_message")
        if not isinstance(persist_update, dict):
            return None
        assistant_message = persist_update.get("assistant_message")
        if isinstance(assistant_message, ConversationMessageResponse):
            return assistant_message
        if isinstance(assistant_message, dict):
            return ConversationMessageResponse.model_validate(assistant_message)
        return None

    @staticmethod
    def _extract_interrupt_value_from_updates(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        raw_interrupts = payload.get("__interrupt__")
        if not isinstance(raw_interrupts, (list, tuple)) or not raw_interrupts:
            return None
        first_interrupt = raw_interrupts[0]
        value = getattr(first_interrupt, "value", None)
        if isinstance(first_interrupt, dict):
            value = first_interrupt.get("value")
        if not isinstance(value, dict):
            return None
        return value

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, Mapping):
            return {k: AgentFacade._to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [AgentFacade._to_jsonable(v) for v in value]
        return value

    @staticmethod
    def _coerce_intent(value: Any) -> Intent:
        if isinstance(value, Intent):
            return value
        if isinstance(value, str):
            try:
                return Intent(value)
            except ValueError:
                return Intent.general_chat
        return Intent.general_chat

    @staticmethod
    def _build_references_from_legacy(
        *,
        snippets: list[dict[str, Any]] | list[Any],
        related_files: list[dict[str, Any]] | list[Any],
    ) -> list[dict[str, Any]]:
        references: list[dict[str, Any]] = []
        for snippet in snippets:
            payload = snippet.model_dump(mode="json") if hasattr(snippet, "model_dump") else dict(snippet)
            references.append(
                {
                    "reference_type": AssistantReferenceType.snippet.value,
                    "upload_id": payload.get("upload_id"),
                    "file_name": payload.get("file_name"),
                    "snippet_text": payload.get("text"),
                    "page_start": payload.get("page_start"),
                    "page_end": payload.get("page_end"),
                    "score": payload.get("score"),
                }
            )
        for related_file in related_files:
            payload = related_file.model_dump(mode="json") if hasattr(related_file, "model_dump") else dict(related_file)
            references.append(
                {
                    "reference_type": AssistantReferenceType.file.value,
                    "upload_id": payload.get("upload_id"),
                    "file_name": payload.get("file_name"),
                    "download_url": payload.get("download_url"),
                }
            )
        return references
