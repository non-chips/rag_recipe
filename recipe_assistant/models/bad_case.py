"""Review-gated Bad Case candidate snapshot."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from recipe_assistant.core.database import Base, UTCDateTime, utc_now


class BadCaseCandidate(Base):
    __tablename__ = "bad_case_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    first_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_run_traces.run_id", ondelete="CASCADE")
    )
    latest_run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_run_traces.run_id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="PENDING_REVIEW", index=True)
    score: Mapped[float] = mapped_column(Float)
    normalized_request: Mapped[str] = mapped_column(Text)
    trigger_types_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    occurrence_count: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )
