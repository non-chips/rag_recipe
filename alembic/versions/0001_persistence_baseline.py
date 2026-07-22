"""Persistence baseline for users, chat, profiles, interactions and traces."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_persistence_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_accounts_username", "user_accounts", ["username"], unique=True
    )

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_sessions_public_id", "chat_sessions", ["public_id"], unique=True
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("preferred_cuisines_json", sa.JSON(), nullable=False),
        sa.Column("disliked_ingredients_json", sa.JSON(), nullable=False),
        sa.Column("allergens_json", sa.JSON(), nullable=False),
        sa.Column("available_appliances_json", sa.JSON(), nullable=False),
        sa.Column("default_servings", sa.Integer(), nullable=True),
        sa.Column("skill_level", sa.String(length=50), nullable=True),
        sa.Column("planning_goal", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "USER",
                "ASSISTANT",
                "SYSTEM",
                "TOOL",
                name="messagerole",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"])

    op.create_table(
        "recipe_interactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("recipe_id", sa.String(length=100), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "QUERY",
                "VIEW",
                "FAVORITE",
                "PLAN",
                "COOK",
                "CONSUME",
                "RATE",
                name="interactiontype",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("servings", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recipe_interactions_event_type", "recipe_interactions", ["event_type"])
    op.create_index("ix_recipe_interactions_recipe_id", "recipe_interactions", ["recipe_id"])
    op.create_index("ix_recipe_interactions_session_id", "recipe_interactions", ["session_id"])
    op.create_index("ix_recipe_interactions_user_id", "recipe_interactions", ["user_id"])

    op.create_table(
        "agent_run_traces",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("route", sa.String(length=50), nullable=False),
        sa.Column("original_input", sa.Text(), nullable=False),
        sa.Column("normalized_input", sa.Text(), nullable=False),
        sa.Column("events_json", sa.JSON(), nullable=False),
        sa.Column("tasks_json", sa.JSON(), nullable=False),
        sa.Column("artifacts_json", sa.JSON(), nullable=False),
        sa.Column("sources_json", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("token_usage_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_run_traces_run_id", "agent_run_traces", ["run_id"], unique=True
    )
    op.create_index("ix_agent_run_traces_session_id", "agent_run_traces", ["session_id"])
    op.create_index("ix_agent_run_traces_user_id", "agent_run_traces", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_traces_user_id", table_name="agent_run_traces")
    op.drop_index("ix_agent_run_traces_session_id", table_name="agent_run_traces")
    op.drop_index("ix_agent_run_traces_run_id", table_name="agent_run_traces")
    op.drop_table("agent_run_traces")
    op.drop_index("ix_recipe_interactions_user_id", table_name="recipe_interactions")
    op.drop_index("ix_recipe_interactions_session_id", table_name="recipe_interactions")
    op.drop_index("ix_recipe_interactions_recipe_id", table_name="recipe_interactions")
    op.drop_index("ix_recipe_interactions_event_type", table_name="recipe_interactions")
    op.drop_table("recipe_interactions")
    op.drop_index("ix_chat_messages_user_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_table("user_profiles")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_public_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_index("ix_user_accounts_username", table_name="user_accounts")
    op.drop_table("user_accounts")
