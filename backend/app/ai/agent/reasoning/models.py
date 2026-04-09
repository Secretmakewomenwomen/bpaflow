from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DecisionType(str, Enum):
    """定义 reasoning 层可能产出的几类决策结果。"""

    final_answer = "final_answer"
    tool_call = "tool_call"
    tool_arguments_error = "tool_arguments_error"
    decision_error = "decision_error"


@dataclass(frozen=True)
class ToolCall:
    """表示一次标准化后的工具调用请求。"""

    tool_name: str
    tool_args: dict[str, Any]
    call_id: str | None = None


@dataclass
class AgentDecision:
    """表示模型经过解析后的统一决策结果，供 runtime 继续执行。"""

    decision_type: DecisionType
    thought: str | None = None
    final_answer: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    error_message: str | None = None
