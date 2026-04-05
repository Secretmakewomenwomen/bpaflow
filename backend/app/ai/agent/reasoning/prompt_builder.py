from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable

from pydantic import ValidationError

from app.schemas.ai import ConversationMessageResponse, MessageRole

DEFAULT_SYSTEM_RULES = [
    "你是工作台里的 AI 助手。正常问题直接回答；当需要查用户、文件或资料时可调用工具。",
    "对于普通资料检索问题，优先使用一次 search_knowledge_base 后直接回答，不要重复调用相同工具和相同参数。",
    "如果用户一次询问多个并列主题，必须先汇总每个主题各自命中的候选文件，再给出综合结论。",
    "不能因为某一个主题先命中，就立刻围绕单个文件持续深挖。",
    "只有在用户明确要求继续查看某个具体文件，或者你已经先完成多主题候选汇总后，才可以继续调用 get_file_detail 或追加定向检索。",
    "只有当用户明确要求某个具体文件的详情、元数据或下载信息时，才调用 get_file_detail。",
    "工具返回错误时，你最多允许自纠一次，再继续给出最终结论。",
]

TEXT_REACT_PROTOCOL_RULES = [
    "使用纯文本 ReAct 协议回复，不要调用 OpenAI tool_calls。",
    '如果需要使用工具，严格输出两行：`Thought: ...` 和 `Action: {"tool_name":"...", "tool_args": {...}}`。',
    "拿到 Observation 后继续推理；如果已经可以回答，严格输出两行：`Thought: ...` 和 `Final Answer: ...`。",
    "Final Answer 必须是完整、可直接展示给用户的最终回答，不能只写开头句、引导句或未完成的列举。",
    "不能只输出“我可以为你提供这些能力：”“主要有这些能力：”“包括以下几类：”这类未完成答案。",
]


class PromptBuilder:
    def __init__(self, *, system_rules: Iterable[str] | None = None, max_history: int = 4) -> None:
        self.system_rules = list(system_rules) if system_rules is not None else list(DEFAULT_SYSTEM_RULES)
        self.max_history = max(0, max_history)

    def build_messages(
        self,
        *,
        query: str,
        history_messages: Iterable[ConversationMessageResponse | dict[str, Any]] | None = None,
        memory_summary: str | None = None,
        decision_mode: str = "auto",
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._format_system_content()}
        ]
        if decision_mode == "text_react":
            messages.append({"role": "system", "content": "\n\n".join(TEXT_REACT_PROTOCOL_RULES)})
        if memory_summary:
            messages.append({"role": "system", "content": f"记住：{memory_summary}"})

        for history_message in self._take_recent_history(history_messages or []):
            role = "assistant" if history_message.role == MessageRole.assistant else "user"
            text = history_message.content.strip()
            if text:
                messages.append({"role": role, "content": text})

        messages.append({"role": "user", "content": query})
        return messages

    def _format_system_content(self) -> str:
        return "\n\n".join(self.system_rules)

    def _take_recent_history(
        self, history_messages: Iterable[ConversationMessageResponse | dict[str, Any]]
    ) -> list[ConversationMessageResponse]:
        restored: list[ConversationMessageResponse] = []
        for item in history_messages:
            if isinstance(item, ConversationMessageResponse):
                restored.append(item)
            elif isinstance(item, Mapping):
                try:
                    restored.append(ConversationMessageResponse.model_validate(item))
                except ValidationError:
                    continue
        if self.max_history <= 0:
            return []
        return restored[-self.max_history :]
