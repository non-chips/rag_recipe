"""Public DTOs for explicit feedback."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from recipe_assistant.models.interaction_feedback import FeedbackRating


class FeedbackReasonTag(str, Enum):
    INCORRECT = "INCORRECT"
    IRRELEVANT = "IRRELEVANT"
    UNSAFE = "UNSAFE"
    CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"
    OUTDATED = "OUTDATED"
    UNCLEAR = "UNCLEAR"
    TOO_VERBOSE = "TOO_VERBOSE"
    TOO_BRIEF = "TOO_BRIEF"
    OTHER = "OTHER"


class AnswerFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=64)
    message_id: int = Field(gt=0)
    rating: FeedbackRating
    reason_tags: list[FeedbackReasonTag] = Field(default_factory=list, max_length=10)
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("reason_tags")
    @classmethod
    def reason_tags_must_be_unique(
        cls, value: list[FeedbackReasonTag]
    ) -> list[FeedbackReasonTag]:
        if len(value) != len(set(value)):
            raise ValueError("reason_tags must not contain duplicates")
        return value

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AnswerFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    run_id: str
    message_id: int
    rating: FeedbackRating
    reason_tags: list[FeedbackReasonTag]
    comment: str | None
    created_at: datetime
    updated_at: datetime


class RecipePreferenceEventType(str, Enum):
    """Reserved recipe preference contract; never used for answer feedback."""

    FAVORITE_RECIPE = "FAVORITE_RECIPE"
    LIKE_RECIPE = "LIKE_RECIPE"
    DISLIKE_RECIPE = "DISLIKE_RECIPE"


class RecipePreferenceEventRequest(BaseModel):
    """Independent interface reserved for a future recipe-event endpoint."""

    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(min_length=1, max_length=100)
    event_type: RecipePreferenceEventType
    session_id: str | None = Field(default=None, max_length=32)
