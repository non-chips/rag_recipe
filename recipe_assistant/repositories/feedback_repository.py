"""Persistence operations dedicated to answer feedback."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from recipe_assistant.core.database import utc_now
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.interaction_feedback import FeedbackRating, InteractionFeedback
from recipe_assistant.models.message import ChatMessage


class FeedbackRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_message(self, message_id: int) -> ChatMessage | None:
        return self.session.get(ChatMessage, message_id)

    def get_trace(self, run_id: str) -> AgentRunTrace | None:
        return self.session.scalar(
            select(AgentRunTrace).where(AgentRunTrace.run_id == run_id)
        )

    def get_for_user_message(
        self, user_id: int, message_id: int
    ) -> InteractionFeedback | None:
        return self.session.scalar(
            select(InteractionFeedback).where(
                InteractionFeedback.user_id == user_id,
                InteractionFeedback.message_id == message_id,
            )
        )

    def create(
        self,
        *,
        user_id: int,
        run_id: str,
        message_id: int,
        rating: FeedbackRating,
        reason_tags: list[str],
        comment: str | None,
    ) -> InteractionFeedback:
        feedback = InteractionFeedback(
            user_id=user_id,
            run_id=run_id,
            message_id=message_id,
            rating=rating,
            reason_tags_json=list(reason_tags),
            comment=comment,
        )
        self.session.add(feedback)
        self.session.flush()
        return feedback

    def update(
        self,
        feedback: InteractionFeedback,
        *,
        rating: FeedbackRating,
        reason_tags: list[str],
        comment: str | None,
    ) -> InteractionFeedback:
        feedback.rating = rating
        feedback.reason_tags_json = list(reason_tags)
        feedback.comment = comment
        feedback.updated_at = utc_now()
        self.session.flush()
        return feedback
