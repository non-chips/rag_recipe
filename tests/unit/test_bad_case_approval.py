from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import DatabaseError
from sqlalchemy.pool import StaticPool

from recipe_assistant.core.database import Base, create_session_factory, session_scope
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.bad_case import BadCaseCandidate
from recipe_assistant.models.bad_case_review import BadCaseReview
from recipe_assistant.models.session import ChatSession
from recipe_assistant.models.user import UserAccount
from recipe_assistant.schemas.api.bad_case_admin import (
    ApproveBadCaseRequest,
    ConfirmRegressionDraftRequest,
    MergeBadCaseRequest,
    RejectBadCaseRequest,
    ResolveBadCaseRequest,
)
from recipe_assistant.services.evaluation import EvaluationService


def _setup(candidate_count: int = 1):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    Base.metadata.create_all(engine)
    candidate_ids = []
    with session_scope(factory) as session:
        user = UserAccount(username="review-user", password_hash="hash")
        session.add(user)
        session.flush()
        chat = ChatSession(user_id=user.id)
        session.add(chat)
        session.flush()
        for index in range(candidate_count):
            run_id = f"review-run-{index}"
            session.add(
                AgentRunTrace(
                    run_id=run_id,
                    user_id=user.id,
                    session_id=chat.id,
                    route="RECIPE_RECOMMENDATION",
                    original_input="no peanuts",
                    normalized_input="no peanuts",
                    events_json=[{"type": "tool_error"}],
                )
            )
            session.flush()
            candidate = BadCaseCandidate(
                fingerprint=f"fingerprint-{index}",
                user_id=user.id,
                session_id=chat.id,
                first_run_id=run_id,
                latest_run_id=run_id,
                status="PENDING_REVIEW",
                score=0.8,
                normalized_request=f"no peanuts {index}",
                trigger_types_json=["TOOL_FAILURE"],
                snapshot_json={"hard_constraint_violations": []},
            )
            session.add(candidate)
            session.flush()
            candidate_ids.append(candidate.id)
    return factory, candidate_ids


def test_approval_keeps_automatic_and_final_root_cause_separate() -> None:
    factory, candidate_ids = _setup()
    detail = EvaluationService(factory).approve(
        candidate_ids[0],
        "developer-a",
        ApproveBadCaseRequest(
            final_category="KNOWLEDGE_GAP",
            final_root_cause="The indexed recipe lacks allergen metadata.",
            review_note="Confirmed after inspecting the source record.",
            severity="HIGH",
            assignee="developer-b",
        ),
    )

    assert detail.status == "APPROVED"
    assert detail.regression_draft is not None
    assert detail.regression_draft.developer_confirmed is False
    review = detail.reviews[0]
    assert review.automatic_category.value == "TOOL_FAILURE"
    assert review.final_category.value == "KNOWLEDGE_GAP"
    assert review.final_root_cause != review.automatic_suggestion["explanation"]

    with pytest.raises(ValueError, match="status must be PENDING_REVIEW"):
        EvaluationService(factory).approve(
            candidate_ids[0],
            "developer-a",
            ApproveBadCaseRequest(
                final_category="OTHER",
                final_root_cause="A second approval must not overwrite history.",
                review_note="Invalid duplicate approval.",
            ),
        )


def test_resolution_requires_developer_confirmed_regression_expectation() -> None:
    factory, candidate_ids = _setup()
    service = EvaluationService(factory)
    service.approve(
        candidate_ids[0],
        "developer-a",
        ApproveBadCaseRequest(
            final_category="TOOL_FAILURE",
            final_root_cause="The adapter returned an unrecoverable error.",
            review_note="Confirmed from the Trace timeline.",
        ),
    )

    with pytest.raises(ValueError, match="confirm the regression draft"):
        service.resolve(
            candidate_ids[0],
            "developer-a",
            ResolveBadCaseRequest(
                fix_reference="commit abc123",
                review_note="Attempted before confirming expected output.",
                evaluation_passed=True,
                evaluation_evidence=("focused test passed",),
            ),
        )
    service.confirm_regression_draft(
        candidate_ids[0],
        "developer-a",
        ConfirmRegressionDraftRequest(
            expected_output="Return a safe recipe without peanuts.",
            expected_constraints=("exclude peanuts",),
            review_note="Expected behavior reviewed manually.",
        ),
    )
    resolved = service.resolve(
        candidate_ids[0],
        "developer-a",
        ResolveBadCaseRequest(
            fix_reference="commit abc123",
            review_note="Fix and focused regression test are linked.",
            evaluation_passed=True,
            evaluation_evidence=("focused and complete regression suites passed",),
            metrics={"suite_pass_rate": 1.0},
            regression_test_reference="tests/e2e/test_no_peanuts.py",
        ),
    )
    assert resolved.status == "RESOLVED"
    assert [review.action.value for review in resolved.reviews] == [
        "APPROVE",
        "CONFIRM_REGRESSION_DRAFT",
        "RESOLVE",
    ]


def test_reject_and_merge_append_audit_records() -> None:
    factory, candidate_ids = _setup(candidate_count=3)
    service = EvaluationService(factory)
    rejected = service.reject(
        candidate_ids[0],
        "developer-a",
        RejectBadCaseRequest(review_note="Not a product defect after inspection."),
    )
    merged = service.merge(
        candidate_ids[1],
        "developer-b",
        MergeBadCaseRequest(
            target_bad_case_id=candidate_ids[2],
            review_note="Same failure mode and affected adapter.",
        ),
    )

    assert rejected.status == "REJECTED"
    assert merged.status == "MERGED"
    assert merged.reviews[0].merge_target_id == candidate_ids[2]
    with session_scope(factory) as session:
        assert session.scalar(select(func.count(BadCaseReview.id))) == 2


def test_review_audit_rows_cannot_be_updated_or_deleted() -> None:
    factory, candidate_ids = _setup()
    EvaluationService(factory).reject(
        candidate_ids[0],
        "developer-a",
        RejectBadCaseRequest(review_note="Reviewed and rejected with evidence."),
    )

    with pytest.raises(DatabaseError, match="append-only"):
        with session_scope(factory) as session:
            review = session.scalar(select(BadCaseReview))
            review.review_note = "tampered"
    with pytest.raises(DatabaseError, match="append-only"):
        with session_scope(factory) as session:
            review = session.scalar(select(BadCaseReview))
            session.delete(review)
