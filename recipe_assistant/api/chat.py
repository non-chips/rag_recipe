"""Versioned SSE chat endpoint."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from recipe_assistant.agents.result import ChatRequest
from recipe_assistant.api.dependencies import ApiContainer, get_container, get_user_id
from recipe_assistant.api.sse import encode_sse, token_chunks
from recipe_assistant.schemas.api import (
    ChatStreamRequest,
    DoneEvent,
    ErrorEvent,
    MetaEvent,
    SourceEvent,
    StatusEvent,
    TokenEvent,
)


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post(
    "/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Versioned chat event stream",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
def stream_chat(
    payload: ChatStreamRequest,
    user_id: int = Depends(get_user_id),
    container: ApiContainer = Depends(get_container),
) -> StreamingResponse:
    def events() -> Iterator[str]:
        try:
            result = container.chat_runner.run(
                ChatRequest(
                    user_id=user_id,
                    message=payload.message,
                    session_public_id=payload.session_id,
                )
            )
            yield encode_sse(
                MetaEvent(
                    session_id=result.session_public_id,
                    run_id=result.run_id,
                    route=result.route.value,
                )
            )
            yield encode_sse(StatusEvent(stage="completed", message="回答已生成"))
            for source in result.outcome.result.sources:
                yield encode_sse(SourceEvent(source=source))
            for chunk in token_chunks(result.content):
                yield encode_sse(TokenEvent(content=chunk))
            yield encode_sse(
                DoneEvent(
                    message_id=result.assistant_message_id,
                    content=result.content,
                )
            )
        except LookupError as exc:
            yield encode_sse(
                ErrorEvent(code="RESOURCE_NOT_FOUND", message=str(exc), retryable=False)
            )
        except PermissionError as exc:
            yield encode_sse(
                ErrorEvent(code="ACCESS_DENIED", message=str(exc), retryable=False)
            )
        except Exception:
            yield encode_sse(
                ErrorEvent(
                    code="CHAT_EXECUTION_FAILED",
                    message="本次请求暂时无法完成，请稍后重试。",
                    retryable=True,
                )
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
