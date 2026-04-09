from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .models import ToolCall

_REACT_ACTION_RE = re.compile(r"(?mi)^\s*Action:\s*(?P<action>\{.*\})\s*$")
_REACT_FINAL_RE = re.compile(r"(?mi)^\s*Final Answer:\s*(?P<final>.+?)\s*$")
_REACT_THOUGHT_RE = re.compile(r"(?mi)^\s*Thought:\s*(?P<thought>.+?)\s*$")


def extract_tool_calls(message: Any) -> tuple[list[ToolCall], str | None]:
    """从模型返回的 tool_calls 字段中解析出标准 ToolCall 列表。"""
    raw_calls = _read_attribute(message, "tool_calls") or []
    parsed_calls: list[ToolCall] = []

    for call_payload in raw_calls:
        function_payload = _read_attribute(call_payload, "function")
        tool_name = _read_attribute(function_payload, "name")
        if not tool_name:
            continue
        raw_arguments = _read_attribute(function_payload, "arguments") or ""
        normalized_arguments = _normalize_raw_arguments(raw_arguments)
        tool_args, error_message = parse_tool_arguments(normalized_arguments)
        if error_message:
            return [], error_message
        call_id = _read_attribute(call_payload, "id") or _read_attribute(call_payload, "tool_call_id")
        parsed_calls.append(
            ToolCall(
                tool_name=tool_name,
                tool_args=tool_args,
                call_id=call_id,
            )
        )

    return parsed_calls, None


def parse_tool_arguments(raw_arguments: str) -> tuple[dict[str, Any], str | None]:
    """把工具参数文本解析成 JSON 对象，并返回参数错误信息。"""
    arguments_text = raw_arguments.strip()
    if not arguments_text:
        return {}, None
    try:
        parsed = json.loads(arguments_text)
    except json.JSONDecodeError:
        return {}, "Tool arguments must be valid JSON object."
    if not isinstance(parsed, dict):
        return {}, "Tool arguments must be a JSON object."
    return parsed, None


def extract_completion_text(content: Any) -> str:
    """从任意 completion content 结构中提取纯文本内容。"""
    return _extract_text_parts(content).strip()


def extract_legacy_react_action(content_text: str) -> ToolCall | None:
    """解析文本版 ReAct 中的 Action 行，兼容旧格式工具调用。"""
    if not content_text:
        return None
    match = _REACT_ACTION_RE.search(content_text)
    if not match:
        return None
    raw = match.group("action").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    tool_name = str(parsed.get("tool_name") or "").strip()
    tool_args = parsed.get("tool_args")
    if not tool_name or not isinstance(tool_args, dict):
        return None
    return ToolCall(tool_name=tool_name, tool_args=tool_args, call_id=None)


def extract_legacy_react_thought(content_text: str) -> str | None:
    """解析文本版 ReAct 中的 Thought 行。"""
    if not content_text:
        return None
    match = _REACT_THOUGHT_RE.search(content_text)
    if not match:
        return None
    thought = match.group("thought").strip()
    return thought or None


def extract_legacy_react_final_answer(content_text: str) -> str | None:
    """解析文本版 ReAct 中的 Final Answer 行。"""
    if not content_text:
        return None
    match = _REACT_FINAL_RE.search(content_text)
    if not match:
        return None
    final = match.group("final").strip()
    return final or None


def _normalize_raw_arguments(raw_arguments: Any) -> str:
    """把任意形态的工具参数统一规整成可 JSON 解析的字符串。"""
    if isinstance(raw_arguments, str):
        return raw_arguments
    if isinstance(raw_arguments, Mapping):
        return json.dumps(raw_arguments, ensure_ascii=False, default=str)
    if raw_arguments is None:
        return ""
    return str(raw_arguments)


def _read_attribute(payload: Any, key: str) -> Any:
    """统一读取 dict/object 上的同名字段，减少解析分支判断。"""
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        return payload.get(key)
    return getattr(payload, key, None)


def _extract_text_parts(content: Any) -> str:
    """递归展开 content 中的嵌套文本片段，拼成一段可读文本。"""
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
