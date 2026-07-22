"""Versioned Server-Sent Event contracts for chat streaming."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(item.capitalize() for item in rest)


class SseEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        alias_generator=_to_camel,
        populate_by_name=True,
    )

    version: Literal["1.0"] = "1.0"
    type: str


class MetaEvent(SseEvent):
    type: Literal["meta"] = "meta"
    session_id: str
    run_id: str
    route: str


class StatusEvent(SseEvent):
    type: Literal["status"] = "status"
    stage: str
    message: str


class TokenEvent(SseEvent):
    type: Literal["token"] = "token"
    content: str


class SourceEvent(SseEvent):
    type: Literal["source"] = "source"
    source: dict


class DoneEvent(SseEvent):
    type: Literal["done"] = "done"
    message_id: int
    content: str


class ErrorEvent(SseEvent):
    type: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool = False


class ChatStreamRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        alias_generator=_to_camel,
        populate_by_name=True,
    )

    message: str = Field(min_length=1)
    session_id: str | None = None


ChatSseEvent = MetaEvent | StatusEvent | TokenEvent | SourceEvent | DoneEvent | ErrorEvent

