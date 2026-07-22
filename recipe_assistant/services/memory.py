"""Session and short-term message persistence service."""

from __future__ import annotations

from recipe_assistant.agents.result import MemoryMessage
from recipe_assistant.models import ChatMessage, ChatSession, MessageRole
from recipe_assistant.repositories.interfaces import ChatRepository


class MemoryService:
    def __init__(self, repository: ChatRepository) -> None:
        self.repository = repository

    def create_or_restore_session(
        self,
        *,
        user_id: int,
        public_id: str | None,
        title: str | None = None,
    ) -> ChatSession:
        if public_id:
            existing = self.repository.get_session_by_public_id(public_id)
            if existing is None:
                raise ValueError("chat session was not found")
            if existing.user_id != user_id:
                raise PermissionError("chat session does not belong to the user")
            return existing
        return self.repository.create_session(user_id=user_id, title=title)

    def load_history(self, session_id: int, *, limit: int = 20) -> list[MemoryMessage]:
        messages = self.repository.list_messages(session_id, limit=10_000)[-limit:]
        return [
            MemoryMessage(
                role=message.role,
                content=message.content,
                created_at=message.created_at,
            )
            for message in messages
        ]

    def save_message(
        self,
        *,
        session_id: int,
        user_id: int,
        role: MessageRole,
        content: str,
    ) -> ChatMessage:
        return self.repository.add_message(session_id, user_id, role, content)
