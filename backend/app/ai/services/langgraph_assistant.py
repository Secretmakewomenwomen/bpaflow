
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator, Mapping
from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from openai import OpenAI

from app.ai.agent.facade import AgentFacade
from app.ai.services.ai_conversation_service import AiConversationService
from app.ai.services.flow_chart_interrupt_service import FlowChartInterruptService
from app.ai.services.ai_rag_service import AIRagService
from app.core.config import Settings
from app.schemas.ai import (
    AssistantResponse,
    AssistantSnippet,
    ConversationMessageResponse,
    Intent,
    MessageRole,
    RelatedFile,
)
from app.services.chapter_flow_service import ChapterFlowService
from app.services.upload_service import UploadService
from app.services.work_service import WorkService

_SUMMARY_DEGRADE_MESSAGE = "摘要生成能力未配置，已返回检索结果。"
_SUMMARY_FAILURE_MESSAGE = "摘要生成失败，已返回检索结果。"
_GENERAL_CHAT_DEGRADE_MESSAGE = "普通对话能力未配置。"
logger = logging.getLogger(__name__)
_CHECKPOINTER_SETUP_LOCK = threading.Lock()
_INITIALIZED_CHECKPOINTER_DSNS: set[str] = set()


def _get_postgres_saver_class():
    """延迟导入 PostgresSaver，避免模块加载时就强依赖 checkpoint 扩展。"""
    from langgraph.checkpoint.postgres import PostgresSaver

    return PostgresSaver


class AiAssistantState(TypedDict, total=False):
    conversation_id: str
    query: str
    user_id: str
    stream: bool
    history_messages: list[dict[str, Any]]
    intent: str | None
    retrieval_response: dict[str, Any]
    snippets: list[dict[str, Any]]
    related_files: list[dict[str, Any]]
    references: list[dict[str, Any]]
    tool_trace: list[dict[str, Any]]
    reasoning_trace: list[dict[str, Any]]
    answer: str
    message: str | None
    chat_answer: str
    status: str
    pending_action: dict[str, Any] | None
    artifact: dict[str, Any] | None
    actions: list[dict[str, Any]]
    response_streamed: bool
    response: dict[str, Any]
    assistant_message: dict[str, Any]


class LangGraphAssistantService:
    def __init__(
        self,
        settings: Settings,
        conversation_service: AiConversationService,
        tenant_id: str | None = None,
        rag_service: AIRagService | None = None,
        upload_service: UploadService | None = None,
        work_service: WorkService | None = None,
        flow_chart_interrupt_service: FlowChartInterruptService | None = None,
        openai_client: OpenAI | None = None,
        mcp_client: Any | None = None,
        checkpointer_factory: Any | None = None,
        checkpointer_dsn: str | None = None,
    ) -> None:
        """初始化 LangGraph 助手服务，注入会话、RAG、工具服务和可选的 OpenAI 客户端。"""
        self.settings = settings
        self.conversation_service = conversation_service
        self.tenant_id = tenant_id
        self.rag_service = rag_service or AIRagService(settings)
        self.upload_service = upload_service
        self.work_service = work_service
        self.flow_chart_interrupt_service = flow_chart_interrupt_service or self._build_flow_chart_interrupt_service()
        self._openai_client = openai_client
        self._mcp_client = mcp_client
        self._checkpointer_factory = checkpointer_factory
        self._checkpointer_dsn = checkpointer_dsn or settings.postgres_database_url
        self._facade = AgentFacade(
            settings=settings,
            conversation_service=self.conversation_service,
            tenant_id=self.tenant_id,
            rag_service=self.rag_service,
            upload_service=self.upload_service,
            work_service=self.work_service,
            flow_chart_interrupt_service=self.flow_chart_interrupt_service,
            openai_client=self._openai_client,
            openai_client_factory=self._get_openai_client,
            mcp_client=self._mcp_client,
        )

    def _build_flow_chart_interrupt_service(self) -> FlowChartInterruptService | None:
        if self.upload_service is None:
            return None
        upload_settings = getattr(self.upload_service, "settings", None)
        upload_db = getattr(self.upload_service, "db", None)
        if upload_settings is None or upload_db is None:
            return FlowChartInterruptService(
                upload_service=self.upload_service,
                chapter_flow_service=None,
            )
        return FlowChartInterruptService(
            upload_service=self.upload_service,
            chapter_flow_service=ChapterFlowService(
                settings=upload_settings,
                db=upload_db,
            ),
        )

    def _sync_facade_dependencies(self) -> None:
        # Tests sometimes mutate service dependencies (e.g. rag_service) after init; keep facade aligned.
        self._facade.settings = self.settings
        self._facade.conversation_service = self.conversation_service
        self._facade.tenant_id = self.tenant_id
        self._facade.rag_service = self.rag_service
        self._facade.upload_service = self.upload_service
        self._facade.work_service = self.work_service
        self._facade.flow_chart_interrupt_service = self.flow_chart_interrupt_service
        self._facade._mcp_client = self._mcp_client
        if self._mcp_client is not None:
            if hasattr(self._mcp_client, "rag_service"):
                self._mcp_client.rag_service = self.rag_service
            if hasattr(self._mcp_client, "upload_service"):
                self._mcp_client.upload_service = self.upload_service
            if hasattr(self._mcp_client, "work_service"):
                self._mcp_client.work_service = self.work_service

    def _create_graph_definition(self):
        """定义当前助手使用的状态图节点与路由关系。"""
        graph = StateGraph(AiAssistantState)
        graph.add_node("load_history", self._load_history_node)
        graph.add_node("run_agent_loop", self._run_agent_loop_node)
        graph.add_node("build_response", self._build_response_node)
        graph.add_node("persist_message", self._persist_message_node)

        graph.add_edge(START, "load_history")
        graph.add_edge("load_history", "run_agent_loop")
        graph.add_edge("run_agent_loop", "build_response")
        graph.add_edge("build_response", "persist_message")
        graph.add_edge("persist_message", END)
        return graph

    def build_graph(self, *, checkpointer: Any | None):
        """基于状态图定义编译出可执行 graph，并按需挂上 checkpointer。"""
        graph = self._create_graph_definition()
        return graph.compile(checkpointer=checkpointer)

    def export_graph_mermaid(self) -> str:
        """导出当前 graph 的 Mermaid 文本，方便调试和查看节点流转。"""
        self._sync_facade_dependencies()
        return self._facade.export_graph_mermaid(build_graph=self.build_graph)

    def stream_invoke(
        self,
        *,
        conversation_id: str,
        query: str,
        user_id: str,
    ) -> Iterator[dict[str, Any]]:
        """执行流式对话请求，并把 LangGraph 事件转换成前端可消费的 SSE 事件。"""
        self._sync_facade_dependencies()
        yield from self._facade.stream_invoke(
            conversation_id=conversation_id,
            query=query,
            user_id=user_id,
            build_graph=self.build_graph,
            checkpointer_context=self._create_checkpointer_context,
            create_assistant_message=self.conversation_service.create_assistant_message,
        )

    def _create_checkpointer_context(self):
        """创建 checkpoint 上下文；测试环境可注入自定义工厂，生产默认使用 PostgresSaver。"""
        if self._checkpointer_factory is not None:
            return self._checkpointer_factory()
        return _get_postgres_saver_class().from_conn_string(self._checkpointer_dsn)

    def _load_history_node(self, state: AiAssistantState) -> AiAssistantState:
        """图节点：加载当前会话最近几轮历史消息，供后续摘要和对话生成使用。"""
        return {
            "history_messages": [
                message.model_dump(mode="json")
                for message in self.conversation_service.get_recent_messages(
                    conversation_id=state.get("conversation_id", ""),
                    user_id=state.get("user_id", ""),
                    limit=self.settings.assistant_max_context_blocks,
                )
            ]
        }

    def _run_agent_loop_node(self, state: AiAssistantState) -> AiAssistantState:
        """图节点：统一执行模型驱动的 tool-calling agent loop。"""
        self._sync_facade_dependencies()
        stream = bool(state.get("stream"))
        return self._facade.run_agent_loop(
            conversation_id=state.get("conversation_id", ""),
            query=state.get("query", ""),
            history_messages=self._restore_history_messages(state.get("history_messages", [])),
            user_id=state.get("user_id", ""),
            stream=stream,
            emit_event=self._write_stream_event if stream else None,
        )

    def _build_response_node(self, state: AiAssistantState) -> AiAssistantState:
        """图节点：把前面各节点产出的中间状态组装成统一的 AssistantResponse。"""
        self._sync_facade_dependencies()
        response = self._facade.build_response(state=state)
        self._stream_response_if_needed(state=state, response=response)
        return {"response": response.model_dump(mode="json")}

    def _persist_message_node(self, state: AiAssistantState) -> AiAssistantState:
        """图节点：把最终助手回复写入业务消息表，并返回持久化后的消息对象。"""
        response = state.get("response")
        if response is None:
            return {}
        response_model = self._restore_assistant_response(response)
        assistant_message = self.conversation_service.create_assistant_message(
            conversation_id=state.get("conversation_id", ""),
            user_id=state.get("user_id", ""),
            response=response_model,
        )
        return {"assistant_message": assistant_message.model_dump(mode="json")}

    def _stream_response_if_needed(
        self,
        *,
        state: AiAssistantState,
        response: AssistantResponse,
    ) -> None:
        """在当前响应尚未通过增量流输出时，补发一次完整文本 delta。"""
        if not state.get("stream") or state.get("response_streamed"):
            return
        text = response.answer.strip() or (response.message or "").strip()
        if not text:
            return
        self._write_stream_event("assistant_delta", {"delta": text})

    def _write_stream_event(self, event: str, data: dict[str, Any]) -> None:
        """向 LangGraph 的 custom stream 写入一条前端事件。"""
        writer = get_stream_writer()
        writer({"event": event, "data": data})

    def run_agent_loop(
        self,
        *,
        query: str,
        history_messages: list[ConversationMessageResponse],
        user_id: str,
        stream: bool = False,
        max_turns: int = 6,
        conversation_id: str | None = None,
    ) -> AiAssistantState:
        """兼容入口：委托 AgentFacade 执行 ReAct runtime。"""
        self._sync_facade_dependencies()
        return self._facade.run_agent_loop(
            conversation_id=conversation_id,
            query=query,
            history_messages=history_messages,
            user_id=user_id,
            stream=stream,
            max_turns=max_turns,
            emit_event=None,
        )

    def resume_flow_chart_generation(
        self,
        *,
        conversation_id: str,
        user_id: str,
        action_id: str,
        upload_id: int,
    ) -> ConversationMessageResponse:
        self._sync_facade_dependencies()
        if isinstance(upload_id, bool) or not isinstance(upload_id, int) or upload_id <= 0:
            raise ValueError("resume_flow_chart_generation requires a single upload_id.")
        self._facade.validate_pending_flow_chart_action(
            conversation_id=conversation_id,
            user_id=user_id,
            action_id=action_id,
            upload_id=upload_id,
        )

        resume_payload = {
            "action_id": action_id,
            "upload_id": upload_id,
        }
        try:
            with self._create_checkpointer_context() as checkpointer:
                graph = self.build_graph(checkpointer=checkpointer)
                graph_result = graph.invoke(
                    Command(resume=resume_payload),
                    config={"configurable": {"thread_id": conversation_id}},
                )
            if isinstance(graph_result, dict):
                assistant_message = graph_result.get("assistant_message")
                if isinstance(assistant_message, ConversationMessageResponse):
                    return assistant_message
                if isinstance(assistant_message, dict):
                    return ConversationMessageResponse.model_validate(assistant_message)
        except (RuntimeError, ValueError):
            pass

        # Compatibility fallback when the graph is not resumable (e.g. tests without a real checkpointer).
        fallback_response = self._facade.resume_flow_chart_generation(
            conversation_id=conversation_id,
            user_id=user_id,
            action_id=action_id,
            upload_id=upload_id,
        )
        return self.conversation_service.create_assistant_message(
            conversation_id=conversation_id,
            user_id=user_id,
            response=fallback_response,
        )

    def _to_jsonable(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, (Intent, MessageRole)):
            return value.value
        if isinstance(value, Mapping):
            return {key: self._to_jsonable(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [self._to_jsonable(item) for item in value]
        return value

    def _restore_history_messages(
        self,
        history_messages: list[ConversationMessageResponse] | list[dict[str, Any]],
    ) -> list[ConversationMessageResponse]:
        restored: list[ConversationMessageResponse] = []
        for item in history_messages:
            if isinstance(item, ConversationMessageResponse):
                restored.append(item)
            elif isinstance(item, dict):
                restored.append(ConversationMessageResponse.model_validate(item))
        return restored

    def _restore_assistant_response(self, payload: AssistantResponse | dict[str, Any]) -> AssistantResponse:
        if isinstance(payload, AssistantResponse):
            return payload
        return AssistantResponse.model_validate(payload)

    def _extract_completion_content(self, content: Any, *, strip: bool = True) -> str:
        text = self._extract_text_parts(content)
        if strip:
            return text.strip()
        return text

    def _extract_text_parts(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, (list, tuple)):
            return "".join(self._extract_text_parts(item) for item in content)
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
                return self._extract_text_parts(nested_content)
            return ""

        text_attr = getattr(content, "text", None)
        if isinstance(text_attr, str):
            return text_attr
        if text_attr is not None:
            return self._extract_text_parts(text_attr)

        nested_content = getattr(content, "content", None)
        if nested_content is not None and nested_content is not content:
            return self._extract_text_parts(nested_content)
        return ""

    def _read_provider_field(self, payload: Any, field_name: str) -> Any:
        if isinstance(payload, Mapping):
            return payload.get(field_name)
        return getattr(payload, field_name, None)

    def generate_summary(
        self,
        *,
        query: str,
        snippets: list[AssistantSnippet],
        related_files: list[RelatedFile],
        history_messages: list[ConversationMessageResponse],
    ) -> str:
        """一次性生成检索摘要，用于非流式摘要场景。"""
        context_blocks = self._build_summary_context(
            snippets=snippets,
            related_files=related_files,
            history_messages=history_messages,
        )
        client = self._get_openai_client()
        completion = client.chat.completions.create(
            model=self.settings.assistant_llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "你是文档检索助手。请仅基于给定上下文生成简洁摘要，不要编造内容。",
                },
                {
                    "role": "user",
                    "content": (
                        f"用户问题：{query}\n\n"
                        "检索上下文：\n"
                        f"{self._render_context_blocks(context_blocks)}\n\n"
                        "请输出中文摘要。"
                    ),
                },
            ],
            temperature=0.2,
        )
        choices = getattr(completion, "choices", None)
        if not choices:
            return ""
        first_choice = choices[0]
        message = self._read_provider_field(first_choice, "message")
        if message is None:
            return ""
        content = self._read_provider_field(message, "content")
        return self._extract_completion_content(content)

    def iter_summary_reply(
        self,
        *,
        query: str,
        snippets: list[AssistantSnippet],
        related_files: list[RelatedFile],
        history_messages: list[ConversationMessageResponse],
    ) -> Iterator[str]:
        """流式生成检索摘要，把模型输出按分片逐段返回。"""
        context_blocks = self._build_summary_context(
            snippets=snippets,
            related_files=related_files,
            history_messages=history_messages,
        )
        messages = [
            {
                "role": "system",
                "content": "你是文档检索助手。请仅基于给定上下文生成简洁摘要，不要编造内容。",
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{query}\n\n"
                    "检索上下文：\n"
                    f"{self._render_context_blocks(context_blocks)}\n\n"
                    "请输出中文摘要。"
                ),
            },
        ]
        yield from self._iter_chat_completion_deltas(messages=messages, temperature=0.2)

    def generate_chat_reply(
        self,
        *,
        query: str,
        history_messages: list[ConversationMessageResponse],
    ) -> str:
        """一次性生成普通对话回复，用于非流式聊天场景。"""
        client = self._get_openai_client()
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": "你是工作台里的 AI 助手。正常问题直接自然回答；只有用户明确要求查文件、查资料、检索文档时，系统才会走检索链路。",
            }
        ]
        for history_message in history_messages[-4:]:
            role = "assistant" if history_message.role == MessageRole.assistant else "user"
            text = history_message.content.strip()
            if not text:
                continue
            messages.append({"role": role, "content": text})
        messages.append({"role": "user", "content": query})

        completion = client.chat.completions.create(
            model=self.settings.assistant_llm_model,
            messages=messages,
            temperature=0.4,
        )
        choices = getattr(completion, "choices", None)
        if not choices:
            return ""
        first_choice = choices[0]
        message = self._read_provider_field(first_choice, "message")
        if message is None:
            return ""
        content = self._read_provider_field(message, "content")
        return self._extract_completion_content(content)

    def iter_chat_reply(
        self,
        *,
        query: str,
        history_messages: list[ConversationMessageResponse],
    ) -> Iterator[str]:
        """流式生成普通对话回复，把模型增量内容逐段暴露给上层。"""
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": "你是工作台里的 AI 助手。正常问题直接自然回答；只有用户明确要求查文件、查资料、检索文档时，系统才会走检索链路。",
            }
        ]
        for history_message in history_messages[-4:]:
            role = "assistant" if history_message.role == MessageRole.assistant else "user"
            text = history_message.content.strip()
            if not text:
                continue
            messages.append({"role": role, "content": text})
        messages.append({"role": "user", "content": query})
        yield from self._iter_chat_completion_deltas(messages=messages, temperature=0.4)

    def _iter_chat_completion_deltas(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
    ) -> Iterator[str]:
        """统一封装 OpenAI Chat Completions 流式调用，并提取文本 delta。"""
        client = self._get_openai_client()
        stream = client.chat.completions.create(
            model=self.settings.assistant_llm_model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            first_choice = choices[0]
            delta = self._read_provider_field(first_choice, "delta")
            if delta is None:
                continue
            content = self._read_provider_field(delta, "content")
            text = self._extract_completion_content(content, strip=False)
            if text:
                yield text

    def _get_openai_client(self) -> OpenAI:
        """懒加载并缓存 OpenAI 客户端实例。"""
        if self._openai_client is None:
            self._openai_client = OpenAI(
                base_url=self._normalize_assistant_base_url(self.settings.assistant_llm_base_url),
                api_key=self.settings.assistant_llm_api_key,
            )
        return self._openai_client

    def _is_summary_model_configured(self) -> bool:
        """检查摘要/聊天模型配置是否齐全。"""
        return bool(
            self.settings.assistant_llm_base_url
            and self.settings.assistant_llm_api_key
            and self.settings.assistant_llm_model
        )

    def _build_summary_context(
        self,
        *,
        snippets: list[AssistantSnippet],
        related_files: list[RelatedFile],
        history_messages: list[ConversationMessageResponse],
    ) -> list[str]:
        """构建摘要生成所需的上下文块，混合历史消息、片段和相关文件提示。"""
        seen: set[str] = set()
        blocks: list[str] = []

        for history_message in history_messages[-2:]:
            text = history_message.content.strip()
            if not text:
                continue
            blocks.append(f"[历史{history_message.role.value}] {text}")

        for snippet in snippets:
            text = snippet.text.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            blocks.append(f"[片段] {snippet.file_name}: {text}")
            if len(blocks) >= self.settings.assistant_max_context_blocks:
                break

        if len(blocks) < self.settings.assistant_max_context_blocks:
            for related_file in related_files:
                file_hint = related_file.file_name.strip()
                if not file_hint:
                    continue
                key = f"file:{file_hint}"
                if key in seen:
                    continue
                seen.add(key)
                blocks.append(f"[文件] {file_hint}")
                if len(blocks) >= self.settings.assistant_max_context_blocks:
                    break

        return blocks

    def _render_context_blocks(self, blocks: list[str]) -> str:
        """把上下文块数组渲染成带序号的文本，供提示词直接引用。"""
        if not blocks:
            return "（无可用上下文）"
        return "\n".join(f"{idx}. {block}" for idx, block in enumerate(blocks, start=1))

    def _normalize_assistant_base_url(self, base_url: str | None) -> str | None:
        """兼容火山方舟等网关地址，统一转换成 OpenAI SDK 可用的 base_url。"""
        if base_url is None:
            return None
        normalized = base_url.rstrip("/")
        if normalized.endswith("/api/coding"):
            return f"{normalized[:-len('/api/coding')]}/api/v3"
        return normalized

    def _is_empty_retrieval_response(self, response: AssistantResponse) -> bool:
        """判断当前检索结果是否为空命中。"""
        return (
            response.intent == Intent.rag_retrieval
            and response.answer == ""
            and response.snippets == []
            and response.related_files == []
        )

    def _degraded_summary_state(
        self,
        retrieval_response: AssistantResponse,
        *,
        message: str = _SUMMARY_DEGRADE_MESSAGE,
    ) -> AiAssistantState:
        """在摘要模型不可用或失败时，把检索结果降级包装成图状态。"""
        return {
            "message": message,
            "answer": retrieval_response.answer,
            "snippets": self._to_jsonable(retrieval_response.snippets),
            "related_files": self._to_jsonable(retrieval_response.related_files),
            "response_streamed": False,
        }


def initialize_postgres_checkpointer_for_dsn(dsn: str) -> None:
    """初始化指定 DSN 的 LangGraph checkpoint 表结构，只执行一次。"""
    if dsn in _INITIALIZED_CHECKPOINTER_DSNS:
        return

    with _CHECKPOINTER_SETUP_LOCK:
        if dsn in _INITIALIZED_CHECKPOINTER_DSNS:
            return

        with _get_postgres_saver_class().from_conn_string(dsn) as checkpointer:
            checkpointer.setup()

        _INITIALIZED_CHECKPOINTER_DSNS.add(dsn)


def initialize_postgres_checkpointer(settings: Settings) -> None:
    """初始化默认租户使用的 LangGraph checkpoint 表结构。"""
    initialize_postgres_checkpointer_for_dsn(settings.postgres_database_url)
