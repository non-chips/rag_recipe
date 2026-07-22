from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from recipe_assistant.core.database import Base, create_session_factory, session_scope
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.interaction_feedback import InteractionFeedback
from recipe_assistant.models.message import ChatMessage, MessageRole
from recipe_assistant.models.recipe_interaction import RecipeInteraction
from recipe_assistant.models.session import ChatSession
from recipe_assistant.models.user import UserAccount
from recipe_assistant.schemas.feedback import (
    AnswerFeedbackRequest,
    FeedbackReasonTag,
    RecipePreferenceEventRequest,
)
from recipe_assistant.services.feedback import FeedbackService


def _factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _seed(factory) -> dict[str, int | str]:
    with session_scope(factory) as session:
        owner = UserAccount(username="feedback-owner", password_hash="hash")
        other = UserAccount(username="feedback-other", password_hash="hash")
        session.add_all([owner, other])
        session.flush()
        owner_chat = ChatSession(user_id=owner.id)
        other_chat = ChatSession(user_id=other.id)
        session.add_all([owner_chat, other_chat])
        session.flush()
        assistant = ChatMessage(
            session_id=owner_chat.id,
            user_id=owner.id,
            role=MessageRole.ASSISTANT,
            content="answer",
        )
        user_message = ChatMessage(
            session_id=owner_chat.id,
            user_id=owner.id,
            role=MessageRole.USER,
            content="question",
        )
        foreign_assistant = ChatMessage(
            session_id=other_chat.id,
            user_id=other.id,
            role=MessageRole.ASSISTANT,
            content="foreign answer",
        )
        session.add_all([assistant, user_message, foreign_assistant])
        session.flush()
        owner_trace = AgentRunTrace(
            run_id="run-owner",
            user_id=owner.id,
            session_id=owner_chat.id,
            route="SIMPLE",
            original_input="question",
            normalized_input="question",
        )
        foreign_trace = AgentRunTrace(
            run_id="run-other-session",
            user_id=other.id,
            session_id=other_chat.id,
            route="SIMPLE",
            original_input="question",
            normalized_input="question",
        )
        session.add_all([owner_trace, foreign_trace])
        session.flush()
        return {
            "user_id": owner.id,
            "other_user_id": other.id,
            "message_id": assistant.id,
            "user_message_id": user_message.id,
            "foreign_message_id": foreign_assistant.id,
            "run_id": owner_trace.run_id,
            "foreign_run_id": foreign_trace.run_id,
        }


def test_submit_is_idempotent_and_can_explicitly_change_rating() -> None:
    factory = _factory()
    ids = _seed(factory)
    service = FeedbackService(factory)
    like = AnswerFeedbackRequest(
        run_id=str(ids["run_id"]),
        message_id=int(ids["message_id"]),
        rating="LIKE",
    )

    first = service.submit(int(ids["user_id"]), like)
    repeated = service.submit(int(ids["user_id"]), like)

    assert repeated.id == first.id
    assert repeated.updated_at == first.updated_at
    dislike = service.submit(
        int(ids["user_id"]),
        AnswerFeedbackRequest(
            run_id=str(ids["run_id"]),
            message_id=int(ids["message_id"]),
            rating="DISLIKE",
            reason_tags=[FeedbackReasonTag.INCORRECT],
            comment="The cooking time is wrong.",
        ),
    )
    assert dislike.id == first.id
    assert dislike.rating.value == "DISLIKE"
    assert dislike.reason_tags == [FeedbackReasonTag.INCORRECT]

    with session_scope(factory) as session:
        feedback_count = session.scalar(select(func.count(InteractionFeedback.id)))
        recipe_event_count = session.scalar(select(func.count(RecipeInteraction.id)))
    assert feedback_count == 1
    assert recipe_event_count == 0


def test_submit_checks_message_run_ownership_role_and_session() -> None:
    factory = _factory()
    ids = _seed(factory)
    service = FeedbackService(factory)

    with pytest.raises(PermissionError):
        service.submit(
            int(ids["other_user_id"]),
            AnswerFeedbackRequest(
                run_id=str(ids["run_id"]),
                message_id=int(ids["message_id"]),
                rating="LIKE",
            ),
        )
    with pytest.raises(ValueError, match="assistant message"):
        service.submit(
            int(ids["user_id"]),
            AnswerFeedbackRequest(
                run_id=str(ids["run_id"]),
                message_id=int(ids["user_message_id"]),
                rating="LIKE",
            ),
        )
    with pytest.raises(PermissionError, match="agent run"):
        service.submit(
            int(ids["user_id"]),
            AnswerFeedbackRequest(
                run_id=str(ids["foreign_run_id"]),
                message_id=int(ids["message_id"]),
                rating="DISLIKE",
            ),
        )


def test_recipe_preference_contract_is_distinct_from_answer_feedback() -> None:
    recipe_event = RecipePreferenceEventRequest(
        recipe_id="recipe-42", event_type="DISLIKE_RECIPE"
    )
    assert recipe_event.event_type.value == "DISLIKE_RECIPE"
    with pytest.raises(ValueError):
        RecipePreferenceEventRequest(recipe_id="recipe-42", event_type="DISLIKE")
