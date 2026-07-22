"""User account API DTOs."""

from datetime import datetime

from pydantic import Field

from recipe_assistant.schemas.api.common import ApiSchema


class UserAccountCreate(ApiSchema):
    username: str = Field(min_length=1, max_length=100)
    display_name: str | None = Field(default=None, max_length=100)
    password_hash: str = Field(min_length=1, max_length=255)


class UserAccountRead(ApiSchema):
    id: int
    username: str
    display_name: str | None
    created_at: datetime
