from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from recipe_assistant.core.database import Base, create_session_factory, session_scope
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.message import ChatMessage, MessageRole
from recipe_assistant.models.session import ChatSession
from recipe_assistant.models.user import UserAccount
from recipe_assistant.schemas.api.bad_case_admin import ApproveBadCaseRequest
from recipe_assistant.schemas.feedback import (
    AnswerFeedbackRequest,
    FeedbackReasonTag,
)
from recipe_assistant.services.evaluation import EvaluationService
from recipe_assistant.services.feedback import FeedbackService


def test_dislike_trace_candidate_waits_for_explicit_developer_approval() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    Base.metadata.create_all(engine)
    with session_scope(factory) as session:
        user = UserAccount(username="feedback-review-user", password_hash="hash")
        session.add(user)
        session.flush()
        chat = ChatSession(user_id=user.id)
        session.add(chat)
        session.flush()
        answer = ChatMessage(
            user_id=user.id,
            session_id=chat.id,
            role=MessageRole.ASSISTANT,
            content="The wrong recipe answer.",
        )
        trace = AgentRunTrace(
            run_id="feedback-review-run",
            user_id=user.id,
            session_id=chat.id,
            route="RECIPE_KNOWLEDGE",
            original_input="How do I make the first recipe?",
            normalized_input="How do I make the first recipe?",
            events_json=[{"type": "context_resolution"}],
            sources_json=[{"recipeName": "Expected recipe"}],
        )
        session.add_all([answer, trace])
        session.flush()
        user_id = user.id
        message_id = answer.id

    FeedbackService(factory).submit(
        user_id,
        AnswerFeedbackRequest(
            run_id="feedback-review-run",
            message_id=message_id,
            rating="DISLIKE",
            reason_tags=[FeedbackReasonTag.INCORRECT],
            comment="The answer did not use the referenced recipe.",
        ),
    )

    evaluation = EvaluationService(factory)
    pending = evaluation.list_candidates("PENDING_REVIEW")
    assert len(pending) == 1
    detail = evaluation.get_detail(pending[0].id)
    assert detail.status == "PENDING_REVIEW"
    assert detail.reviews == ()
    assert detail.regression_draft is None
    assert detail.snapshot["feedback"]["message_id"] == message_id
    assert detail.snapshot["trace"]["sources"] == [
        {"recipeName": "Expected recipe"}
    ]

    approved = evaluation.approve(
        detail.id,
        "developer-reviewer",
        ApproveBadCaseRequest(
            final_category="KNOWLEDGE_GAP",
            final_root_cause="The response ignored the grounded recipe source.",
            review_note="Confirmed from the feedback-linked Trace.",
            severity="MEDIUM",
        ),
    )

    assert approved.status == "APPROVED"
    assert len(approved.reviews) == 1
    assert approved.reviews[0].reviewer_id == "developer-reviewer"
    assert approved.regression_draft is not None
    assert approved.regression_draft.developer_confirmed is False
