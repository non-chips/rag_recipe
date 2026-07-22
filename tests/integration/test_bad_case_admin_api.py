from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from recipe_assistant.api.admin_bad_cases import router as admin_bad_cases_router
from recipe_assistant.api.application import ApiApplicationService
from recipe_assistant.api.dependencies import ApiContainer
from recipe_assistant.core.database import Base, create_session_factory, session_scope
from recipe_assistant.main import create_app
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.bad_case import BadCaseCandidate
from recipe_assistant.models.session import ChatSession
from recipe_assistant.models.user import UserAccount
from recipe_assistant.services.nutrition import NutritionCatalog


class _UnusedChatRunner:
    def run(self, request):  # pragma: no cover
        raise AssertionError(f"unexpected chat request: {request}")


def _client() -> tuple[TestClient, int]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    Base.metadata.create_all(engine)
    with session_scope(factory) as session:
        user = UserAccount(username="admin-api-user", password_hash="hash")
        session.add(user)
        session.flush()
        chat = ChatSession(user_id=user.id)
        session.add(chat)
        session.flush()
        trace = AgentRunTrace(
            run_id="admin-api-run",
            user_id=user.id,
            session_id=chat.id,
            route="RECIPE_KNOWLEDGE",
            original_input="unknown recipe",
            normalized_input="unknown recipe",
            sources_json=[],
        )
        session.add(trace)
        session.flush()
        candidate = BadCaseCandidate(
            fingerprint="admin-api-fingerprint",
            user_id=user.id,
            session_id=chat.id,
            first_run_id=trace.run_id,
            latest_run_id=trace.run_id,
            status="PENDING_REVIEW",
            score=0.7,
            normalized_request="unknown recipe",
            trigger_types_json=["EMPTY_RETRIEVAL"],
            snapshot_json={"trace": {"retrieval_hits": []}},
        )
        session.add(candidate)
        session.flush()
        candidate_id = candidate.id
    container = ApiContainer(
        engine=engine,
        session_factory=factory,
        chat_runner=_UnusedChatRunner(),
        application=ApiApplicationService(factory, NutritionCatalog()),
    )
    application = create_app(lambda: container)
    application.include_router(admin_bad_cases_router)
    return TestClient(application), candidate_id


def test_admin_api_rejects_missing_wrong_and_ordinary_user_credentials(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-admin-secret")
    client, candidate_id = _client()
    with client:
        missing = client.get(f"/api/admin/bad-cases/{candidate_id}")
        wrong = client.get(
            f"/api/admin/bad-cases/{candidate_id}",
            headers={"X-Admin-Id": "dev", "X-Admin-Token": "wrong"},
        )
        ordinary = client.get(
            f"/api/admin/bad-cases/{candidate_id}",
            headers={"X-User-Id": "1"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 403
    assert ordinary.status_code == 401


def test_admin_api_lists_details_and_records_developer_approval(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-admin-secret")
    client, candidate_id = _client()
    headers = {"X-Admin-Id": "developer-7", "X-Admin-Token": "test-admin-secret"}
    with client:
        listing = client.get("/api/admin/bad-cases", headers=headers)
        detail = client.get(f"/api/admin/bad-cases/{candidate_id}", headers=headers)
        approved = client.post(
            f"/api/admin/bad-cases/{candidate_id}/approve",
            headers=headers,
            json={
                "final_category": "KNOWLEDGE_GAP",
                "final_root_cause": "The requested recipe is absent from the catalog.",
                "review_note": "Confirmed against the indexed source inventory.",
                "severity": "MEDIUM",
            },
        )

    assert listing.status_code == 200
    assert listing.json()[0]["id"] == candidate_id
    assert detail.status_code == 200
    assert detail.json()["root_cause_suggestion"]["possible_category"] == "RETRIEVAL_MISS"
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "APPROVED"
    assert body["reviews"][0]["reviewer_id"] == "developer-7"
    assert body["reviews"][0]["final_category"] == "KNOWLEDGE_GAP"
    assert body["regression_draft"]["developer_confirmed"] is False
