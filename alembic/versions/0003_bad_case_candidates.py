"""Add implicit feedback signals and review-gated Bad Case candidates."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_bad_case_candidates"
down_revision: str | None = "0002_interaction_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "implicit_feedback_signals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("signal_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run_traces.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "signal_type", name="uq_implicit_signal_run_type"),
    )
    op.create_index(
        "ix_implicit_feedback_signals_run_id", "implicit_feedback_signals", ["run_id"]
    )
    op.create_index(
        "ix_implicit_feedback_signals_session_id",
        "implicit_feedback_signals",
        ["session_id"],
    )
    op.create_index(
        "ix_implicit_feedback_signals_signal_type",
        "implicit_feedback_signals",
        ["signal_type"],
    )
    op.create_index(
        "ix_implicit_feedback_signals_user_id", "implicit_feedback_signals", ["user_id"]
    )

    op.create_table(
        "bad_case_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("first_run_id", sa.String(length=64), nullable=False),
        sa.Column("latest_run_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("normalized_request", sa.Text(), nullable=False),
        sa.Column("trigger_types_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["first_run_id"], ["agent_run_traces.run_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["latest_run_id"], ["agent_run_traces.run_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bad_case_candidates_fingerprint",
        "bad_case_candidates",
        ["fingerprint"],
        unique=True,
    )
    op.create_index(
        "ix_bad_case_candidates_latest_run_id", "bad_case_candidates", ["latest_run_id"]
    )
    op.create_index(
        "ix_bad_case_candidates_session_id", "bad_case_candidates", ["session_id"]
    )
    op.create_index("ix_bad_case_candidates_status", "bad_case_candidates", ["status"])
    op.create_index(
        "ix_bad_case_candidates_user_id", "bad_case_candidates", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_bad_case_candidates_user_id", table_name="bad_case_candidates")
    op.drop_index("ix_bad_case_candidates_status", table_name="bad_case_candidates")
    op.drop_index("ix_bad_case_candidates_session_id", table_name="bad_case_candidates")
    op.drop_index("ix_bad_case_candidates_latest_run_id", table_name="bad_case_candidates")
    op.drop_index("ix_bad_case_candidates_fingerprint", table_name="bad_case_candidates")
    op.drop_table("bad_case_candidates")
    op.drop_index(
        "ix_implicit_feedback_signals_user_id", table_name="implicit_feedback_signals"
    )
    op.drop_index(
        "ix_implicit_feedback_signals_signal_type",
        table_name="implicit_feedback_signals",
    )
    op.drop_index(
        "ix_implicit_feedback_signals_session_id",
        table_name="implicit_feedback_signals",
    )
    op.drop_index(
        "ix_implicit_feedback_signals_run_id", table_name="implicit_feedback_signals"
    )
    op.drop_table("implicit_feedback_signals")
