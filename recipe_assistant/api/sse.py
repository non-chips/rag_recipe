"""SSE wire encoder kept independent from HTTP routing."""

from __future__ import annotations

from recipe_assistant.schemas.api.sse import ChatSseEvent


def encode_sse(event: ChatSseEvent) -> str:
    data = event.model_dump_json(by_alias=True)
    return f"event: {event.type}\ndata: {data}\n\n"
