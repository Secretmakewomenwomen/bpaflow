import json
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.ai.services.ai_conversation_service import AiConversationService
from app.ai.services.langgraph_assistant import LangGraphAssistantService
from app.schemas.ai import (
    ConversationCreateResponse,
    ConversationMessageResponse,
    ResumeConversationMessageRequest,
    SendConversationMessageRequest,
)
from app.schemas.auth import CurrentUserResponse
from app.services.upload_service import UploadService
from app.services.work_service import WorkService

router = APIRouter(prefix="/ai", tags=["ai"])


def _format_sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def get_ai_conversation_service(db: Annotated[Session, Depends(get_db)]) -> AiConversationService:
    return AiConversationService(db=db)


def get_ai_assistant_service(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
) -> LangGraphAssistantService:
    return LangGraphAssistantService(
        settings=settings,
        conversation_service=AiConversationService(db=db),
        upload_service=UploadService(db=db, settings=settings),
        work_service=WorkService(db=db),
    )


@router.post("/conversations", response_model=ConversationCreateResponse)
def create_ai_conversation(
    service: Annotated[AiConversationService, Depends(get_ai_conversation_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> ConversationCreateResponse:
    return service.create_conversation(user_id=current_user.user_id)


@router.get("/conversations/latest", response_model=ConversationCreateResponse | None)
def get_latest_ai_conversation(
    service: Annotated[AiConversationService, Depends(get_ai_conversation_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> ConversationCreateResponse | None:
    return service.get_latest_conversation(user_id=current_user.user_id)


@router.get("/graph")
def get_ai_graph(
    service: Annotated[LangGraphAssistantService, Depends(get_ai_assistant_service)],
) -> dict[str, str]:
    return {
        "format": "mermaid",
        "mermaid": service.export_graph_mermaid(),
    }


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageResponse])
def get_ai_conversation_messages(
    conversation_id: str,
    service: Annotated[AiConversationService, Depends(get_ai_conversation_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> list[ConversationMessageResponse]:
    return service.get_messages(conversation_id=conversation_id, user_id=current_user.user_id)


@router.post("/conversations/{conversation_id}/messages/stream")
def stream_ai_conversation_message(
    conversation_id: str,
    payload: SendConversationMessageRequest,
    service: Annotated[LangGraphAssistantService, Depends(get_ai_assistant_service)],
    conversation_service: Annotated[AiConversationService, Depends(get_ai_conversation_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> StreamingResponse:
    user_message = conversation_service.create_user_message(
        conversation_id=conversation_id,
        user_id=current_user.user_id,
        content=payload.query.strip(),
    )

    def generate() -> Iterator[str]:
        yield _format_sse("user_message", {"message": user_message.model_dump(mode="json")})
        try:
            for event in service.stream_invoke(
                conversation_id=conversation_id,
                query=payload.query,
                user_id=current_user.user_id,
            ):
                yield _format_sse(event["event"], event["data"])
        except HTTPException as exc:
            message = exc.detail if isinstance(exc.detail, str) else "AI retrieval failed."
            yield _format_sse("error", {"message": message})
        except RuntimeError:
            yield _format_sse("error", {"message": "AI retrieval precondition failed."})
        except Exception:
            yield _format_sse("error", {"message": "AI retrieval failed."})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/conversations/{conversation_id}/messages/resume", response_model=ConversationMessageResponse)
def resume_ai_conversation_message(
    conversation_id: str,
    payload: ResumeConversationMessageRequest,
    service: Annotated[LangGraphAssistantService, Depends(get_ai_assistant_service)],
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
) -> ConversationMessageResponse:
    try:
        return service.resume_flow_chart_generation(
            conversation_id=conversation_id,
            user_id=current_user.user_id,
            action_id=payload.actionId,
            upload_id=payload.payload.uploadId,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

@router.post("/conversations/{conversation_id}/clear", status_code=status.HTTP_204_NO_CONTENT)
def deleteMessageByconversiationId(
    conversation_id: str,
    current_user: Annotated[CurrentUserResponse, Depends(get_current_user)],
    service: Annotated[AiConversationService, Depends(get_ai_conversation_service)],
) -> Response:
    service.deleteMessage(conversation_id=conversation_id, user_id=current_user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
