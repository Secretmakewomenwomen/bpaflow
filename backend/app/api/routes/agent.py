from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.ai.event_stream import AgentEventStream
from app.dependencies.auth import get_current_user
from app.schemas.agent import AgentResumeRequest, AgentRunResponse, AgentStartRequest
from app.schemas.auth import CurrentUserResponse

router = APIRouter(prefix="/agent", tags=["agent"])


def get_agent_service() -> Any:
    raise HTTPException(status_code=501, detail="Agent service is not configured.")


def get_agent_event_stream(request: Request) -> AgentEventStream:
    stream = getattr(request.app.state, "agent_event_stream", None)
    if stream is None:
        stream = AgentEventStream()
        request.app.state.agent_event_stream = stream
    return stream


@router.post("/threads", response_model=AgentRunResponse)
def create_agent_thread(
    payload: AgentStartRequest,
    service: Annotated[Any, Depends(get_agent_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> AgentRunResponse:
    return service.start_thread(current_user.user_id, payload)


@router.post("/threads/{thread_id}/resume", response_model=AgentRunResponse)
def resume_agent_thread(
    thread_id: str,
    payload: AgentResumeRequest,
    service: Annotated[Any, Depends(get_agent_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> AgentRunResponse:
    return service.resume_thread(thread_id, current_user.user_id, payload)


@router.get("/threads/{thread_id}", response_model=AgentRunResponse)
def get_agent_thread(
    thread_id: str,
    service: Annotated[Any, Depends(get_agent_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> AgentRunResponse:
    return service.get_thread(thread_id, current_user.user_id)


@router.get("/threads/{thread_id}/events")
def stream_agent_thread_events(
    thread_id: str,
    stream: Annotated[AgentEventStream, Depends(get_agent_event_stream)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> StreamingResponse:
    del current_user

    def generate() -> Iterator[str]:
        subscriber = stream.subscribe(thread_id)
        while not subscriber.empty():
            yield subscriber.get_nowait().to_sse()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
