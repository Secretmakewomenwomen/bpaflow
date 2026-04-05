from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from typing import Any, Callable

from app.ai.agent.guardrails.policy import GuardrailsPolicy
from app.ai.agent.memory.manager import MemoryManager
from app.ai.agent.reasoning.engine import ReasoningEngine
from app.ai.agent.reasoning.models import DecisionType
from app.ai.agent.state.manager import AgentStateManager
from app.ai.agent.state.models import AgentSessionState
from app.ai.agent.termination.controller import TerminationController
from app.ai.agent.tools.dispatcher import ToolDispatcher
from app.ai.agent.tools.models import ToolCall as DispatcherToolCall
from app.ai.agent.tools.registry import get_tool, list_tools
from app.ai.agent.tracing.tracer import AgentTracer, NoopAgentTracer
from app.schemas.ai import AssistantReasoningStep, AssistantResponse, Intent

logger = logging.getLogger(__name__)


def _summarize_observation(*, tool_name: str, result: Mapping[str, Any]) -> str:
    # User-facing reasoning must not include raw tool payloads.
    name = tool_name.strip() if tool_name else "unknown_tool"
    ok = bool(result.get("ok"))
    if ok:
        return f"工具 {name} 调用成功"
    error = result.get("error") or {}
    code = str(error.get("code") or "ERROR")
    message = error.get("message")
    if isinstance(message, str) and message.strip():
        # Keep message bounded; error details should remain in server-side traces/tool messages.
        trimmed = message.strip()
        if len(trimmed) > 160:
            trimmed = trimmed[:157] + "..."
        return f"工具 {name} 调用失败: {code} ({trimmed})"
    return f"工具 {name} 调用失败: {code}"


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


def _extract_content_text(content: Any, *, strip: bool = True) -> str:
    text = _extract_text_parts(content)
    return text.strip() if strip else text


def _extract_text_parts(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "".join(_extract_text_parts(item) for item in content)
    if isinstance(content, Mapping):
        text_value = content.get("text")
        if isinstance(text_value, str):
            return text_value
        if isinstance(text_value, Mapping):
            nested_value = text_value.get("value")
            if isinstance(nested_value, str):
                return nested_value
        nested_content = content.get("content")
        if nested_content is not None:
            return _extract_text_parts(nested_content)
        return ""
    text_attr = getattr(content, "text", None)
    if isinstance(text_attr, str):
        return text_attr
    if text_attr is not None:
        return _extract_text_parts(text_attr)
    nested_content = getattr(content, "content", None)
    if nested_content is not None and nested_content is not content:
        return _extract_text_parts(nested_content)
    return ""


class _DecisionClientProxy:
    """Proxy client that forces ReasoningEngine.decide() to use the runtime's message list."""

    def __init__(self, *, base_client: Any, get_messages: Callable[[], list[dict[str, Any]]]) -> None:
        self._base = base_client
        self._get_messages = get_messages
        self.last_completion: Any | None = None

        base_chat = getattr(base_client, "chat", None)
        base_completions = getattr(base_chat, "completions", None) if base_chat is not None else None
        if base_completions is None or not hasattr(base_completions, "create"):
            raise TypeError("client.chat.completions.create is required")

        class _Chat:
            def __init__(self, outer: "_DecisionClientProxy") -> None:
                self.completions = outer._Completions(outer)

        self.chat = _Chat(self)

    class _Completions:
        def __init__(self, outer: "_DecisionClientProxy") -> None:
            self._outer = outer

        def create(self, **kwargs: Any) -> Any:
            # ReasoningEngine builds its own prompt messages; runtime must keep tool-role messages in play,
            # so we override the outgoing request with the runtime-managed message list.
            kwargs["messages"] = list(self._outer._get_messages())
            result = self._outer._base.chat.completions.create(**kwargs)
            self._outer.last_completion = result
            return result


class LangGraphAgentRuntime:
    """
    ReAct-ish agent runtime that supports:
    - tool-calling completions (OpenAI tool_calls)
    - legacy text ReAct (Thought/Action/Final Answer)
    - streaming callbacks compatible with the current SSE behavior
    - trace persistence via AgentTracer
    """

    def __init__(
        self,
        *,
        settings: Any,
        client: Any,
        conversation_service: Any | None,
        history_messages: Iterable[Any] | None = None,
        tool_dispatcher: ToolDispatcher,
        reasoning_engine: ReasoningEngine,
        state_manager: AgentStateManager | None = None,
        memory_manager: MemoryManager | None = None,
        guardrails: GuardrailsPolicy | None = None,
        termination: TerminationController | None = None,
        tracer: AgentTracer | None = None,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
        max_turns: int = 6,
    ) -> None:
        self.settings = settings
        self.client = client
        self.conversation_service = conversation_service
        self.history_messages = list(history_messages) if history_messages is not None else None
        self.tool_dispatcher = tool_dispatcher
        self.reasoning_engine = reasoning_engine
        self.state_manager = state_manager or AgentStateManager()
        self.memory_manager = memory_manager or MemoryManager()
        self.guardrails = guardrails or GuardrailsPolicy()
        self.termination = termination or TerminationController()
        self.tracer = tracer or NoopAgentTracer()
        self.emit_event = emit_event
        self.max_turns = max(1, int(max_turns))

    def run(self, *, session_state: AgentSessionState, stream: bool = False) -> AgentSessionState:
        conversation_id = session_state.conversation_id
        session_id = session_state.session_id
        query = session_state.goal

        history_messages = self._load_history(session_state)
        tool_schemas = self._build_tool_schemas()
        messages: list[dict[str, Any]] = self.reasoning_engine.prompt_builder.build_messages(
            query=query,
            history_messages=history_messages,
            memory_summary=None,
        )
        decision_tools = tool_schemas if self._should_send_tools() else None
        proxy_client = _DecisionClientProxy(base_client=self.client, get_messages=lambda: messages)
        decision_engine = ReasoningEngine(
            client=proxy_client,
            prompt_builder=self.reasoning_engine.prompt_builder,
            model=self.reasoning_engine.model,
            temperature=self.reasoning_engine.temperature,
        )

        reasoning_trace: list[dict[str, Any]] = []
        tool_trace: list[dict[str, Any]] = []
        tool_result_cache: dict[str, dict[str, Any]] = {}
        retrieval_response: AssistantResponse | None = None
        retry_used = False

        def emit_reasoning(step: AssistantReasoningStep) -> None:
            step_payload = step.model_dump(mode="json")
            reasoning_trace.append(step_payload)
            if stream and self.emit_event is not None:
                self.emit_event("assistant_reasoning", {"step": step_payload})

        def emit_debug(payload: dict[str, Any]) -> None:
            if stream and self.emit_event is not None:
                self.emit_event("assistant_debug", payload)

        for _ in range(self.max_turns):
            step = self.state_manager.start_step(session_state)
            try:
                decision = decision_engine.decide(
                    query=query,
                    history_messages=history_messages,
                    memory_summary=None,
                    tools=decision_tools,
                )
            except Exception as exc:
                logger.exception("Agent loop decision failed.", exc_info=exc)
                decision = None

            completion = proxy_client.last_completion
            completion_message = self._extract_first_message(completion) if completion is not None else None
            content = _extract_content_text(self._read_attr(completion_message, "content"))

            if decision is None or decision.decision_type == DecisionType.decision_error:
                session_state.final_response = {
                    "message": "普通对话生成失败，请稍后再试。",
                    "chat_answer": "",
                    "response_streamed": False,
                    "tool_trace": tool_trace,
                    "reasoning_trace": reasoning_trace,
                }
                session_state.status = "failed"
                self.tracer.record_termination(
                    conversation_id=conversation_id,
                    session_id=session_id,
                    step_index=step.step_index,
                    status="failed",
                    reason_summary=getattr(decision, "error_message", None) or "decision_failed",
                )
                return session_state

            if decision.thought:
                emit_reasoning(
                    AssistantReasoningStep(
                        step_type="thought",
                        content=decision.thought,
                    )
                )

            if decision.decision_type == DecisionType.final_answer:
                final_answer = decision.final_answer or ""
                response_streamed = False
                if stream and self.emit_event is not None and final_answer and "Final Answer:" not in content:
                    self._emit_text_deltas(final_answer)
                    response_streamed = True

                response_payload: dict[str, Any]
                if retrieval_response is not None:
                    response_payload = {
                        "intent": Intent.rag_retrieval,
                        "message": retrieval_response.message,
                        "answer": final_answer or retrieval_response.answer,
                        "references": _to_jsonable(retrieval_response.references),
                        "snippets": _to_jsonable(retrieval_response.snippets),
                        "related_files": _to_jsonable(retrieval_response.related_files),
                        "response_streamed": response_streamed,
                        "tool_trace": tool_trace,
                        "reasoning_trace": reasoning_trace,
                    }
                else:
                    response_payload = {
                        "intent": Intent.general_chat,
                        "message": None,
                        "chat_answer": final_answer,
                        "response_streamed": response_streamed,
                        "tool_trace": tool_trace,
                        "reasoning_trace": reasoning_trace,
                    }

                session_state.final_response = response_payload
                session_state.status = "completed"
                self.tracer.record_termination(
                    conversation_id=conversation_id,
                    session_id=session_id,
                    step_index=step.step_index,
                    status="completed",
                    reason_summary="final_answer",
                )
                return session_state

            if decision.decision_type == DecisionType.tool_arguments_error:
                # The model attempted tool calling but produced invalid arguments; feed a synthetic tool error
                # back and allow one self-correction.
                if retry_used:
                    session_state.final_response = {
                        "message": "工具调用失败，请稍后再试。",
                        "chat_answer": "",
                        "response_streamed": False,
                        "tool_trace": tool_trace,
                        "reasoning_trace": reasoning_trace,
                    }
                    session_state.status = "failed"
                    self.tracer.record_termination(
                        conversation_id=conversation_id,
                        session_id=session_id,
                        step_index=step.step_index,
                        status="failed",
                        reason_summary="tool_arguments_error",
                    )
                    return session_state
                tool_name = ""
                call_id = f"call-err-{step.step_index}"
                raw_tool_calls = list(self._read_attr(completion_message, "tool_calls") or [])
                normalized_tool_calls: list[dict[str, Any]] = []
                if raw_tool_calls:
                    for idx, raw in enumerate(raw_tool_calls, start=1):
                        raw_id = self._read_attr(raw, "id") or f"{call_id}-{idx}"
                        fn = self._read_attr(raw, "function")
                        fn_name = str(self._read_attr(fn, "name") or "")
                        raw_args = self._read_attr(fn, "arguments") or "{}"
                        if not isinstance(raw_args, str):
                            raw_args = json.dumps(raw_args, ensure_ascii=False, default=str)
                        normalized_tool_calls.append(
                            {
                                "id": str(raw_id),
                                "type": "function",
                                "function": {"name": fn_name, "arguments": raw_args},
                            }
                        )
                        if idx == 1:
                            tool_name = fn_name
                            call_id = str(raw_id)
                self.state_manager.record_tool_call(
                    session_state,
                    tool_name=tool_name or "unknown_tool",
                    arguments={},
                    call_id=str(call_id),
                )
                emit_reasoning(
                    AssistantReasoningStep(
                        step_type="action",
                        content=f"调用工具 {tool_name or 'unknown_tool'}",
                        tool_name=tool_name or "unknown_tool",
                        tool_args={},
                    )
                )
                error_message = decision.error_message or "Tool arguments must be valid JSON object."
                result = {
                    "ok": False,
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": error_message,
                        "retryable": True,
                    },
                }
                tool_trace.append(
                    {
                        "tool_name": tool_name or "unknown_tool",
                        "tool_args": {},
                        "status": "error",
                    }
                )
                self.tracer.record_action(
                    conversation_id=conversation_id,
                    session_id=session_id,
                    step_index=step.step_index,
                    decision_type=DecisionType.tool_arguments_error.value,
                    tool_name=tool_name or "unknown_tool",
                    tool_args={},
                    status="error",
                )
                messages.append({"role": "assistant", "content": content, "tool_calls": normalized_tool_calls})
                observation_content = json.dumps(_to_jsonable(result), ensure_ascii=False, default=str)
                emit_reasoning(
                    AssistantReasoningStep(
                        step_type="observation",
                        content=_summarize_observation(tool_name=tool_name or "unknown_tool", result=result),
                        tool_name=tool_name or "unknown_tool",
                        tool_args={},
                        status="error",
                    )
                )
                self.tracer.record_observation(
                    conversation_id=conversation_id,
                    session_id=session_id,
                    step_index=step.step_index,
                    tool_name=tool_name or "unknown_tool",
                    tool_args={},
                    observation=result,
                    status="error",
                    error_code="INVALID_ARGUMENT",
                    error_message=error_message,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": observation_content,
                    }
                )
                self.state_manager.record_tool_observation(
                    session_state,
                    call_id=str(call_id),
                    observation=observation_content,
                    metadata={"ok": False, "code": "INVALID_ARGUMENT"},
                )
                has_tool_error = True
                has_non_retryable_error = False
                # Continue loop to let the model self-correct once.
                self.state_manager.finalize_step(session_state, step)
                retry_used = True
                continue

            if decision.decision_type != DecisionType.tool_call:
                session_state.final_response = {
                    "message": "普通对话生成失败，请稍后再试。",
                    "chat_answer": "",
                    "response_streamed": False,
                    "tool_trace": tool_trace,
                    "reasoning_trace": reasoning_trace,
                }
                session_state.status = "failed"
                self.tracer.record_termination(
                    conversation_id=conversation_id,
                    session_id=session_id,
                    step_index=step.step_index,
                    status="failed",
                    reason_summary=decision.decision_type.value,
                )
                return session_state

            # tool-calling branch (model tool_calls)
            tool_calls_payload: list[dict[str, Any]] = []
            for idx, tool_call in enumerate(decision.tool_calls, start=1):
                call_id = tool_call.call_id or f"call-{step.step_index}-{idx}"
                raw_arguments = json.dumps(dict(tool_call.tool_args), ensure_ascii=False, default=str)
                tool_calls_payload.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": tool_call.tool_name, "arguments": raw_arguments},
                    }
                )
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls_payload})

            has_tool_error = False
            has_non_retryable_error = False

            for idx, tool_call in enumerate(decision.tool_calls, start=1):
                call_id = tool_call.call_id or f"call-{step.step_index}-{idx}"
                tool_name = tool_call.tool_name
                tool_args = dict(tool_call.tool_args or {})
                argument_error = None

                cache_key = None
                if argument_error is None:
                    cache_key = self._build_tool_cache_key(tool_name, tool_args)
                reused_cached_result = False

                # Record activity into session state, so termination policies reflect real tool work.
                self.state_manager.record_tool_call(
                    session_state,
                    tool_name=tool_name,
                    arguments=dict(tool_args),
                    call_id=str(call_id),
                )

                emit_reasoning(
                    AssistantReasoningStep(
                        step_type="action",
                        content=f"调用工具 {tool_name}",
                        tool_name=tool_name,
                        tool_args=dict(tool_args),
                    )
                )

                tool_def = None
                try:
                    tool_def = get_tool(tool_name)
                except KeyError:
                    tool_def = None
                except Exception as exc:
                    logger.debug("Unexpected error while resolving tool definition: %s", tool_name, exc_info=exc)
                    tool_def = None

                if tool_def is not None:
                    guardrail = self.guardrails.validate_tool_call(
                        session_state,
                        tool_definition=tool_def,
                        tool_call=self._to_reasoning_tool_call(tool_name, tool_args),
                        confirmation=False,
                    )
                    if not guardrail.allowed:
                        argument_error = guardrail.detail or "Tool call blocked by guardrails."

                if argument_error:
                    result = {
                        "ok": False,
                        "error": {
                            "code": "INVALID_ARGUMENT",
                            "message": argument_error,
                            "retryable": True,
                        },
                    }
                else:
                    cached = tool_result_cache.get(cache_key) if cache_key else None
                    if cached is not None:
                        result = cached
                        reused_cached_result = True
                    else:
                        emit_debug(
                            {
                                "stage": "tool_start",
                                "tool_name": tool_name,
                                "tool_args": tool_args,
                                "message": f"调用工具 {tool_name}",
                            }
                        )
                        dispatcher_call = DispatcherToolCall(tool_name=tool_name, arguments=tool_args)
                        dispatcher_result = self.tool_dispatcher.execute(dispatcher_call)
                        result = dispatcher_result.to_legacy_dict()

                        if result.get("ok"):
                            if cache_key:
                                tool_result_cache[cache_key] = result
                            if tool_name == "search_knowledge_base":
                                tool_data = result.get("data")
                                if isinstance(tool_data, AssistantResponse):
                                    retrieval_response = tool_data
                                elif isinstance(tool_data, dict) and retrieval_response is None:
                                    retrieval_response = AssistantResponse.model_validate(tool_data)

                if not reused_cached_result:
                    status_text = "成功" if bool(result.get("ok")) else "失败"
                    emit_debug(
                        {
                            "stage": "tool_result",
                            "tool_name": tool_name,
                            "tool_args": tool_args,
                            "message": f"工具 {tool_name} 调用{status_text}",
                        }
                    )
                    tool_trace.append(
                        {
                            "tool_name": tool_name,
                            "tool_args": dict(tool_args),
                            "status": "success" if bool(result.get("ok")) else "error",
                        }
                    )

                self.tracer.record_action(
                    conversation_id=conversation_id,
                    session_id=session_id,
                    step_index=step.step_index,
                    decision_type=DecisionType.tool_call.value,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    status="success" if bool(result.get("ok")) else "error",
                )

                # Legacy compatibility: allow the model to self-correct once on validation errors.
                if not result.get("ok"):
                    error_payload = result.get("error") or {}
                    if error_payload.get("code") == "INVALID_ARGUMENT":
                        error_payload = dict(error_payload)
                        error_payload["retryable"] = True
                        result["error"] = error_payload

                observation_content = json.dumps(_to_jsonable(result), ensure_ascii=False, default=str)
                emit_reasoning(
                    AssistantReasoningStep(
                        step_type="observation",
                        content=_summarize_observation(tool_name=tool_name, result=result),
                        tool_name=tool_name,
                        tool_args=dict(tool_args),
                        status="success" if bool(result.get("ok")) else "error",
                    )
                )
                self.tracer.record_observation(
                    conversation_id=conversation_id,
                    session_id=session_id,
                    step_index=step.step_index,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    observation=result,
                    status="success" if bool(result.get("ok")) else "error",
                    error_code=(result.get("error") or {}).get("code") if not result.get("ok") else None,
                    error_message=(result.get("error") or {}).get("message") if not result.get("ok") else None,
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": observation_content,
                    }
                )

                self.state_manager.record_tool_observation(
                    session_state,
                    call_id=str(call_id),
                    observation=observation_content,
                    metadata={"ok": bool(result.get("ok"))},
                )
                try:
                    self.memory_manager.record_observation(
                        session_state,
                        observation_record=session_state.observations[-1],
                    )
                except Exception as exc:
                    # Memory updates must not break the runtime loop, but should be observable.
                    logger.debug("Memory manager failed to record observation", exc_info=exc)

                if not result.get("ok"):
                    has_tool_error = True
                    if not bool((result.get("error") or {}).get("retryable")):
                        has_non_retryable_error = True

            self.state_manager.finalize_step(session_state, step)

            if has_tool_error:
                if has_non_retryable_error or retry_used:
                    session_state.final_response = {
                        "message": "工具调用失败，请稍后再试。",
                        "chat_answer": "",
                        "response_streamed": False,
                        "tool_trace": tool_trace,
                        "reasoning_trace": reasoning_trace,
                    }
                    session_state.status = "failed"
                    self.tracer.record_termination(
                        conversation_id=conversation_id,
                        session_id=session_id,
                        step_index=step.step_index,
                        status="failed",
                        reason_summary="tool_error",
                    )
                    return session_state
                retry_used = True

            termination = self.termination.evaluate(session_state)
            if termination.should_stop and session_state.final_response is None:
                session_state.final_response = {
                    "message": termination.user_message or "普通对话生成失败，请稍后再试。",
                    "chat_answer": "",
                    "response_streamed": False,
                    "tool_trace": tool_trace,
                    "reasoning_trace": reasoning_trace,
                }
                session_state.status = termination.status
                self.tracer.record_termination(
                    conversation_id=conversation_id,
                    session_id=session_id,
                    step_index=step.step_index,
                    status=termination.status,
                    reason_summary=termination.reason,
                )
                return session_state

        session_state.final_response = {
            "message": "普通对话生成失败，请稍后再试。",
            "chat_answer": "",
            "response_streamed": False,
            "tool_trace": tool_trace,
            "reasoning_trace": reasoning_trace,
        }
        session_state.status = "failed"
        self.tracer.record_termination(
            conversation_id=conversation_id,
            session_id=session_id,
            step_index=session_state.step_count,
            status="failed",
            reason_summary="max_turns_exceeded",
        )
        return session_state

    def _load_history(self, session_state: AgentSessionState) -> list[Any]:
        if self.history_messages is not None:
            return list(self.history_messages)
        if self.conversation_service is None:
            return []
        try:
            limit = int(getattr(self.settings, "assistant_max_context_blocks", 4) or 4)
        except Exception:
            limit = 4
        try:
            return list(
                self.conversation_service.get_recent_messages(
                    conversation_id=session_state.conversation_id,
                    user_id=session_state.user_id,
                    limit=limit,
                )
            )
        except Exception as exc:
            logger.debug("Failed to load recent history messages", exc_info=exc)
            return []

    def _should_send_tools(self) -> bool:
        # For compatibility with existing tests/behavior:
        # - When only work_service is configured (no upload_service), run in legacy ReAct mode.
        # - Otherwise prefer tool calling mode to surface tool schemas for the model.
        work_service = getattr(self.tool_dispatcher, "work_service", None)
        upload_service = getattr(self.tool_dispatcher, "upload_service", None)
        return not (work_service is not None and upload_service is None)

    def _build_tool_schemas(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for tool in list_tools():
            if not self._should_expose_tool(tool.backend_metadata):
                continue
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": self._thaw_mapping(tool.parameters),
                    },
                }
            )
        return tools

    def _should_expose_tool(self, metadata: Any) -> bool:
        if getattr(metadata, "placeholder_response", None) is not None:
            return True
        service_attr = getattr(metadata, "service_attr", None)
        if service_attr is None:
            return False
        if service_attr == "ai_rag_service":
            return getattr(self.tool_dispatcher, "ai_rag_service", None) is not None
        return getattr(self.tool_dispatcher, service_attr, None) is not None

    def _thaw_mapping(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {k: self._thaw_mapping(v) for k, v in value.items()}
        if isinstance(value, tuple):
            return [self._thaw_mapping(v) for v in value]
        if isinstance(value, list):
            return [self._thaw_mapping(v) for v in value]
        return value

    def _build_tool_cache_key(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        normalized = _to_jsonable(tool_args)
        return f"{tool_name}:{json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)}"

    def _extract_first_message(self, completion: Any) -> Any:
        choices = self._read_attr(completion, "choices") or []
        if not choices:
            return None
        first_choice = choices[0]
        return self._read_attr(first_choice, "message")

    @staticmethod
    def _read_attr(payload: Any, name: str) -> Any:
        if payload is None:
            return None
        if isinstance(payload, Mapping):
            return payload.get(name)
        return getattr(payload, name, None)

    def _emit_text_deltas(self, text: str, *, chunk_size: int = 1) -> None:
        if self.emit_event is None or not text:
            return
        if chunk_size <= 0:
            chunk_size = 1
        for idx in range(0, len(text), chunk_size):
            chunk = text[idx : idx + chunk_size]
            if chunk:
                self.emit_event("assistant_delta", {"delta": chunk})

    @staticmethod
    def _to_reasoning_tool_call(tool_name: str, tool_args: dict[str, Any]) -> Any:
        # GuardrailsPolicy expects app.ai.agent.reasoning.models.ToolCall.
        from app.ai.agent.reasoning.models import ToolCall

        return ToolCall(tool_name=tool_name, tool_args=tool_args)
