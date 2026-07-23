import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recipe_assistant.api.chat import router
from recipe_assistant.api.dependencies import get_container, get_user_id
from recipe_assistant.api.sse import encode_sse
from recipe_assistant.schemas.api import (
    DoneEvent,
    ErrorEvent,
    MetaEvent,
    SourceEvent,
    StatusEvent,
    TokenEvent,
)


@pytest.mark.parametrize(
    "event",
    [
        MetaEvent(session_id="session-1", run_id="run-1", route="SIMPLE"),
        StatusEvent(stage="routing", message="正在路由"),
        TokenEvent(content="你好"),
        SourceEvent(source={"recipe_id": "r1"}),
        DoneEvent(message_id=7, content="完成"),
        ErrorEvent(code="FAILED", message="失败", retryable=True),
    ],
)
def test_sse_events_have_stable_names_version_and_json(event) -> None:
    encoded = encode_sse(event)
    lines = encoded.strip().splitlines()

    assert lines[0] == f"event: {event.type}"
    payload = json.loads(lines[1].removeprefix("data: "))
    assert payload["type"] == event.type
    assert payload["version"] == "1.0"
    assert "sessionId" in payload if event.type == "meta" else True


def test_sse_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        TokenEvent(content="x", internal_trace="secret")  # type: ignore[call-arg]


def _stream_client(runner) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user_id] = lambda: 1
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(
        chat_runner=runner
    )
    return TestClient(app)


def _event_payloads(body: str) -> list[dict]:
    return [
        json.loads(
            next(
                line
                for line in block.splitlines()
                if line.startswith("data: ")
            ).removeprefix("data: ")
        )
        for block in body.strip().split("\n\n")
    ]


class _StreamingRunner:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    def run(self, request):
        del request
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            session_public_id="session",
            run_id="run",
            route=SimpleNamespace(value="RECIPE_KNOWLEDGE"),
            assistant_message_id=7,
            content="real streamed response",
            outcome=SimpleNamespace(
                result=SimpleNamespace(
                    sources=[],
                    streamed_tokens=["real ", "streamed ", "response"],
                )
            ),
        )


def test_sse_forwards_only_explicit_runtime_tokens_in_stable_order() -> None:
    with _stream_client(_StreamingRunner()) as client:
        response = client.post("/api/chat/stream", json={"message": "test"})

    events = _event_payloads(response.text)
    types = [event["type"] for event in events]
    assert types[0] == "meta"
    assert types[-1] == "done"
    assert [
        event["content"] for event in events if event["type"] == "token"
    ] == ["real ", "streamed ", "response"]
    assert [
        event["stage"] for event in events if event["type"] == "status"
    ][-1] == "completed"


def test_sse_failure_always_uses_versioned_error_contract() -> None:
    with _stream_client(_StreamingRunner(error=TimeoutError("late"))) as client:
        response = client.post("/api/chat/stream", json={"message": "test"})

    events = _event_payloads(response.text)
    assert events == [
        {
            "version": "1.0",
            "type": "error",
            "code": "CHAT_EXECUTION_FAILED",
            "message": "本次请求暂时无法完成，请稍后重试。",
            "retryable": True,
        }
    ]
