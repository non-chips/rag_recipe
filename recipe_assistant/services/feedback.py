"""Application service for explicit answer feedback."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from recipe_assistant.core.database import session_scope
from recipe_assistant.models.interaction_feedback import InteractionFeedback
from recipe_assistant.models.message import MessageRole
from recipe_assistant.repositories.feedback_repository import FeedbackRepository
from recipe_assistant.schemas.feedback import (
    AnswerFeedbackRequest,
    AnswerFeedbackResponse,
    FeedbackReasonTag,
)


class FeedbackService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def submit(
        self, user_id: int, request: AnswerFeedbackRequest
    ) -> AnswerFeedbackResponse:
        with session_scope(self.session_factory) as session:
            repository = FeedbackRepository(session)
            self._validate_targets(repository, user_id, request)
            feedback = repository.get_for_user_message(user_id, request.message_id)
            reason_tags = [tag.value for tag in request.reason_tags]
            if feedback is None:
                feedback = repository.create(
                    user_id=user_id,
                    run_id=request.run_id,
                    message_id=request.message_id,
                    rating=request.rating,
                    reason_tags=reason_tags,
                    comment=request.comment,
                )
            else:
                if feedback.run_id != request.run_id:
                    raise ValueError("message feedback is already bound to another run")
                if not self._same_payload(feedback, request):
                    feedback = repository.update(
                        feedback,
                        rating=request.rating,
                        reason_tags=reason_tags,
                        comment=request.comment,
                    )
            return self._response(feedback)

    def get(self, user_id: int, message_id: int) -> AnswerFeedbackResponse:
        with session_scope(self.session_factory) as session:
            repository = FeedbackRepository(session)
            message = repository.get_message(message_id)
            if message is None:
                raise LookupError("assistant message was not found")
            if message.user_id != user_id:
                raise PermissionError("assistant message does not belong to this user")
            feedback = repository.get_for_user_message(user_id, message_id)
            if feedback is None:
                raise LookupError("feedback was not found")
            return self._response(feedback)

    @staticmethod
    def _validate_targets(
        repository: FeedbackRepository,
        user_id: int,
        request: AnswerFeedbackRequest,
    ) -> None:
        message = repository.get_message(request.message_id)
        if message is None:
            raise LookupError("assistant message was not found")
        if message.user_id != user_id:
            raise PermissionError("assistant message does not belong to this user")
        if message.role is not MessageRole.ASSISTANT:
            raise ValueError("feedback can only target an assistant message")

        trace = repository.get_trace(request.run_id)
        if trace is None:
            raise LookupError("agent run was not found")
        if trace.user_id != user_id:
            raise PermissionError("agent run does not belong to this user")
        if trace.session_id is None or trace.session_id != message.session_id:
            raise ValueError("message_id and run_id do not belong to the same session")

    @staticmethod
    def _same_payload(
        feedback: InteractionFeedback, request: AnswerFeedbackRequest
    ) -> bool:
        return (
            feedback.rating == request.rating
            and feedback.reason_tags_json == [tag.value for tag in request.reason_tags]
            and feedback.comment == request.comment
        )

    @staticmethod
    def _response(feedback: InteractionFeedback) -> AnswerFeedbackResponse:
        return AnswerFeedbackResponse(
            id=feedback.id,
            user_id=feedback.user_id,
            run_id=feedback.run_id,
            message_id=feedback.message_id,
            rating=feedback.rating,
            reason_tags=[FeedbackReasonTag(tag) for tag in feedback.reason_tags_json],
            comment=feedback.comment,
            created_at=feedback.created_at,
            updated_at=feedback.updated_at,
        )
