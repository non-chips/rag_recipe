"""Chat session and message API DTOs."""

from datetime import datetime

from pydantic import Field

from recipe_assistant.models.message import MessageRole
from recipe_assistant.schemas.api.common import ApiSchema


class ChatSessionCreate(ApiSchema):
    title: str | None = Field(default=None, max_length=200)


class ChatSessionRead(ApiSchema):
    public_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class ChatMessageCreate(ApiSchema):
    role: MessageRole
    content: str = Field(min_length=1)


class ChatMessageRead(ApiSchema):
    id: int
    role: MessageRole
    content: str
    created_at: datetime
