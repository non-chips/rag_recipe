import json

import pytest

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

