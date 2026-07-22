from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from recipe_assistant.core.database import create_database_engine, create_session_factory, session_scope
from recipe_assistant.models import InteractionType, MessageRole
from recipe_assistant.repositories import (
    SqlAlchemyChatRepository,
    SqlAlchemyInteractionRepository,
    SqlAlchemyProfileRepository,
    SqlAlchemyTraceRepository,
    SqlAlchemyUserRepository,
)


def _upgrade_database(database_url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def test_alembic_database_persists_repository_data_across_sessions(tmp_path) -> None:
    database_path = tmp_path / "persistence.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    _upgrade_database(database_url)

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    expected_tables = {
        "user_accounts",
        "chat_sessions",
        "chat_messages",
        "user_profiles",
        "recipe_interactions",
        "agent_run_traces",
        "alembic_version",
    }
    assert expected_tables.issubset(set(inspect(engine).get_table_names()))

    with session_scope(factory) as session:
        user = SqlAlchemyUserRepository(session).create("persistent-user", "hash")
        chat = SqlAlchemyChatRepository(session).create_session(user.id, "测试会话")
        SqlAlchemyChatRepository(session).add_message(
            chat.id, user.id, MessageRole.USER, "清蒸鱼怎么做"
        )
        SqlAlchemyProfileRepository(session).upsert(
            user.id,
            disliked_ingredients_json=["香菜"],
            available_appliances_json=["蒸锅"],
        )
        SqlAlchemyInteractionRepository(session).add(
            user_id=user.id,
            session_id=chat.id,
            recipe_id="recipe-fish",
            event_type=InteractionType.PLAN,
            source="user_plan",
        )
        SqlAlchemyTraceRepository(session).add(
            run_id="persistent-run",
            user_id=user.id,
            session_id=chat.id,
            route="RECIPE_KNOWLEDGE",
            original_input="清蒸鱼怎么做",
            normalized_input="清蒸鱼怎么做",
            sources=[{"recipe_id": "recipe-fish"}],
        )
        user_id = user.id
        public_id = chat.public_id

    with session_scope(factory) as session:
        user = SqlAlchemyUserRepository(session).get(user_id)
        chat = SqlAlchemyChatRepository(session).get_session_by_public_id(public_id)
        profile = SqlAlchemyProfileRepository(session).get(user_id)
        interactions = SqlAlchemyInteractionRepository(session).list_for_user(user_id)
        trace = SqlAlchemyTraceRepository(session).get_by_run_id("persistent-run")

        assert user is not None and user.username == "persistent-user"
        assert chat is not None
        assert SqlAlchemyChatRepository(session).list_messages(chat.id)[0].content == "清蒸鱼怎么做"
        assert profile is not None and profile.disliked_ingredients_json == ["香菜"]
        assert interactions[0].event_type is InteractionType.PLAN
        assert trace is not None and trace.sources_json == [{"recipe_id": "recipe-fish"}]
        assert trace.created_at.utcoffset() is not None

    engine.dispose()
