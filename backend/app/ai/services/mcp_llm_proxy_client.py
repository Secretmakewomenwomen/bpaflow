from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx

from app.mcp.client import McpSessionClient


class McpLlmProxyClient:
    """OpenAI-like chat.completions client backed by MCP llm-gateway tools."""

    def __init__(
        self,
        *,
        endpoint: str,
        user_id: str | None = None,
        tenant_id: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        timeout_seconds: float = 20.0,
        http_client: Any | None = None,
        mcp_session_client: McpSessionClient | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.trace_id = trace_id
        self.timeout_seconds = timeout_seconds
        # Legacy injected client (tests) can still use .post JSON-RPC behavior.
        self._http_client = http_client
        self._mcp_session_client = mcp_session_client or McpSessionClient()
        self.chat = SimpleNamespace(completions=_McpLlmCompletionsProxy(self))


class _McpLlmCompletionsProxy:
    def __init__(self, outer: McpLlmProxyClient) -> None:
        self._outer = outer

    def create(self, **kwargs: Any) -> Any:
        stream = bool(kwargs.get("stream"))
        tool_name = "stream_completion" if stream else "chat_completion"

        arguments: dict[str, Any] = {
            "messages": kwargs.get("messages") or [],
            "model": kwargs.get("model"),
        }
        if "temperature" in kwargs:
            arguments["temperature"] = kwargs["temperature"]
        if "tools" in kwargs:
            arguments["tools"] = kwargs["tools"]
        if "tool_choice" in kwargs:
            arguments["tool_choice"] = kwargs["tool_choice"]

        if stream:
            return self._stream_tool_call(arguments=arguments)
        body = self._post_tool_call(tool_name=tool_name, arguments=arguments)
        data = self._extract_tool_data(body)
        return self._build_completion(data)

    def _stream_tool_call(self, *, arguments: dict[str, Any]) -> Iterator[Any]:
        if self._outer._http_client is not None and not hasattr(self._outer._http_client, "stream"):
            body = self._post_tool_call(tool_name="stream_completion", arguments=arguments)
            data = self._extract_tool_data(body)
            yield from self._build_stream_chunks(data)
            return

        headers = self._build_headers()
        headers["accept"] = "text/event-stream"
        payload = self._build_payload(tool_name="stream_completion", arguments=arguments)
        stream_context, should_close_client = self._open_stream_request(payload=payload, headers=headers)
        try:
            with stream_context as response:
                status_code = getattr(response, "status_code", 200)
                if status_code >= 400:
                    raise RuntimeError(f"mcp llm gateway returned HTTP {status_code}")
                yield from self._iter_sse_chunks(response)
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "mcp llm gateway timed out. "
                f"endpoint={self._outer.endpoint}, timeout={self._outer.timeout_seconds}s. "
                "Increase ASSISTANT_MCP_LLM_TIMEOUT_SECONDS or inspect llm-gateway latency."
            ) from exc
        finally:
            if should_close_client:
                self._close_stream_client()

    def _post_tool_call(self, *, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        headers = self._build_headers()
        payload = self._build_payload(tool_name=tool_name, arguments=arguments)
        if self._outer._http_client is not None and hasattr(self._outer._http_client, "post"):
            try:
                response = self._outer._http_client.post(
                    self._outer.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self._outer.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    "mcp llm gateway timed out. "
                    f"endpoint={self._outer.endpoint}, timeout={self._outer.timeout_seconds}s. "
                    "Increase ASSISTANT_MCP_LLM_TIMEOUT_SECONDS or inspect llm-gateway latency."
                ) from exc
            status_code = getattr(response, "status_code", 200)
            if status_code >= 400:
                raise RuntimeError(f"mcp llm gateway returned HTTP {status_code}")
            body = response.json()
            if not isinstance(body, dict):
                raise RuntimeError("mcp llm gateway returned invalid payload")
            return body

        body = self._outer._mcp_session_client.call_tool(
            endpoint=self._outer.endpoint,
            tool_name=tool_name,
            arguments=arguments,
            headers=headers,
            timeout_seconds=self._outer.timeout_seconds,
        )
        if not isinstance(body, dict):
            raise RuntimeError("mcp llm gateway returned invalid payload")
        return body

    def _open_stream_request(self, *, payload: dict[str, Any], headers: dict[str, str]) -> tuple[Any, bool]:
        if self._outer._http_client is not None and hasattr(self._outer._http_client, "stream"):
            return (
                self._outer._http_client.stream(
                    "POST",
                    self._outer.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self._outer.timeout_seconds,
                ),
                False,
            )
        self._stream_http_client = httpx.Client(timeout=self._outer.timeout_seconds, trust_env=False)
        return (
            self._stream_http_client.stream(
                "POST",
                self._outer.endpoint,
                json=payload,
                headers=headers,
                timeout=self._outer.timeout_seconds,
            ),
            True,
        )

    def _close_stream_client(self) -> None:
        stream_http_client = getattr(self, "_stream_http_client", None)
        if stream_http_client is None:
            return
        try:
            stream_http_client.close()
        finally:
            self._stream_http_client = None

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._outer.user_id:
            headers["x-user-id"] = self._outer.user_id
        if self._outer.tenant_id:
            headers["x-tenant-id"] = self._outer.tenant_id
        if self._outer.session_id:
            headers["x-session-id"] = self._outer.session_id
        if self._outer.trace_id:
            headers["x-trace-id"] = self._outer.trace_id
        return headers

    @staticmethod
    def _build_payload(*, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": f"llm-{uuid.uuid4().hex}",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

    def _iter_sse_chunks(self, response: Any) -> Iterator[Any]:
        buffer = ""
        for chunk in response.iter_text():
            if not chunk:
                continue
            buffer += chunk
            while "\n\n" in buffer:
                raw_event, buffer = buffer.split("\n\n", 1)
                parsed = self._parse_sse_event(raw_event)
                if parsed is None:
                    continue
                event_name, data = parsed
                if event_name == "delta":
                    yield self._build_stream_chunk(data)
                elif event_name == "error":
                    raise RuntimeError(str(data.get("message") or "mcp llm gateway stream failed"))
                elif event_name == "done":
                    return

    @staticmethod
    def _parse_sse_event(raw_event: str) -> tuple[str, dict[str, Any]] | None:
        event_name = "message"
        data_parts: list[str] = []
        for line in raw_event.splitlines():
            if line.startswith("event:"):
                event_name = line.partition(":")[2].strip()
            elif line.startswith("data:"):
                data_parts.append(line.partition(":")[2].strip())
        if not data_parts:
            return None
        try:
            data = json.loads("\n".join(data_parts))
        except json.JSONDecodeError as exc:
            raise RuntimeError("mcp llm gateway returned malformed SSE payload") from exc
        if not isinstance(data, dict):
            raise RuntimeError("mcp llm gateway returned malformed SSE payload")
        return event_name, data

    @staticmethod
    def _build_stream_chunk(data: dict[str, Any]) -> Any:
        delta_payload = data.get("delta")
        content = None
        tool_calls = None
        if isinstance(delta_payload, dict):
            content = delta_payload.get("content")
            tool_calls = delta_payload.get("tool_calls")
        if content is None:
            content = data.get("content")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=content, tool_calls=_build_stream_tool_calls(tool_calls)),
                    finish_reason=data.get("finish_reason"),
                )
            ]
        )

    @staticmethod
    def _extract_tool_data(body: dict[str, Any]) -> dict[str, Any]:
        rpc_error = body.get("error")
        if isinstance(rpc_error, dict):
            raise RuntimeError(str(rpc_error.get("message") or "mcp json-rpc error"))

        result = body.get("result")
        source = result if isinstance(result, dict) else body
        payload: dict[str, Any] | None = None

        structured = source.get("structuredContent")
        if isinstance(structured, dict) and "ok" in structured:
            payload = structured

        if payload is None:
            content = source.get("content")
            if isinstance(content, list) and content:
                first_item = content[0]
                if isinstance(first_item, dict):
                    raw_payload = first_item.get("json")
                    if isinstance(raw_payload, dict):
                        payload = raw_payload
                    elif bool(source.get("isError")):
                        text = first_item.get("text")
                        payload = {
                            "ok": False,
                            "error": {
                                "code": "SERVICE_ERROR",
                                "message": str(text or "mcp tool failed"),
                                "retryable": False,
                            },
                        }

        if payload is None:
            raise RuntimeError("mcp llm gateway result payload missing json/structuredContent")
        if not payload.get("ok"):
            error = payload.get("error") or {}
            raise RuntimeError(str(error.get("message") or "mcp tool failed"))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("mcp llm gateway result data invalid")
        return data

    @staticmethod
    def _build_completion(data: dict[str, Any]) -> Any:
        choices_data = data.get("choices")
        choices: list[Any] = []
        if isinstance(choices_data, list) and choices_data:
            for item in choices_data:
                if not isinstance(item, dict):
                    continue
                message_payload = item.get("message")
                message = _build_message(message_payload)
                finish_reason = item.get("finish_reason")
                choices.append(SimpleNamespace(message=message, finish_reason=finish_reason))

        if not choices:
            message = _build_message(data.get("message"))
            choices = [SimpleNamespace(message=message, finish_reason=data.get("finish_reason"))]

        return SimpleNamespace(model=data.get("model"), choices=choices)

    @staticmethod
    def _build_stream_chunks(data: dict[str, Any]):
        chunks = data.get("chunks")
        if not isinstance(chunks, list):
            return iter([])

        output: list[Any] = []
        for item in chunks:
            if not isinstance(item, dict):
                continue
            delta_payload = item.get("delta")
            content = None
            if isinstance(delta_payload, dict):
                content = delta_payload.get("content")
            if content is None:
                content = item.get("content")
            finish_reason = item.get("finish_reason")
            output.append(
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=content),
                            finish_reason=finish_reason,
                        )
                    ]
                )
            )
        return iter(output)


def _build_message(payload: Any) -> Any:
    if not isinstance(payload, dict):
        payload = {}
    role = payload.get("role")
    content = payload.get("content")
    reasoning_content = payload.get("reasoning_content")
    model_extra = payload.get("model_extra")
    tool_calls_raw = payload.get("tool_calls")
    tool_calls: list[Any] = []
    if isinstance(tool_calls_raw, list):
        for item in tool_calls_raw:
            if not isinstance(item, dict):
                continue
            fn = item.get("function")
            fn_name = None
            fn_args = ""
            if isinstance(fn, dict):
                fn_name = fn.get("name")
                fn_args = str(fn.get("arguments") or "")
            tool_calls.append(
                SimpleNamespace(
                    id=item.get("id"),
                    type=item.get("type", "function"),
                    function=SimpleNamespace(name=fn_name, arguments=fn_args),
                )
            )
    return SimpleNamespace(
        role=role or "assistant",
        content=content,
        tool_calls=tool_calls,
        reasoning_content=reasoning_content if isinstance(reasoning_content, str) else None,
        model_extra=model_extra if isinstance(model_extra, dict) else None,
    )


def _build_stream_tool_calls(payload: Any) -> list[Any]:
    if not isinstance(payload, list):
        return []
    tool_calls: list[Any] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        function_payload = item.get("function")
        if not isinstance(function_payload, dict):
            function_payload = {}
        tool_calls.append(
            SimpleNamespace(
                index=item.get("index"),
                id=item.get("id"),
                type=item.get("type", "function"),
                function=SimpleNamespace(
                    name=function_payload.get("name"),
                    arguments=function_payload.get("arguments"),
                ),
            )
        )
    return tool_calls
