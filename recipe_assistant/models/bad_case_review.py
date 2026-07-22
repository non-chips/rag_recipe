"""Append-only developer review audit for Bad Case state changes."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DDL, ForeignKey, JSON, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from recipe_assistant.core.database import Base, UTCDateTime, utc_now


class BadCaseReview(Base):
    __tablename__ = "bad_case_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bad_case_id: Mapped[int] = mapped_column(
        ForeignKey("bad_case_candidates.id", ondelete="RESTRICT"), index=True
    )
    reviewer_id: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str] = mapped_column(String(20))
    from_status: Mapped[str] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    automatic_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    automatic_suggestion_json: Mapped[dict] = mapped_column(JSON, default=dict)
    final_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    final_root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_note: Mapped[str] = mapped_column(Text)
    assignee: Mapped[str | None] = mapped_column(String(100), nullable=True)
    merge_target_id: Mapped[int | None] = mapped_column(
        ForeignKey("bad_case_candidates.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


event.listen(
    BadCaseReview.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_bad_case_reviews_no_update "
        "BEFORE UPDATE ON bad_case_reviews BEGIN "
        "SELECT RAISE(ABORT, 'Bad Case review audit is append-only'); END"
    ).execute_if(dialect="sqlite"),
)
event.listen(
    BadCaseReview.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_bad_case_reviews_no_delete "
        "BEFORE DELETE ON bad_case_reviews BEGIN "
        "SELECT RAISE(ABORT, 'Bad Case review audit is append-only'); END"
    ).execute_if(dialect="sqlite"),
)
