"""Append-only resolution evidence and developer-confirmed regression drafts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from recipe_assistant.core.database import Base, UTCDateTime, utc_now


class RegressionSampleDraft(Base):
    __tablename__ = "regression_sample_drafts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bad_case_id: Mapped[int] = mapped_column(
        ForeignKey("bad_case_candidates.id", ondelete="RESTRICT"),
        unique=True,
        index=True,
    )
    input_text: Mapped[str] = mapped_column(Text)
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_constraints_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    developer_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class BadCaseResolution(Base):
    __tablename__ = "bad_case_resolutions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bad_case_id: Mapped[int] = mapped_column(
        ForeignKey("bad_case_candidates.id", ondelete="RESTRICT"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(100), index=True)
    fix_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    issue_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    regression_test_reference: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    evidence_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    metrics_json: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
