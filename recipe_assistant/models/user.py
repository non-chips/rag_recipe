"""User account and explicit long-term profile entities."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from recipe_assistant.core.database import Base, UTCDateTime, utc_now


class UserAccount(Base):
    __tablename__ = "user_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    preferred_cuisines_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    disliked_ingredients_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    allergens_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    available_appliances_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_servings: Mapped[int | None] = mapped_column(nullable=True)
    skill_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    planning_goal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )
