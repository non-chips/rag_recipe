"""Add explicit assistant-answer feedback."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_interaction_feedback"
down_revision: str | None = "0001_persistence_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interaction_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column(
            "rating",
            sa.Enum(
                "LIKE",
                "DISLIKE",
                name="feedbackrating",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("reason_tags_json", sa.JSON(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["agent_run_traces.run_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "message_id", name="uq_interaction_feedback_user_message"
        ),
    )
    op.create_index(
        "ix_interaction_feedback_message_id",
        "interaction_feedback",
        ["message_id"],
    )
    op.create_index(
        "ix_interaction_feedback_run_id", "interaction_feedback", ["run_id"]
    )
    op.create_index(
        "ix_interaction_feedback_user_id", "interaction_feedback", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_interaction_feedback_user_id", table_name="interaction_feedback")
    op.drop_index("ix_interaction_feedback_run_id", table_name="interaction_feedback")
    op.drop_index(
        "ix_interaction_feedback_message_id", table_name="interaction_feedback"
    )
    op.drop_table("interaction_feedback")
