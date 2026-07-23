"""Application service owning one complete chat request lifecycle."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

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
from recipe_assistant.services.memory import MemoryService
from recipe_assistant.services.profile import ProfileService
from recipe_assistant.services.trace import TraceService


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
    ) -> None:
        self.session_factory = session_factory
        self.harness = harness

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

        outcome = self.harness.run(context)

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

        return ChatServiceResult(
            run_id=context.run_id,
            session_public_id=context.session_public_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            route=outcome.route_decision.route,
            content=outcome.result.final_text,
            outcome=outcome,
        )
