"""Explicit user feedback for an assistant answer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from recipe_assistant.core.database import Base, UTCDateTime, utc_now


class FeedbackRating(str, Enum):
    LIKE = "LIKE"
    DISLIKE = "DISLIKE"


class InteractionFeedback(Base):
    """One recoverable answer-feedback record per user and assistant message."""

    __tablename__ = "interaction_feedback"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "message_id", name="uq_interaction_feedback_user_message"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_run_traces.run_id", ondelete="CASCADE"), index=True
    )
    rating: Mapped[FeedbackRating] = mapped_column(
        SqlEnum(FeedbackRating, native_enum=False, length=16, validate_strings=True)
    )
    reason_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )
