"""FastAPI dependency container and request-scoped identity contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fastapi import Header, Request
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from recipe_assistant.agents.harness import (
    LegacyReactAgentAdapter,
)
from recipe_assistant.agents.factory import build_runtime_harness
from recipe_assistant.agents.result import ChatRequest, ChatServiceResult
from recipe_assistant.api.application import ApiApplicationService
from recipe_assistant.core.config import PROJECT_ROOT, Settings, get_settings
from recipe_assistant.core.container import ResourceContainer
from recipe_assistant.core.database import (
    Base,
    create_database_engine,
    create_session_factory,
)
from recipe_assistant.services.chat import ChatService
from recipe_assistant.services.nutrition import NutritionCatalog


class ChatRunner(Protocol):
    def run(self, request: ChatRequest) -> ChatServiceResult: ...


class LazyLegacyExecutor:
    """Delay the legacy model/agent construction until a non-simple request arrives."""

    def __init__(self) -> None:
        self._adapter: LegacyReactAgentAdapter | None = None

    def execute(self, query: str, thread_id: str) -> str:
        if self._adapter is None:
            from agent.react_agent import ReactAgent

            self._adapter = LegacyReactAgentAdapter(ReactAgent())
        return self._adapter.execute(query, thread_id)


@dataclass(slots=True)
class ApiContainer:
    engine: Engine
    session_factory: sessionmaker[Session]
    chat_runner: ChatRunner
    application: ApiApplicationService
    resources: ResourceContainer | None = None
    started: bool = False

    @classmethod
    def build_default(cls, settings: Settings | None = None) -> "ApiContainer":
        resolved_settings = settings or get_settings()
        engine = create_database_engine()
        session_factory = create_session_factory(engine)
        harness = build_runtime_harness(
            resolved_settings,
            session_factory,
            LazyLegacyExecutor(),
        )
        catalog_path = Path(PROJECT_ROOT) / "data" / "nutrition" / "recipes.json"
        catalog = (
            NutritionCatalog.from_json(catalog_path)
            if catalog_path.exists()
            else NutritionCatalog()
        )
        return cls(
            engine=engine,
            session_factory=session_factory,
            chat_runner=ChatService(session_factory, harness),
            application=ApiApplicationService(session_factory, catalog),
            resources=ResourceContainer(resolved_settings),
        )

    def startup(self) -> None:
        Base.metadata.create_all(self.engine)
        if self.resources is not None:
            self.resources.startup()
        self.started = True

    def shutdown(self) -> None:
        try:
            if self.resources is not None:
                self.resources.shutdown()
        finally:
            self.engine.dispose()
            self.started = False


ContainerFactory = Callable[[], ApiContainer]


def get_container(request: Request) -> ApiContainer:
    return request.app.state.container


def get_user_id(x_user_id: int = Header(alias="X-User-Id", gt=0)) -> int:
    return x_user_id

