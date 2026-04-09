from __future__ import annotations

import atexit
import asyncio
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_MAX_POOL_SIZE = 64
_IDLE_TTL_SECONDS = 15 * 60
_FUTURE_WAIT_BUFFER_SECONDS = 8.0
_VOLATILE_HEADERS = {"x-trace-id", "traceparent", "tracestate"}


@dataclass(slots=True)
class _SessionEntry:
    endpoint: str
    headers: dict[str, str]
    timeout_seconds: float
    http_client: Any
    transport_cm: Any
    session_cm: Any
    session: Any
    lock: asyncio.Lock
    last_used_monotonic: float


class McpSessionClient:
    """Sync MCP client wrapper backed by pooled mcp.ClientSession + streamable HTTP transport."""

    _bootstrap_lock = threading.Lock()
    _loop_ready = threading.Event()
    _loop: asyncio.AbstractEventLoop | None = None
    _loop_thread: threading.Thread | None = None
    _shutdown_registered = False
    _stats_lock = threading.Lock()
    _stats: dict[str, int] = {
        "calls_total": 0,
        "calls_failed": 0,
        "pool_hit": 0,
        "pool_miss": 0,
        "sessions_created": 0,
        "reconnects": 0,
        "evicted_idle": 0,
        "evicted_lru": 0,
        "discarded_error": 0,
    }

    # Loop-thread only state.
    _entries: dict[tuple[str, tuple[tuple[str, str], ...], int], _SessionEntry] = {}

    def call_tool(
        self,
        *,
        endpoint: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 20.0,
    ) -> dict[str, Any]:
        timeout = float(timeout_seconds)
        normalized_headers = _normalize_headers(headers)
        pool_headers = _pool_headers(normalized_headers)
        trace_id = normalized_headers.get("x-trace-id")
        key = _build_key(endpoint=endpoint, headers=pool_headers, timeout_seconds=timeout)
        self._inc("calls_total")
        started = time.monotonic()
        try:
            result = self._run_in_loop(
                self._call_tool_async(
                    key=key,
                    endpoint=endpoint,
                    headers=pool_headers,
                    tool_name=tool_name,
                    arguments=dict(arguments or {}),
                    timeout_seconds=timeout,
                ),
                timeout_seconds=timeout + _FUTURE_WAIT_BUFFER_SECONDS,
            )
        except Exception:
            self._inc("calls_failed")
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.exception(
                "MCP session call failed endpoint=%s tool=%s trace_id=%s elapsed_ms=%s",
                endpoint,
                tool_name,
                trace_id,
                elapsed_ms,
            )
            raise
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "MCP session call completed endpoint=%s tool=%s trace_id=%s elapsed_ms=%s",
            endpoint,
            tool_name,
            trace_id,
            elapsed_ms,
        )
        return result

    @classmethod
    def get_metrics(cls) -> dict[str, Any]:
        with cls._stats_lock:
            stats = dict(cls._stats)
        lookups = stats["pool_hit"] + stats["pool_miss"]
        hit_rate = float(stats["pool_hit"] / lookups) if lookups else 0.0
        return {
            "calls_total": stats["calls_total"],
            "calls_failed": stats["calls_failed"],
            "pool_hit": stats["pool_hit"],
            "pool_miss": stats["pool_miss"],
            "pool_hit_rate": hit_rate,
            "sessions_created": stats["sessions_created"],
            "reconnects": stats["reconnects"],
            "evicted_idle": stats["evicted_idle"],
            "evicted_lru": stats["evicted_lru"],
            "discarded_error": stats["discarded_error"],
            "pool_size": len(cls._entries),
            "pool_max_size": _MAX_POOL_SIZE,
            "pool_idle_ttl_seconds": _IDLE_TTL_SECONDS,
        }

    @classmethod
    def close_pool(cls) -> None:
        loop = cls._loop
        thread = cls._loop_thread
        if loop is None or thread is None:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(cls._close_all_entries_async(), loop)
            future.result(timeout=10)
        except Exception:
            logger.exception("Failed to close MCP session pool cleanly")
        finally:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
            thread.join(timeout=3)
            cls._loop = None
            cls._loop_thread = None
            cls._loop_ready.clear()

    def _run_in_loop(self, coro: Any, *, timeout_seconds: float) -> Any:
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout_seconds)

    @classmethod
    def _ensure_loop(cls) -> asyncio.AbstractEventLoop:
        loop = cls._loop
        if loop is not None and loop.is_running():
            return loop
        with cls._bootstrap_lock:
            loop = cls._loop
            if loop is not None and loop.is_running():
                return loop
            cls._loop_ready.clear()
            cls._loop_thread = threading.Thread(target=cls._loop_thread_main, daemon=True, name="mcp-session-loop")
            cls._loop_thread.start()
            cls._loop_ready.wait(timeout=5)
            loop = cls._loop
            if loop is None:
                raise RuntimeError("failed to bootstrap MCP session event loop")
            if not cls._shutdown_registered:
                atexit.register(cls.close_pool)
                cls._shutdown_registered = True
            return loop

    @classmethod
    def _loop_thread_main(cls) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cls._loop = loop
        cls._entries = {}
        cls._loop_ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                try:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
            loop.close()

    async def _call_tool_async(
        self,
        *,
        key: tuple[str, tuple[tuple[str, str], ...], int],
        endpoint: str,
        headers: dict[str, str],
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        await self._evict_idle_entries_async()
        for attempt in (1, 2):
            entry = await self._get_or_create_entry_async(
                key=key,
                endpoint=endpoint,
                headers=headers,
                timeout_seconds=timeout_seconds,
            )
            async with entry.lock:
                entry.last_used_monotonic = time.monotonic()
                try:
                    result = await entry.session.call_tool(
                        name=tool_name,
                        arguments=arguments,
                        read_timeout_seconds=timedelta(seconds=timeout_seconds),
                    )
                    return result.model_dump(mode="json")
                except Exception as exc:
                    logger.warning(
                        "MCP session tool call error endpoint=%s tool=%s attempt=%s error=%s",
                        endpoint,
                        tool_name,
                        attempt,
                        exc,
                    )
                    self._inc("discarded_error")
                    await self._discard_entry_async(key)
                    if attempt == 1:
                        self._inc("reconnects")
                    if attempt == 2:
                        raise
        raise RuntimeError("unreachable")

    async def _get_or_create_entry_async(
        self,
        *,
        key: tuple[str, tuple[tuple[str, str], ...], int],
        endpoint: str,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> _SessionEntry:
        existing = self._entries.get(key)
        if existing is not None:
            self._inc("pool_hit")
            existing.last_used_monotonic = time.monotonic()
            return existing
        self._inc("pool_miss")
        entry = await self._create_entry_async(
            endpoint=endpoint,
            headers=headers,
            timeout_seconds=timeout_seconds,
        )
        self._entries[key] = entry
        await self._evict_lru_if_needed_async()
        return entry

    async def _create_entry_async(
        self,
        *,
        endpoint: str,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> _SessionEntry:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "mcp sdk is not installed. Install dependency 'mcp' before enabling ClientSession transport."
            ) from exc

        timeout = float(timeout_seconds)
        http_timeout = httpx.Timeout(timeout, read=timeout)
        http_client = httpx.AsyncClient(timeout=http_timeout, headers=headers, trust_env=False)
        transport_cm = None
        session_cm = None
        try:
            transport_cm = streamable_http_client(
                endpoint,
                http_client=http_client,
                terminate_on_close=False,
            )
            read_stream, write_stream, _get_session_id = await transport_cm.__aenter__()
            _ = _get_session_id
            session_cm = ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=timeout),
            )
            session = await session_cm.__aenter__()
            await session.initialize()
            self._inc("sessions_created")
            return _SessionEntry(
                endpoint=endpoint,
                headers=dict(headers),
                timeout_seconds=timeout,
                http_client=http_client,
                transport_cm=transport_cm,
                session_cm=session_cm,
                session=session,
                lock=asyncio.Lock(),
                last_used_monotonic=time.monotonic(),
            )
        except Exception:
            if session_cm is not None:
                try:
                    await session_cm.__aexit__(None, None, None)
                except Exception:
                    pass
            if transport_cm is not None:
                try:
                    await transport_cm.__aexit__(None, None, None)
                except Exception:
                    pass
            await http_client.aclose()
            raise

    async def _discard_entry_async(self, key: tuple[str, tuple[tuple[str, str], ...], int]) -> None:
        entry = self._entries.pop(key, None)
        if entry is None:
            return
        await self._close_entry_async(entry)

    @classmethod
    async def _close_all_entries_async(cls) -> None:
        entries = list(cls._entries.values())
        cls._entries.clear()
        for entry in entries:
            try:
                await cls._close_entry_async(entry)
            except Exception:
                logger.exception("Failed to close MCP session pool entry endpoint=%s", entry.endpoint)

    @staticmethod
    async def _close_entry_async(entry: _SessionEntry) -> None:
        try:
            await entry.session_cm.__aexit__(None, None, None)
        except Exception:
            logger.debug("Error closing MCP session context endpoint=%s", entry.endpoint, exc_info=True)
        try:
            await entry.transport_cm.__aexit__(None, None, None)
        except Exception:
            logger.debug("Error closing MCP transport context endpoint=%s", entry.endpoint, exc_info=True)
        try:
            await entry.http_client.aclose()
        except Exception:
            logger.debug("Error closing MCP httpx client endpoint=%s", entry.endpoint, exc_info=True)

    async def _evict_lru_if_needed_async(self) -> None:
        while len(self._entries) > _MAX_POOL_SIZE:
            oldest_key = min(
                self._entries,
                key=lambda item_key: self._entries[item_key].last_used_monotonic,
            )
            self._inc("evicted_lru")
            await self._discard_entry_async(oldest_key)

    async def _evict_idle_entries_async(self) -> None:
        if not self._entries:
            return
        now = time.monotonic()
        stale_keys = [
            key
            for key, entry in self._entries.items()
            if now - entry.last_used_monotonic > _IDLE_TTL_SECONDS
        ]
        for key in stale_keys:
            self._inc("evicted_idle")
            await self._discard_entry_async(key)

    @classmethod
    def _inc(cls, key: str, delta: int = 1) -> None:
        with cls._stats_lock:
            cls._stats[key] = cls._stats.get(key, 0) + delta


def _normalize_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    normalized: dict[str, str] = {}
    for key, value in headers.items():
        if not key:
            continue
        normalized[str(key)] = str(value)
    return normalized


def _pool_headers(headers: Mapping[str, str]) -> dict[str, str]:
    stable: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in _VOLATILE_HEADERS:
            continue
        stable[key] = value
    return stable


def _build_key(
    *,
    endpoint: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> tuple[str, tuple[tuple[str, str], ...], int]:
    timeout_ms = int(float(timeout_seconds) * 1000)
    headers_tuple = tuple(sorted((str(k), str(v)) for k, v in headers.items()))
    return endpoint, headers_tuple, timeout_ms
