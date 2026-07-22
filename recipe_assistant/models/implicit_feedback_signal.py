"""Persisted weak feedback evidence for one completed agent run."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from recipe_assistant.core.database import Base, UTCDateTime, utc_now


class ImplicitFeedbackSignal(Base):
    __tablename__ = "implicit_feedback_signals"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "signal_type", name="uq_implicit_signal_run_type"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_run_traces.run_id", ondelete="CASCADE"), index=True
    )
    signal_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default="SIGNAL")
    probability: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )
