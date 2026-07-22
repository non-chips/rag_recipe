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
    BadCaseStatus,
    ToneAnalysisRequest,
)
from recipe_assistant.services.bad_case import BadCaseService
from recipe_assistant.services.constraint import (
    ConstraintService,
    PreferenceContext,
    RecipeCandidate,
    TemporaryConstraints,
)
from recipe_assistant.services.tone_analysis import ToneAnalysisService


def test_trace_constraints_and_weak_signals_create_and_deduplicate_candidate() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    Base.metadata.create_all(engine)
    with session_scope(factory) as session:
        user = UserAccount(username="flow-user", password_hash="hash")
        session.add(user)
        session.flush()
        chat = ChatSession(user_id=user.id)
        session.add(chat)
        session.flush()
        for run_id in ("flow-run-1", "flow-run-2"):
            session.add(
                AgentRunTrace(
                    run_id=run_id,
                    user_id=user.id,
                    session_id=chat.id,
                    route="RECIPE_RECOMMENDATION",
                    original_input="不要花生，重新推荐晚餐",
                    normalized_input="不要花生，重新推荐晚餐",
                    events_json=[{"type": "tool_error", "tool": "recipe_search"}],
                    sources_json=[],
                )
            )
        session.flush()
        user_id = user.id
        session_id = chat.id

    validation = ConstraintService().validate(
        candidates=(
            RecipeCandidate(
                recipe_id="peanut-noodles",
                ingredients=("面条", "花生"),
                source_path="recipes.json",
                evidence="catalog record",
            ),
        ),
        constraints=TemporaryConstraints(),
        preferences=PreferenceContext(allergens=("花生",)),
    )
    violations = tuple(
        reason for rejected in validation.rejected for reason in rejected.reasons
    )
    tone = ToneAnalysisService().analyze(
        ToneAnalysisRequest(
            current_text="我说过不要花生，请重新推荐晚餐",
            recent_user_messages=("不要花生，请推荐晚餐",),
            current_constraints=("不要花生",),
            recent_constraints=("不要花生",),
        )
    )
    service = BadCaseService(factory)

    results = []
    for run_id in ("flow-run-1", "flow-run-2"):
        results.append(
            service.evaluate(
                BadCaseEvaluationRequest(
                    user_id=user_id,
                    run_id=run_id,
                    session_id=session_id,
                    normalized_request="不要花生，重新推荐晚餐",
                    tone_signal=tone,
                    tool_failure=True,
                    empty_retrieval=True,
                    hard_constraint_violations=violations,
                    trace_snapshot={
                        "route": "RECIPE_RECOMMENDATION",
                        "events": [{"type": "tool_error"}],
                        "retrieval_hits": [],
                    },
                )
            )
        )

    assert results[0].status is BadCaseStatus.PENDING_REVIEW
    assert results[0].candidate_created is True
    assert results[1].candidate_created is False
    assert results[0].candidate_id == results[1].candidate_id
    assert results[1].occurrence_count == 2
    with session_scope(factory) as session:
        assert session.scalar(select(func.count(BadCaseCandidate.id))) == 1
        assert session.scalar(select(func.count(ImplicitFeedbackSignal.id))) >= 8
        candidate = session.get(BadCaseCandidate, results[1].candidate_id)
        assert candidate is not None
        assert candidate.status == "PENDING_REVIEW"
        assert candidate.latest_run_id == "flow-run-2"
