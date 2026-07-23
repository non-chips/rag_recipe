from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from recipe_assistant.agents.result import AgentRunResult, HarnessOutcome, RunStatus
from recipe_assistant.agents.router import BusinessRouter
from recipe_assistant.api.application import ApiApplicationService
from recipe_assistant.api.dependencies import ApiContainer
from recipe_assistant.core.database import Base, create_session_factory, session_scope
from recipe_assistant.main import create_app
from recipe_assistant.repositories.sqlite import SqlAlchemyUserRepository
from recipe_assistant.services.chat import ChatService
from recipe_assistant.services.nutrition import NutritionCatalog


class _OfflineHarness:
    @staticmethod
    def normalize_input(text: str) -> str:
        return " ".join(text.strip().split())

    def run(self, context):
        decision = BusinessRouter().route(context.normalized_input)
        result = AgentRunResult(
            status=RunStatus.SUCCEEDED,
            final_text=(
                f"离线回答（V2）：{context.normalized_input}"
                f"（会话 {context.session_public_id}）"
            ),
            events=[{"type": "v2_test_runtime"}],
        )
        return HarnessOutcome(
            context=context,
            route_decision=decision,
            result=result,
            latency_ms=0.0,
        )


def _parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        data_line = next(
            line for line in block.splitlines() if line.startswith("data: ")
        )
        events.append(json.loads(data_line.removeprefix("data: ")))
    return events


def test_chat_sse_persists_session_messages_and_trace() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    Base.metadata.create_all(engine)
    with session_scope(factory) as session:
        user_id = SqlAlchemyUserRepository(session).create("chat-user", "hash").id
    harness = _OfflineHarness()
    container = ApiContainer(
        engine=engine,
        session_factory=factory,
        chat_runner=ChatService(factory, harness),
        application=ApiApplicationService(factory, NutritionCatalog()),
    )

    with TestClient(create_app(lambda: container)) as client:
        headers = {"X-User-Id": str(user_id)}
        first = client.post(
            "/api/chat/stream",
            headers=headers,
            json={"message": "宫保鸡丁怎么做"},
        )
        assert first.status_code == 200
        assert first.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(first.text)
        types = [event["type"] for event in events]
        assert types[:2] == ["meta", "status"]
        assert "token" in types
        assert types[-1] == "done"
        assert all(event["version"] == "1.0" for event in events)
        meta = next(event for event in events if event["type"] == "meta")
        done = events[-1]
        assert "离线回答" in done["content"]

        second = client.post(
            "/api/chat/stream",
            headers=headers,
            json={"message": "谢谢", "sessionId": meta["sessionId"]},
        )
        second_events = _parse_sse(second.text)
        second_meta = next(event for event in second_events if event["type"] == "meta")
        assert second_meta["sessionId"] == meta["sessionId"]

        sessions = client.get("/api/sessions", headers=headers).json()
        assert len(sessions) == 1
        messages = client.get(
            f"/api/sessions/{meta['sessionId']}/messages",
            headers=headers,
        ).json()
        assert [message["role"] for message in messages] == [
            "USER",
            "ASSISTANT",
            "USER",
            "ASSISTANT",
        ]
        trace = client.get(f"/api/agent/runs/{meta['runId']}", headers=headers)
        assert trace.status_code == 200
        assert trace.json()["route"] == "RECIPE_KNOWLEDGE"

    assert container.started is False
