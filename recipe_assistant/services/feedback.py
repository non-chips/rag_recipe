"""Application service for explicit answer feedback."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from recipe_assistant.core.database import session_scope
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.interaction_feedback import InteractionFeedback
from recipe_assistant.models.message import ChatMessage, MessageRole
from recipe_assistant.repositories.feedback_repository import FeedbackRepository
from recipe_assistant.schemas.feedback import (
    AnswerFeedbackRequest,
    AnswerFeedbackResponse,
    BadCaseEvaluationRequest,
    FeedbackReasonTag,
    ToneSignal,
)
from recipe_assistant.services.bad_case import BadCaseService


class FeedbackService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        bad_case_service: BadCaseService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.bad_case_service = bad_case_service or BadCaseService(session_factory)

    def submit(
        self, user_id: int, request: AnswerFeedbackRequest
    ) -> AnswerFeedbackResponse:
        evaluation_request: BadCaseEvaluationRequest | None = None
        with session_scope(self.session_factory) as session:
            repository = FeedbackRepository(session)
            message, trace = self._validate_targets(repository, user_id, request)
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
            response = self._response(feedback)
            if request.rating.value == "DISLIKE":
                evaluation_request = self._bad_case_request(
                    user_id=user_id,
                    request=request,
                    trace=trace,
                    feedback_id=response.id,
                    assistant_answer=message.content,
                )
        if evaluation_request is not None:
            self.bad_case_service.evaluate(evaluation_request)
        return response

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
    ) -> tuple[ChatMessage, AgentRunTrace]:
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
        return message, trace

    @staticmethod
    def _bad_case_request(
        *,
        user_id: int,
        request: AnswerFeedbackRequest,
        trace: AgentRunTrace,
        feedback_id: int,
        assistant_answer: str,
    ) -> BadCaseEvaluationRequest:
        return BadCaseEvaluationRequest(
            user_id=user_id,
            run_id=trace.run_id,
            session_id=int(trace.session_id),
            normalized_request=trace.normalized_input or trace.original_input,
            tone_signal=ToneSignal(
                possible_frustration=0.0,
                possible_impatience=0.0,
                possible_dissatisfaction=0.0,
                repeated_request=False,
                repeated_constraint=False,
                requested_retry=False,
                explicit_error_reported=False,
                evidence=("explicit answer dislike",),
                confidence=1.0,
            ),
            explicit_rating=request.rating,
            trace_snapshot={
                "route": trace.route,
                "original_input": trace.original_input,
                "normalized_input": trace.normalized_input,
                "events": list(trace.events_json or []),
                "tasks": list(trace.tasks_json or []),
                "artifacts": list(trace.artifacts_json or []),
                "sources": list(trace.sources_json or []),
                "latency_ms": trace.latency_ms,
                "token_usage": dict(trace.token_usage_json or {}),
                "created_at": trace.created_at.isoformat(),
            },
            feedback_snapshot={
                "feedback_id": feedback_id,
                "message_id": request.message_id,
                "rating": request.rating.value,
                "reason_tags": [tag.value for tag in request.reason_tags],
                "comment": request.comment,
                "assistant_answer": assistant_answer,
            },
        )

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
