from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import StatementError

from recipe_assistant.core.database import (
    Base,
    create_database_engine,
    create_session_factory,
    session_scope,
)
from recipe_assistant.models import (
    InteractionType,
    MessageRole,
    RecipeInteraction,
    UserAccount,
)
from recipe_assistant.repositories import (
    SqlAlchemyChatRepository,
    SqlAlchemyInteractionRepository,
    SqlAlchemyProfileRepository,
    SqlAlchemyTraceRepository,
    SqlAlchemyUserRepository,
)
from recipe_assistant.schemas.api import AgentRunTraceRead, UserAccountRead, UserProfileRead


@pytest.fixture
def session_factory():
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    yield factory
    engine.dispose()


def test_repositories_flush_without_owning_the_transaction(session_factory) -> None:
    session = session_factory()
    user = SqlAlchemyUserRepository(session).create("rollback-user", "hash")
    assert user.id is not None

    session.rollback()
    assert session.scalar(select(func.count()).select_from(UserAccount)) == 0
    session.close()


def test_session_scope_commits_and_api_dto_hides_entity_secrets(session_factory) -> None:
    with session_scope(session_factory) as session:
        user = SqlAlchemyUserRepository(session).create(
            "alice", "secret-hash", display_name="Alice"
        )
        user_id = user.id

    with session_scope(session_factory) as session:
        stored = SqlAlchemyUserRepository(session).get(user_id)
        assert stored is not None
        dto = UserAccountRead.model_validate(stored)
        assert dto.username == "alice"
        assert "password_hash" not in dto.model_dump()
        assert dto.created_at.utcoffset() is not None


def test_chat_profile_interactions_and_trace_keep_explicit_types(session_factory) -> None:
    with session_scope(session_factory) as session:
        user = SqlAlchemyUserRepository(session).create("bob", "hash")
        chat_repository = SqlAlchemyChatRepository(session)
        chat = chat_repository.create_session(user.id, "晚餐")
        chat_repository.add_message(
            chat.id, user.id, MessageRole.USER, "番茄炒蛋怎么做"
        )

        profile = SqlAlchemyProfileRepository(session).upsert(
            user.id,
            preferred_cuisines_json=["川菜"],
            allergens_json=["花生"],
            default_servings=2,
        )
        profile_dto = UserProfileRead.model_validate(profile)
        assert profile_dto.preferred_cuisines == ["川菜"]
        assert profile_dto.allergens == ["花生"]

        interactions = SqlAlchemyInteractionRepository(session)
        query = interactions.add(
            user_id=user.id,
            session_id=chat.id,
            recipe_id="recipe-1",
            event_type=InteractionType.QUERY,
            source="chat",
        )
        consumed = interactions.add(
            user_id=user.id,
            session_id=chat.id,
            recipe_id="recipe-1",
            event_type=InteractionType.CONSUME,
            servings=1.0,
            source="user_confirmation",
        )
        assert query.event_type is InteractionType.QUERY
        assert consumed.event_type is InteractionType.CONSUME

        trace = SqlAlchemyTraceRepository(session).add(
            run_id="run-1",
            user_id=user.id,
            session_id=chat.id,
            route="RECIPE_KNOWLEDGE",
            original_input=" 番茄炒蛋怎么做 ",
            normalized_input="番茄炒蛋怎么做",
            events=[{"type": "route"}],
            latency_ms=12.5,
            token_usage={"total": 10},
        )
        assert trace.events_json == [{"type": "route"}]
        trace_dto = AgentRunTraceRead.model_validate(trace)
        assert trace_dto.events == [{"type": "route"}]
        assert trace_dto.token_usage == {"total": 10}

    with session_scope(session_factory) as session:
        stored_types = {
            item.event_type
            for item in SqlAlchemyInteractionRepository(session).list_for_user(user.id)
        }
        assert stored_types == {InteractionType.QUERY, InteractionType.CONSUME}
        assert len(SqlAlchemyChatRepository(session).list_messages(chat.id)) == 1
        assert SqlAlchemyTraceRepository(session).get_by_run_id("run-1") is not None


def test_naive_datetime_is_rejected(session_factory) -> None:
    with pytest.raises(StatementError, match="timezone"):
        with session_scope(session_factory) as session:
            user = SqlAlchemyUserRepository(session).create("utc-user", "hash")
            SqlAlchemyInteractionRepository(session).add(
                user_id=user.id,
                recipe_id="recipe-utc",
                event_type=InteractionType.PLAN,
                occurred_at=datetime(2026, 1, 1, 12, 0),
            )


def test_interaction_filter_does_not_treat_query_as_consumption(session_factory) -> None:
    with session_scope(session_factory) as session:
        user = SqlAlchemyUserRepository(session).create("filter-user", "hash")
        repository = SqlAlchemyInteractionRepository(session)
        repository.add(
            user_id=user.id,
            recipe_id="recipe-query",
            event_type=InteractionType.QUERY,
        )
        repository.add(
            user_id=user.id,
            recipe_id="recipe-plan",
            event_type=InteractionType.PLAN,
        )
        consumed = repository.list_for_user(
            user.id, event_types={InteractionType.CONSUME}
        )
        assert consumed == []
        assert session.scalar(select(func.count()).select_from(RecipeInteraction)) == 2
