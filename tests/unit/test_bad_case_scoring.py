from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from recipe_assistant.core.database import Base, create_session_factory, session_scope
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.bad_case import BadCaseCandidate
from recipe_assistant.models.implicit_feedback_signal import ImplicitFeedbackSignal
from recipe_assistant.models.session import ChatSession
from recipe_assistant.models.user import UserAccount
from recipe_assistant.schemas.feedback import (
    BadCaseEvaluationRequest,
    BadCaseScoringConfig,
    BadCaseStatus,
    ToneSignal,
)
from recipe_assistant.services.bad_case import BadCaseService


def _setup():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    Base.metadata.create_all(engine)
    with session_scope(factory) as session:
        user = UserAccount(username="score-user", password_hash="hash")
        session.add(user)
        session.flush()
        chat = ChatSession(user_id=user.id)
        session.add(chat)
        session.flush()
        trace = AgentRunTrace(
            run_id="score-run",
            user_id=user.id,
            session_id=chat.id,
            route="RECIPE_RECOMMENDATION",
            original_input="recommend",
            normalized_input="recommend",
        )
        session.add(trace)
        session.flush()
        return factory, user.id, chat.id


def _tone(**changes) -> ToneSignal:
    values = {
        "possible_frustration": 0.05,
        "possible_impatience": 0.05,
        "possible_dissatisfaction": 0.05,
        "repeated_request": False,
        "repeated_constraint": False,
        "requested_retry": False,
        "explicit_error_reported": False,
        "evidence": (),
        "confidence": 0.8,
    }
    values.update(changes)
    return ToneSignal(**values)


def _request(user_id: int, session_id: int, **changes) -> BadCaseEvaluationRequest:
    values = {
        "user_id": user_id,
        "run_id": "score-run",
        "session_id": session_id,
        "normalized_request": "recommend a quick dinner",
        "tone_signal": _tone(),
    }
    values.update(changes)
    return BadCaseEvaluationRequest(**values)


def test_single_tone_signal_stays_signal() -> None:
    factory, user_id, session_id = _setup()
    result = BadCaseService(factory).evaluate(
        _request(
            user_id,
            session_id,
            tone_signal=_tone(possible_impatience=0.85, confidence=0.9),
        )
    )

    assert result.status is BadCaseStatus.SIGNAL
    assert result.score == 0.20
    assert result.candidate_id is None
    with session_scope(factory) as session:
        assert session.scalar(select(func.count(BadCaseCandidate.id))) == 0
        assert session.scalar(select(func.count(ImplicitFeedbackSignal.id))) == 1


def test_two_weak_signals_create_pending_review_candidate() -> None:
    factory, user_id, session_id = _setup()
    result = BadCaseService(factory).evaluate(
        _request(
            user_id,
            session_id,
            tone_signal=_tone(repeated_request=True, repeated_constraint=True),
        )
    )

    assert result.status is BadCaseStatus.PENDING_REVIEW
    assert result.score == 0.50
    assert result.candidate_created is True
    assert set(result.triggers) == {"REPEATED_REQUEST", "REPEATED_CONSTRAINT"}


def test_strong_signal_is_pending_but_like_cannot_hide_objective_violation() -> None:
    factory, user_id, session_id = _setup()
    result = BadCaseService(factory).evaluate(
        _request(
            user_id,
            session_id,
            explicit_rating="LIKE",
            hard_constraint_violations=("allergen_conflict",),
        )
    )

    assert result.status is BadCaseStatus.PENDING_REVIEW
    assert result.score == 0.30
    assert "HARD_CONSTRAINT_VIOLATION" in result.triggers


def test_scoring_weights_are_replaceable_configuration() -> None:
    factory, user_id, session_id = _setup()
    config = BadCaseScoringConfig(
        tool_failure_weight=0.40,
        empty_retrieval_weight=0.35,
        candidate_threshold=0.70,
    )
    result = BadCaseService(factory, config).evaluate(
        _request(user_id, session_id, tool_failure=True, empty_retrieval=True)
    )

    assert result.status is BadCaseStatus.PENDING_REVIEW
    assert result.score == 0.75
