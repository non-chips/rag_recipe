"""SQLAlchemy repositories for SQLite-backed persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from recipe_assistant.core.database import utc_now
from recipe_assistant.models import (
    AgentRunTrace,
    ChatMessage,
    ChatSession,
    InteractionType,
    MessageRole,
    RecipeInteraction,
    UserAccount,
    UserProfile,
)


class SqlAlchemyUserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, username: str, password_hash: str, display_name: str | None = None
    ) -> UserAccount:
        user = UserAccount(
            username=username,
            display_name=display_name,
            password_hash=password_hash,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def get(self, user_id: int) -> UserAccount | None:
        return self.session.get(UserAccount, user_id)

    def get_by_username(self, username: str) -> UserAccount | None:
        return self.session.scalar(
            select(UserAccount).where(UserAccount.username == username)
        )


class SqlAlchemyChatRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_session(self, user_id: int, title: str | None = None) -> ChatSession:
        chat_session = ChatSession(user_id=user_id, title=title)
        self.session.add(chat_session)
        self.session.flush()
        return chat_session

    def get_session_by_public_id(self, public_id: str) -> ChatSession | None:
        return self.session.scalar(
            select(ChatSession).where(ChatSession.public_id == public_id)
        )

    def add_message(
        self,
        session_id: int,
        user_id: int,
        role: MessageRole,
        content: str,
    ) -> ChatMessage:
        chat_session = self.session.get(ChatSession, session_id)
        if chat_session is None or chat_session.user_id != user_id:
            raise ValueError("chat session does not belong to the supplied user")
        message = ChatMessage(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
        )
        self.session.add(message)
        chat_session.updated_at = utc_now()
        self.session.flush()
        return message

    def list_messages(self, session_id: int, limit: int = 100) -> list[ChatMessage]:
        statement = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
            .limit(limit)
        )
        return list(self.session.scalars(statement))


class SqlAlchemyProfileRepository:
    _FIELDS = {
        "preferred_cuisines_json",
        "disliked_ingredients_json",
        "allergens_json",
        "available_appliances_json",
        "default_servings",
        "skill_level",
        "planning_goal",
    }

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: int) -> UserProfile | None:
        return self.session.get(UserProfile, user_id)

    def upsert(self, user_id: int, **values: Any) -> UserProfile:
        unknown = set(values) - self._FIELDS
        if unknown:
            raise ValueError("unsupported profile fields: " + ", ".join(sorted(unknown)))
        profile = self.get(user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id)
            self.session.add(profile)
        for field_name, value in values.items():
            setattr(profile, field_name, value)
        self.session.flush()
        return profile


class SqlAlchemyInteractionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        *,
        user_id: int,
        recipe_id: str,
        event_type: InteractionType,
        session_id: int | None = None,
        servings: float | None = None,
        source: str | None = None,
        confidence: float | None = None,
        occurred_at: datetime | None = None,
    ) -> RecipeInteraction:
        interaction = RecipeInteraction(
            user_id=user_id,
            session_id=session_id,
            recipe_id=recipe_id,
            event_type=event_type,
            servings=servings,
            source=source,
            confidence=confidence,
        )
        if occurred_at is not None:
            interaction.occurred_at = occurred_at
        self.session.add(interaction)
        self.session.flush()
        return interaction

    def list_for_user(
        self,
        user_id: int,
        event_types: set[InteractionType] | None = None,
    ) -> list[RecipeInteraction]:
        statement = select(RecipeInteraction).where(RecipeInteraction.user_id == user_id)
        if event_types:
            statement = statement.where(RecipeInteraction.event_type.in_(event_types))
        statement = statement.order_by(
            RecipeInteraction.occurred_at, RecipeInteraction.id
        )
        return list(self.session.scalars(statement))


class SqlAlchemyTraceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        *,
        run_id: str,
        user_id: int,
        session_id: int | None,
        route: str,
        original_input: str,
        normalized_input: str,
        events: list[dict] | None = None,
        tasks: list[dict] | None = None,
        artifacts: list[dict] | None = None,
        sources: list[dict] | None = None,
        latency_ms: float | None = None,
        token_usage: dict | None = None,
    ) -> AgentRunTrace:
        trace = AgentRunTrace(
            run_id=run_id,
            user_id=user_id,
            session_id=session_id,
            route=route,
            original_input=original_input,
            normalized_input=normalized_input,
            events_json=list(events or []),
            tasks_json=list(tasks or []),
            artifacts_json=list(artifacts or []),
            sources_json=list(sources or []),
            latency_ms=latency_ms,
            token_usage_json=dict(token_usage or {}),
        )
        self.session.add(trace)
        self.session.flush()
        return trace

    def get_by_run_id(self, run_id: str) -> AgentRunTrace | None:
        return self.session.scalar(
            select(AgentRunTrace).where(AgentRunTrace.run_id == run_id)
        )
