from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from recipe_assistant.api.application import ApiApplicationService
from recipe_assistant.api.dependencies import ApiContainer
from recipe_assistant.api.feedback import router as feedback_router
from recipe_assistant.core.database import Base, create_session_factory, session_scope
from recipe_assistant.main import create_app
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.message import ChatMessage, MessageRole
from recipe_assistant.models.session import ChatSession
from recipe_assistant.models.user import UserAccount
from recipe_assistant.services.nutrition import NutritionCatalog


class _UnusedChatRunner:
    def run(self, request):  # pragma: no cover - feedback API does not call chat
        raise AssertionError(f"unexpected chat request: {request}")


def _build_client() -> tuple[TestClient, dict[str, int | str]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    Base.metadata.create_all(engine)
    with session_scope(factory) as session:
        owner = UserAccount(username="api-owner", password_hash="hash")
        other = UserAccount(username="api-other", password_hash="hash")
        session.add_all([owner, other])
        session.flush()
        chat = ChatSession(user_id=owner.id)
        session.add(chat)
        session.flush()
        message = ChatMessage(
            user_id=owner.id,
            session_id=chat.id,
            role=MessageRole.ASSISTANT,
            content="answer",
        )
        trace = AgentRunTrace(
            run_id="api-run",
            user_id=owner.id,
            session_id=chat.id,
            route="SIMPLE",
            original_input="question",
            normalized_input="question",
        )
        session.add_all([message, trace])
        session.flush()
        ids = {
            "owner_id": owner.id,
            "other_id": other.id,
            "message_id": message.id,
            "run_id": trace.run_id,
        }
    container = ApiContainer(
        engine=engine,
        session_factory=factory,
        chat_runner=_UnusedChatRunner(),
        application=ApiApplicationService(factory, NutritionCatalog()),
    )
    application = create_app(lambda: container)
    application.include_router(feedback_router)
    return TestClient(application), ids


def test_feedback_api_submits_recovers_and_updates_idempotently() -> None:
    client, ids = _build_client()
    headers = {"X-User-Id": str(ids["owner_id"])}
    payload = {
        "run_id": ids["run_id"],
        "message_id": ids["message_id"],
        "rating": "DISLIKE",
        "reason_tags": ["IRRELEVANT", "TOO_VERBOSE"],
        "comment": "Please answer the actual question.",
    }
    with client:
        first = client.post("/api/feedback", headers=headers, json=payload)
        repeated = client.post("/api/feedback", headers=headers, json=payload)
        recovered = client.get(
            f"/api/feedback/{ids['message_id']}", headers=headers
        )

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert recovered.status_code == 200
    assert first.json()["id"] == repeated.json()["id"] == recovered.json()["id"]
    assert recovered.json()["reason_tags"] == ["IRRELEVANT", "TOO_VERBOSE"]


def test_feedback_api_rejects_foreign_user_and_invalid_tags() -> None:
    client, ids = _build_client()
    payload = {
        "run_id": ids["run_id"],
        "message_id": ids["message_id"],
        "rating": "LIKE",
    }
    with client:
        forbidden = client.post(
            "/api/feedback",
            headers={"X-User-Id": str(ids["other_id"])},
            json=payload,
        )
        invalid = client.post(
            "/api/feedback",
            headers={"X-User-Id": str(ids["owner_id"])},
            json={**payload, "reason_tags": ["MADE_UP"]},
        )
        missing = client.get(
            "/api/feedback/99999",
            headers={"X-User-Id": str(ids["owner_id"])},
        )

    assert forbidden.status_code == 403
    assert invalid.status_code == 422
    assert missing.status_code == 404
