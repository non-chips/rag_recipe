"""Explicitly typed recipe interaction entity."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from recipe_assistant.core.database import Base, UTCDateTime, utc_now


class InteractionType(str, Enum):
    QUERY = "QUERY"
    VIEW = "VIEW"
    FAVORITE = "FAVORITE"
    PLAN = "PLAN"
    COOK = "COOK"
    CONSUME = "CONSUME"
    RATE = "RATE"


class RecipeInteraction(Base):
    __tablename__ = "recipe_interactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recipe_id: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[InteractionType] = mapped_column(
        SqlEnum(InteractionType, native_enum=False, length=16, validate_strings=True),
        index=True,
    )
    servings: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
