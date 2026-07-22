"""Add append-only Bad Case review, regression draft and resolution records."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_bad_case_review"
down_revision: str | None = "0003_bad_case_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bad_case_reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bad_case_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=False),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("automatic_category", sa.String(length=50), nullable=True),
        sa.Column("automatic_suggestion_json", sa.JSON(), nullable=False),
        sa.Column("final_category", sa.String(length=50), nullable=True),
        sa.Column("final_root_cause", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=False),
        sa.Column("assignee", sa.String(length=100), nullable=True),
        sa.Column("merge_target_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["bad_case_id"], ["bad_case_candidates.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["merge_target_id"], ["bad_case_candidates.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bad_case_reviews_bad_case_id", "bad_case_reviews", ["bad_case_id"]
    )
    op.create_index(
        "ix_bad_case_reviews_reviewer_id", "bad_case_reviews", ["reviewer_id"]
    )
    op.execute(
        "CREATE TRIGGER trg_bad_case_reviews_no_update "
        "BEFORE UPDATE ON bad_case_reviews BEGIN "
        "SELECT RAISE(ABORT, 'Bad Case review audit is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_bad_case_reviews_no_delete "
        "BEFORE DELETE ON bad_case_reviews BEGIN "
        "SELECT RAISE(ABORT, 'Bad Case review audit is append-only'); END"
    )

    op.create_table(
        "regression_sample_drafts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bad_case_id", sa.Integer(), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text(), nullable=True),
        sa.Column("expected_constraints_json", sa.JSON(), nullable=False),
        sa.Column("developer_confirmed", sa.Boolean(), nullable=False),
        sa.Column("confirmed_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["bad_case_id"], ["bad_case_candidates.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_regression_sample_drafts_bad_case_id",
        "regression_sample_drafts",
        ["bad_case_id"],
        unique=True,
    )

    op.create_table(
        "bad_case_resolutions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bad_case_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("fix_reference", sa.String(length=500), nullable=True),
        sa.Column("issue_reference", sa.String(length=500), nullable=True),
        sa.Column("regression_test_reference", sa.String(length=500), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["bad_case_id"], ["bad_case_candidates.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bad_case_resolutions_actor_id", "bad_case_resolutions", ["actor_id"]
    )
    op.create_index(
        "ix_bad_case_resolutions_bad_case_id",
        "bad_case_resolutions",
        ["bad_case_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bad_case_resolutions_bad_case_id", table_name="bad_case_resolutions"
    )
    op.drop_index(
        "ix_bad_case_resolutions_actor_id", table_name="bad_case_resolutions"
    )
    op.drop_table("bad_case_resolutions")
    op.drop_index(
        "ix_regression_sample_drafts_bad_case_id",
        table_name="regression_sample_drafts",
    )
    op.drop_table("regression_sample_drafts")
    op.execute("DROP TRIGGER IF EXISTS trg_bad_case_reviews_no_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_bad_case_reviews_no_update")
    op.drop_index("ix_bad_case_reviews_reviewer_id", table_name="bad_case_reviews")
    op.drop_index("ix_bad_case_reviews_bad_case_id", table_name="bad_case_reviews")
    op.drop_table("bad_case_reviews")
