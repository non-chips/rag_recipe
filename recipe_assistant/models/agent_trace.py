"""Persisted agent run trace entity."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from recipe_assistant.core.database import Base, UTCDateTime, utc_now


class AgentRunTrace(Base):
    __tablename__ = "agent_run_traces"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    route: Mapped[str] = mapped_column(String(50))
    original_input: Mapped[str] = mapped_column(Text)
    normalized_input: Mapped[str] = mapped_column(Text)
    events_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    tasks_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    artifacts_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    sources_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_usage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
