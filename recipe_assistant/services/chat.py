"""Application service owning one complete chat request lifecycle."""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from recipe_assistant.agents.events import thaw_value
from recipe_assistant.agents.result import (
    ChatRequest,
    ChatServiceResult,
    HarnessOutcome,
    RunContext,
)
from recipe_assistant.core.database import session_scope
from recipe_assistant.models import MessageRole
from recipe_assistant.repositories.sqlite import (
    SqlAlchemyChatRepository,
    SqlAlchemyProfileRepository,
    SqlAlchemyTraceRepository,
)
from recipe_assistant.schemas.feedback import (
    BadCaseEvaluationRequest,
    ToneAnalysisRequest,
    ToneSignal,
)
from recipe_assistant.services.bad_case import BadCaseService
from recipe_assistant.services.memory import MemoryService
from recipe_assistant.services.profile import ProfileService
from recipe_assistant.services.tone_analysis import ToneAnalysisService
from recipe_assistant.services.trace import TraceService


logger = logging.getLogger(__name__)


class ChatHarness(Protocol):
    @staticmethod
    def normalize_input(text: str) -> str: ...

    def run(self, context: RunContext) -> HarnessOutcome: ...


class ChatService:
    """Load context, execute once, and persist final user-visible output."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        harness: ChatHarness,
        tone_analysis_service: ToneAnalysisService | None = None,
        bad_case_service: BadCaseService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.harness = harness
        self.tone_analysis_service = tone_analysis_service or ToneAnalysisService()
        self.bad_case_service = bad_case_service or BadCaseService(session_factory)

    def run(self, request: ChatRequest) -> ChatServiceResult:
        normalized_input = self.harness.normalize_input(request.message)

        with session_scope(self.session_factory) as session:
            memory = MemoryService(SqlAlchemyChatRepository(session))
            chat_session = memory.create_or_restore_session(
                user_id=request.user_id,
                public_id=request.session_public_id,
                title=normalized_input[:80] or None,
            )
            history = memory.load_history(chat_session.id)
            profile = ProfileService(
                SqlAlchemyProfileRepository(session)
            ).load_snapshot(request.user_id)
            user_message = memory.save_message(
                session_id=chat_session.id,
                user_id=request.user_id,
                role=MessageRole.USER,
                content=request.message,
            )
            context = RunContext(
                user_id=request.user_id,
                session_id=chat_session.id,
                session_public_id=chat_session.public_id,
                original_input=request.message,
                normalized_input=normalized_input,
                profile=profile,
                history=history,
            )
            user_message_id = user_message.id

        tone_signal = self._analyze_tone(request.message, context)
        outcome = self.harness.run(context)
        self._record_tone_trace_event(outcome, tone_signal)

        with session_scope(self.session_factory) as session:
            memory = MemoryService(SqlAlchemyChatRepository(session))
            assistant_message = memory.save_message(
                session_id=context.session_id,
                user_id=context.user_id,
                role=MessageRole.ASSISTANT,
                content=outcome.result.final_text,
            )
            TraceService(SqlAlchemyTraceRepository(session)).save(outcome)
            assistant_message_id = assistant_message.id

        self._submit_bad_case_signals(context, outcome, tone_signal)

        return ChatServiceResult(
            run_id=context.run_id,
            session_public_id=context.session_public_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            route=outcome.route_decision.route,
            content=outcome.result.final_text,
            outcome=outcome,
        )

    def _analyze_tone(self, message: str, context: RunContext) -> ToneSignal:
        """Analyze the current turn without allowing observability to block chat."""

        recent_user_messages = tuple(
            item.content
            for item in context.history
            if item.role is MessageRole.USER
        )
        try:
            return self.tone_analysis_service.analyze(
                ToneAnalysisRequest(
                    current_text=message,
                    recent_user_messages=recent_user_messages,
                )
            )
        except Exception:
            logger.exception(
                "Tone analysis failed",
                extra={
                    "chat_user_id": context.user_id,
                    "chat_session_id": context.session_public_id,
                    "chat_run_id": context.run_id,
                },
            )
            return ToneSignal(
                possible_frustration=0.0,
                possible_impatience=0.0,
                possible_dissatisfaction=0.0,
                repeated_request=False,
                repeated_constraint=False,
                requested_retry=False,
                explicit_error_reported=False,
                evidence=("tone analysis unavailable",),
                confidence=0.0,
            )

    @staticmethod
    def _record_tone_trace_event(
        outcome: HarnessOutcome,
        tone_signal: ToneSignal,
    ) -> None:
        outcome.result.events.insert(
            0,
            {
                "event_type": "TONE_ANALYZED",
                "actor": "tone_analysis_service",
                "message": "interaction-level weak signals analyzed",
                "metadata": tone_signal.model_dump(mode="json"),
            }
        )

    def _submit_bad_case_signals(
        self,
        context: RunContext,
        outcome: HarnessOutcome,
        tone_signal: ToneSignal,
    ) -> None:
        """Persist tone signals and merge them with runtime quality evidence."""

        candidates = [
            event
            for event in outcome.result.events
            if event.get("event_type") == "BAD_CASE_CANDIDATE"
        ]
        metadata = (candidates[-1].get("metadata") or {}) if candidates else {}
        try:
            self.bad_case_service.evaluate(
                BadCaseEvaluationRequest(
                    user_id=context.user_id,
                    run_id=context.run_id,
                    session_id=context.session_id,
                    normalized_request=context.normalized_input,
                    tone_signal=tone_signal,
                    hard_constraint_violations=tuple(
                        str(item)
                        for item in metadata.get(
                            "hard_constraint_violations",
                            (),
                        )
                    ),
                    trace_snapshot=thaw_value(
                        {
                            "route": outcome.route_decision.route.value,
                            "events": outcome.result.events,
                        }
                    ),
                )
            )
        except Exception:
            logger.exception(
                "Bad-case signal submission failed",
                extra={
                    "chat_user_id": context.user_id,
                    "chat_session_id": context.session_public_id,
                    "chat_run_id": context.run_id,
                },
            )
            # Observability must never replace the persisted user-facing answer.
            return
