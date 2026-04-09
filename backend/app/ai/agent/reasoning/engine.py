from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable

from app.schemas.ai import ConversationMessageResponse

from .models import AgentDecision, DecisionType
from .parser import (
    extract_completion_text,
    extract_legacy_react_action,
    extract_legacy_react_final_answer,
    extract_legacy_react_thought,
    extract_tool_calls,
)
from .prompt_builder import PromptBuilder


class ReasoningEngine:
    def __init__(
        self,
        *,
        client: Any,
        prompt_builder: PromptBuilder,
        model: str,
        temperature: float = 0.2,
    ) -> None:
        """初始化决策引擎，注入模型客户端、PromptBuilder 和模型参数。"""
        self.client = client
        self.prompt_builder = prompt_builder
        self.model = model
        self.temperature = temperature

    def decide(
        self,
        *,
        query: str,
        history_messages: Iterable[ConversationMessageResponse] | None = None,
        memory_summary: str | None = None,
        tools: Iterable[dict[str, Any]] | None = None,
        decision_mode: str = "auto",
    ) -> AgentDecision:
        """构造 prompt、调用模型，并把原始返回解析成统一的 AgentDecision。"""
        messages = self.prompt_builder.build_messages(
            query=query,
            history_messages=history_messages or [],
            memory_summary=memory_summary,
            decision_mode=decision_mode,
        )
        request_kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        tools_list = list(tools or []) if decision_mode != "text_react" else []
        if tools_list:
            request_kwargs["tools"] = tools_list
            request_kwargs["tool_choice"] = "auto"

        completion = self.client.chat.completions.create(**request_kwargs)
        choices = self._extract_choices(completion)
        if not choices:
            return AgentDecision(
                decision_type=DecisionType.decision_error,
                error_message="Completion did not return any choices.",
            )

        message = self._extract_choice_message(choices[0])
        if message is None:
            return AgentDecision(
                decision_type=DecisionType.decision_error,
                error_message="Completion choice is missing message payload.",
            )
        tool_calls, tool_error = extract_tool_calls(message)
        content_text = extract_completion_text(self._get_message_content(message))
        thought = self._extract_reasoning_content(message) or extract_legacy_react_thought(content_text)
        if tool_error:
            return AgentDecision(
                decision_type=DecisionType.tool_arguments_error,
                thought=thought,
                error_message=tool_error,
            )
        if tool_calls:
            return AgentDecision(decision_type=DecisionType.tool_call, thought=thought, tool_calls=tool_calls)

        legacy_action = extract_legacy_react_action(content_text)
        if legacy_action is not None:
            return AgentDecision(decision_type=DecisionType.tool_call, thought=thought, tool_calls=[legacy_action])

        legacy_final = extract_legacy_react_final_answer(content_text)
        if legacy_final is not None:
            return AgentDecision(decision_type=DecisionType.final_answer, thought=thought, final_answer=legacy_final)

        return AgentDecision(decision_type=DecisionType.final_answer, thought=thought, final_answer=content_text)

    def _extract_choices(self, completion: Any) -> list[Any]:
        """兼容 dict/object 两种 completion 形态，提取 choices 列表。"""
        if isinstance(completion, Mapping):
            choices = completion.get("choices")
            if isinstance(choices, list):
                return choices
            return []
        choices = getattr(completion, "choices", None)
        if isinstance(choices, list):
            return choices
        return []

    def _extract_choice_message(self, choice: Any) -> Any:
        """从第一条 choice 中提取 message，兼容 dict/object 访问方式。"""
        if isinstance(choice, Mapping):
            return choice.get("message")
        return getattr(choice, "message", None)

    def _get_message_content(self, message_payload: Any) -> Any:
        """提取 message.content，并兼容直接把 message 当字符串返回的场景。"""
        if isinstance(message_payload, Mapping):
            content = message_payload.get("content")
        else:
            content = getattr(message_payload, "content", None)
        if content is None and isinstance(message_payload, str):
            return message_payload
        return content

    def _extract_reasoning_content(self, message_payload: Any) -> str | None:
        """优先读取模型原生 reasoning_content，提取结构化 thought 文本。"""
        if isinstance(message_payload, Mapping):
            direct = message_payload.get("reasoning_content")
            model_extra = message_payload.get("model_extra")
        else:
            direct = getattr(message_payload, "reasoning_content", None)
            model_extra = getattr(message_payload, "model_extra", None)

        reasoning_content = direct
        if reasoning_content is None and isinstance(model_extra, Mapping):
            reasoning_content = model_extra.get("reasoning_content")

        if not isinstance(reasoning_content, str):
            return None
        thought = reasoning_content.strip()
        return thought or None
