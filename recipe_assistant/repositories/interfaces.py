"""Repository protocols used by future service-layer code."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

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


class UserRepository(Protocol):
    def create(
        self, username: str, password_hash: str, display_name: str | None = None
    ) -> UserAccount: ...

    def get(self, user_id: int) -> UserAccount | None: ...

    def get_by_username(self, username: str) -> UserAccount | None: ...


class ChatRepository(Protocol):
    def create_session(self, user_id: int, title: str | None = None) -> ChatSession: ...

    def get_session_by_public_id(self, public_id: str) -> ChatSession | None: ...

    def add_message(
        self, session_id: int, user_id: int, role: MessageRole, content: str
    ) -> ChatMessage: ...

    def list_messages(self, session_id: int, limit: int = 100) -> list[ChatMessage]: ...


class ProfileRepository(Protocol):
    def get(self, user_id: int) -> UserProfile | None: ...

    def upsert(self, user_id: int, **values: Any) -> UserProfile: ...


class InteractionRepository(Protocol):
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
    ) -> RecipeInteraction: ...

    def list_for_user(
        self,
        user_id: int,
        event_types: set[InteractionType] | None = None,
    ) -> list[RecipeInteraction]: ...


class TraceRepository(Protocol):
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
    ) -> AgentRunTrace: ...

    def get_by_run_id(self, run_id: str) -> AgentRunTrace | None: ...
