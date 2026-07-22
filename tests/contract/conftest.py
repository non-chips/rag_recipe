from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from recipe_assistant.agents.result import ChatRequest
from recipe_assistant.api.application import ApiApplicationService
from recipe_assistant.api.dependencies import ApiContainer
from recipe_assistant.core.database import Base, create_session_factory, session_scope
from recipe_assistant.main import create_app
from recipe_assistant.repositories.sqlite import SqlAlchemyUserRepository
from recipe_assistant.services.nutrition import NutritionCatalog


class _UnusedChatRunner:
    def run(self, request: ChatRequest):
        del request
        raise RuntimeError("chat runner is not used by this contract fixture")


@pytest.fixture
def api_container():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    Base.metadata.create_all(engine)
    with session_scope(factory) as session:
        user = SqlAlchemyUserRepository(session).create("contract-user", "test-hash")
        user_id = user.id
    container = ApiContainer(
        engine=engine,
        session_factory=factory,
        chat_runner=_UnusedChatRunner(),
        application=ApiApplicationService(factory, NutritionCatalog()),
    )
    return container, user_id


@pytest.fixture
def api_client(api_container):
    container, user_id = api_container
    with TestClient(create_app(lambda: container)) as client:
        yield client, container, user_id

