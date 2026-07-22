from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from recipe_assistant.core.database import Base, create_session_factory, session_scope
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.bad_case import BadCaseCandidate
from recipe_assistant.models.bad_case_resolution import BadCaseResolution
from recipe_assistant.models.bad_case_review import BadCaseReview
from recipe_assistant.models.session import ChatSession
from recipe_assistant.models.user import UserAccount
from recipe_assistant.schemas.api.bad_case_admin import (
    ApproveBadCaseRequest,
    ConfirmRegressionDraftRequest,
    ResolveBadCaseRequest,
    VerifyBadCaseRequest,
)
from recipe_assistant.services.evaluation import EvaluationService


def test_developer_review_to_verified_preserves_full_audit_chain() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    Base.metadata.create_all(engine)
    with session_scope(factory) as session:
        user = UserAccount(username="review-flow-user", password_hash="hash")
        session.add(user)
        session.flush()
        chat = ChatSession(user_id=user.id)
        session.add(chat)
        session.flush()
        trace = AgentRunTrace(
            run_id="review-flow-run",
            user_id=user.id,
            session_id=chat.id,
            route="RECIPE_RECOMMENDATION",
            original_input="I am allergic to peanuts",
            normalized_input="exclude peanuts",
            events_json=[{"type": "constraint_validation"}],
            sources_json=[{"recipe_id": "unsafe-recipe"}],
        )
        session.add(trace)
        session.flush()
        candidate = BadCaseCandidate(
            fingerprint="review-flow-fingerprint",
            user_id=user.id,
            session_id=chat.id,
            first_run_id=trace.run_id,
            latest_run_id=trace.run_id,
            status="PENDING_REVIEW",
            score=0.8,
            normalized_request="exclude peanuts",
            trigger_types_json=["HARD_CONSTRAINT_VIOLATION"],
            snapshot_json={
                "hard_constraint_violations": ["allergen_conflict"],
                "assistant_answer": "Try peanut noodles.",
            },
        )
        session.add(candidate)
        session.flush()
        candidate_id = candidate.id

    service = EvaluationService(factory)
    approved = service.approve(
        candidate_id,
        "developer-owner",
        ApproveBadCaseRequest(
            final_category="CONSTRAINT_VIOLATION",
            final_root_cause="Allergen filtering was not applied after ranking.",
            review_note="Reproduced with the saved candidate and Trace.",
            severity="CRITICAL",
            assignee="safety-team",
        ),
    )
    assert approved.regression_draft is not None
    assert approved.regression_draft.expected_output is None

    confirmed = service.confirm_regression_draft(
        candidate_id,
        "developer-owner",
        ConfirmRegressionDraftRequest(
            expected_output="Never recommend a recipe containing peanuts.",
            expected_constraints=("allergen:peanut",),
            review_note="Expected safety behavior confirmed manually.",
        ),
    )
    assert confirmed.regression_draft.developer_confirmed is True

    resolved = service.resolve(
        candidate_id,
        "implementer",
        ResolveBadCaseRequest(
            fix_reference="commit:safe-filter-123",
            issue_reference="ISSUE-42",
            regression_test_reference="tests/e2e/test_allergen_filter.py",
            review_note="Hard filter moved after ranking and focused test added.",
            evaluation_passed=True,
            evaluation_evidence=(
                "focused allergen test passed",
                "complete recommendation suite showed no regression",
            ),
            metrics={"focused_pass_rate": 1.0, "suite_pass_rate": 1.0},
        ),
    )
    assert resolved.status == "RESOLVED"

    with pytest.raises(ValueError, match="failed verification"):
        service.verify(
            candidate_id,
            "verifier",
            VerifyBadCaseRequest(
                verification_passed=False,
                verification_evidence=("focused test failed",),
                metrics={"focused_pass_rate": 0.0},
                review_note="Verification failed and must not close the case.",
            ),
        )

    verified = service.verify(
        candidate_id,
        "verifier",
        VerifyBadCaseRequest(
            verification_passed=True,
            verification_evidence=(
                "focused allergen regression passed",
                "complete recommendation suite passed",
            ),
            metrics={"focused_pass_rate": 1.0, "suite_pass_rate": 1.0},
            review_note="Focused and complete regression suites passed.",
        ),
    )

    assert verified.status == "VERIFIED"
    assert [review.to_status for review in verified.reviews] == [
        "APPROVED",
        "APPROVED",
        "RESOLVED",
        "VERIFIED",
    ]
    assert verified.reviews[0].final_root_cause == (
        "Allergen filtering was not applied after ranking."
    )
    assert verified.resolutions[-1].metrics["suite_pass_rate"] == 1.0
    with session_scope(factory) as session:
        assert session.scalar(select(func.count(BadCaseReview.id))) == 4
        assert session.scalar(select(func.count(BadCaseResolution.id))) == 2
