from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.core.config import Settings


class LlmGatewayService:
    def __init__(self, settings: Settings, *, openai_client: OpenAI | None = None) -> None:
        self.settings = settings
        self._openai_client = openai_client

    def chat_completion(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> dict[str, Any]:
        if self._is_configured():
            self._validate_llm_base_url()
            request_kwargs: dict[str, Any] = {
                "model": model or self.settings.assistant_llm_model,
                "messages": messages,
            }
            if temperature is not None:
                request_kwargs["temperature"] = temperature
            if tools:
                request_kwargs["tools"] = tools
            if tool_choice is not None:
                request_kwargs["tool_choice"] = tool_choice

            try:
                response = self._get_client().chat.completions.create(**request_kwargs)
            except (APITimeoutError, APIConnectionError) as exc:
                raise RuntimeError(
                    "Upstream LLM request failed: connection/timeout error. "
                    f"base_url={self.settings.assistant_llm_base_url}, model={request_kwargs.get('model')}"
                ) from exc
            except APIStatusError as exc:
                body = _safe_response_body(exc)
                raise RuntimeError(
                    "Upstream LLM returned HTTP error. "
                    f"status={getattr(exc, 'status_code', 'unknown')}, "
                    f"base_url={self.settings.assistant_llm_base_url}, "
                    f"model={request_kwargs.get('model')}, body={body}"
                ) from exc
            choice = response.choices[0] if response.choices else None
            message_payload = {}
            finish_reason = None
            if choice is not None:
                finish_reason = getattr(choice, "finish_reason", None)
                message_payload = _serialize_message(getattr(choice, "message", None))
            return {
                "model": response.model,
                "message": message_payload,
                "choices": [
                    {
                        "message": message_payload,
                        "finish_reason": finish_reason,
                    }
                ],
                "finish_reason": finish_reason,
            }

        fallback_message = {
            "role": "assistant",
            "content": "LLM gateway is not configured.",
        }
        return {
            "model": model or "mock",
            "message": fallback_message,
            "choices": [
                {
                    "message": fallback_message,
                    "finish_reason": "stop",
                }
            ],
            "fallback": True,
        }

    def stream_completion(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> dict[str, Any]:
        return {
            "model": model or self.settings.assistant_llm_model or "mock",
            "chunks": list(
                self.iter_stream_completion(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    tools=tools,
                    tool_choice=tool_choice,
                )
            ),
            "fallback": not self._is_configured(),
        }

    def iter_stream_completion(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        if self._is_configured():
            self._validate_llm_base_url()
            request_kwargs: dict[str, Any] = {
                "model": model or self.settings.assistant_llm_model,
                "messages": messages,
                "stream": True,
            }
            if temperature is not None:
                request_kwargs["temperature"] = temperature
            if tools:
                request_kwargs["tools"] = tools
            if tool_choice is not None:
                request_kwargs["tool_choice"] = tool_choice
            try:
                stream = self._get_client().chat.completions.create(**request_kwargs)
            except (APITimeoutError, APIConnectionError) as exc:
                raise RuntimeError(
                    "Upstream LLM stream request failed: connection/timeout error. "
                    f"base_url={self.settings.assistant_llm_base_url}, model={request_kwargs.get('model')}"
                ) from exc
            except APIStatusError as exc:
                body = _safe_response_body(exc)
                raise RuntimeError(
                    "Upstream LLM stream returned HTTP error. "
                    f"status={getattr(exc, 'status_code', 'unknown')}, "
                    f"base_url={self.settings.assistant_llm_base_url}, "
                    f"model={request_kwargs.get('model')}, body={body}"
                ) from exc
            for event in stream:
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    yield {"type": "delta", "content": text, "delta": {"content": text}}
                tool_calls = _serialize_tool_calls(getattr(delta, "tool_calls", None))
                if tool_calls:
                    yield {"type": "tool_calls", "delta": {"tool_calls": tool_calls}}
            return

        yield {"type": "delta", "content": "LLM gateway", "delta": {"content": "LLM gateway"}}
        yield {"type": "delta", "content": " is not configured.", "delta": {"content": " is not configured."}}

    def _is_configured(self) -> bool:
        return bool(
            self.settings.assistant_llm_base_url
            and self.settings.assistant_llm_api_key
            and self.settings.assistant_llm_model
        )

    def _get_client(self) -> OpenAI:
        if self._openai_client is None:
            self._openai_client = OpenAI(
                base_url=self.settings.assistant_llm_base_url,
                api_key=self.settings.assistant_llm_api_key,
            )
        return self._openai_client

    def _validate_llm_base_url(self) -> None:
        base_url = (self.settings.assistant_llm_base_url or "").strip()
        if "/api/coding" in base_url:
            raise RuntimeError(
                "ASSISTANT_LLM_BASE_URL appears to use '/api/coding', which is not OpenAI chat-completions compatible. "
                "Please configure an OpenAI-compatible endpoint (for example a provider '/v1' or Ark '/api/v3' endpoint)."
            )


def _serialize_message(message: Any) -> dict[str, Any]:
    if message is None:
        return {"role": "assistant", "content": ""}
    if isinstance(message, Mapping):
        role = message.get("role")
        content = message.get("content")
        tool_calls = message.get("tool_calls")
        reasoning_content = message.get("reasoning_content")
        model_extra = message.get("model_extra")
        return {
            "role": role if isinstance(role, str) else "assistant",
            "content": content,
            "tool_calls": _serialize_tool_calls(tool_calls),
            "reasoning_content": reasoning_content if isinstance(reasoning_content, str) else None,
            "model_extra": _serialize_model_extra(model_extra),
        }

    role = getattr(message, "role", None)
    content = getattr(message, "content", None)
    tool_calls = getattr(message, "tool_calls", None)
    reasoning_content = getattr(message, "reasoning_content", None)
    model_extra = getattr(message, "model_extra", None)
    return {
        "role": role if isinstance(role, str) else "assistant",
        "content": content,
        "tool_calls": _serialize_tool_calls(tool_calls),
        "reasoning_content": reasoning_content if isinstance(reasoning_content, str) else None,
        "model_extra": _serialize_model_extra(model_extra),
    }


def _serialize_tool_calls(raw_calls: Any) -> list[dict[str, Any]]:
    if not raw_calls:
        return []
    serialized: list[dict[str, Any]] = []
    for item in list(raw_calls):
        if isinstance(item, Mapping):
            call_id = item.get("id")
            call_type = item.get("type")
            function_payload = item.get("function")
            if isinstance(function_payload, Mapping):
                fn_name = function_payload.get("name")
                fn_args = function_payload.get("arguments")
            else:
                fn_name = getattr(function_payload, "name", None)
                fn_args = getattr(function_payload, "arguments", None)
        else:
            call_id = getattr(item, "id", None)
            call_type = getattr(item, "type", None)
            function_payload = getattr(item, "function", None)
            fn_name = getattr(function_payload, "name", None) if function_payload is not None else None
            fn_args = getattr(function_payload, "arguments", None) if function_payload is not None else None

        serialized.append(
            {
                "id": str(call_id or ""),
                "type": str(call_type or "function"),
                "function": {
                    "name": str(fn_name or ""),
                    "arguments": str(fn_args or ""),
                },
            }
        )
    return serialized


def _serialize_model_extra(model_extra: Any) -> dict[str, Any] | None:
    if isinstance(model_extra, Mapping):
        return dict(model_extra)
    return None


def _safe_response_body(exc: APIStatusError) -> str:
    response = getattr(exc, "response", None)
    if response is None:
        return "n/a"
    try:
        body = response.text
    except Exception:
        return "n/a"
    if not isinstance(body, str):
        return "n/a"
    text = body.strip().replace("\n", " ")
    if not text:
        return "n/a"
    if len(text) > 400:
        return text[:397] + "..."
    return text
