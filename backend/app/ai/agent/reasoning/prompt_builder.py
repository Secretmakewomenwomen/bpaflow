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
    "只有在你确认已经覆盖了用户主问题，并且当前回答不是中间过程说明时，才能结束并输出最终回答。",
    "如果你仍然需要检索资料、查看文件、补充证据、核对约束或补齐并列子问题，就不要提前结束。",
    "像“我先帮你看一下”“我来查一下”“稍等我分析一下”这类过程性话术，不算最终回答。",
    "如果问题依赖知识库、文件或业务数据，关键结论必须有工具结果或检索结果支撑后，才能结束。",
    "如果用户问题包含多个要求，只有在主要要求都已覆盖后，才可以结束。",
]

TEXT_REACT_PROTOCOL_RULES = [
    "使用纯文本 ReAct 协议回复，不要调用 OpenAI tool_calls。",
    '如果需要使用工具，严格输出两行：`Thought: ...` 和 `Action: {"tool_name":"...", "tool_args": {...}}`。',
    "拿到 Observation 后继续推理；如果已经可以回答，严格输出两行：`Thought: ...` 和 `Final Answer: ...`。",
    "Final Answer 必须是完整、可直接展示给用户的最终回答，不能只写开头句、引导句或未完成的列举。",
    "不能只输出“我可以为你提供这些能力：”“主要有这些能力：”“包括以下几类：”这类未完成答案。",
    "只有在你确认任务已经完成时，才能输出 `Final Answer: ...`；否则必须继续输出 `Action: ...`。",
    "如果当前内容只是过程说明、过渡句、准备继续检索或准备继续分析，不要输出 `Final Answer`。",
    "如果答案依赖工具结果或检索证据，只有在证据已经获得后，才能输出 `Final Answer`。",
    "如果用户的问题包含多个主要要求，只有在这些要求都已覆盖时，才能输出 `Final Answer`。",
]


class PromptBuilder:
    def __init__(self, *, system_rules: Iterable[str] | None = None, max_history: int = 4) -> None:
        """初始化 PromptBuilder，允许注入自定义 system 规则和历史窗口大小。"""
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
        """把 system 规则、记忆摘要、历史消息和当前 query 组装成模型输入消息。"""
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
        """把多条 system 规则拼接成一段模型可直接消费的系统提示。"""
        return "\n\n".join(self.system_rules)

    def _take_recent_history(
        self, history_messages: Iterable[ConversationMessageResponse | dict[str, Any]]
    ) -> list[ConversationMessageResponse]:
        """恢复并截断最近历史消息，避免把过长上下文直接喂给模型。"""
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
