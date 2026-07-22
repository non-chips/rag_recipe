"""SSE wire encoder kept independent from HTTP routing."""

from __future__ import annotations

from recipe_assistant.schemas.api.sse import ChatSseEvent


def encode_sse(event: ChatSseEvent) -> str:
    data = event.model_dump_json(by_alias=True)
    return f"event: {event.type}\ndata: {data}\n\n"


def token_chunks(content: str, size: int = 24):
    if size < 1:
        raise ValueError("token chunk size must be positive")
    for offset in range(0, len(content), size):
        yield content[offset : offset + size]

