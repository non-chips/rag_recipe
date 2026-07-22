"""Optional local FastMCP server with lazy dependency and resource startup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from recipe_assistant.core.config import PROJECT_ROOT
from recipe_assistant.core.database import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from recipe_assistant.mcp_tools.facade import McpToolFacade
from recipe_assistant.mcp_tools.nutrition_tools import NutritionMcpTools
from recipe_assistant.mcp_tools.recipe_tools import RecipeMcpTools
from recipe_assistant.mcp_tools.recommendation_tools import RecommendationMcpTools
from recipe_assistant.mcp_tools.schemas import (
    NutritionSummaryInput,
    RecipeCandidatesInput,
    RecipeDetailInput,
    RecipeSearchInput,
)
from recipe_assistant.repositories.sqlite import SqlAlchemyInteractionRepository
from recipe_assistant.services.meal_history import MealHistoryService
from recipe_assistant.services.nutrition import NutritionCatalog, NutritionService
from recipe_assistant.services.recommendation import RecommendationService
from recipe_assistant.services.retrieval import RetrievalService


class McpDependencyMissingError(RuntimeError):
    pass


class McpServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(PROJECT_ROOT) / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    mcp_enabled: bool = False
    mcp_user_id: int | None = Field(default=None, gt=0)
    mcp_transport: Literal["stdio"] = "stdio"


class _ScopedMealHistoryProvider:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def load_confirmed(self, user_id: int, *, days: int = 7):
        with session_scope(self.factory) as session:
            return MealHistoryService(
                SqlAlchemyInteractionRepository(session)
            ).load_confirmed(user_id, days=days)


@dataclass(slots=True)
class McpRuntime:
    facade: McpToolFacade
    retrieval_service: RetrievalService
    engine: Engine

    def close(self) -> None:
        try:
            self.retrieval_service.close()
        finally:
            self.engine.dispose()


def build_default_runtime(settings: McpServerSettings) -> McpRuntime:
    """Build resources only after the caller has confirmed MCP is enabled."""

    if not settings.mcp_enabled:
        raise RuntimeError("MCP runtime must not be built while MCP_ENABLED=false")
    if settings.mcp_user_id is None:
        raise ValueError("MCP_USER_ID must be configured when MCP is enabled")
    engine = create_database_engine()
    factory = create_session_factory(engine)
    retrieval_service = RetrievalService()
    recommendation_service = RecommendationService(retrieval_service)
    catalog_path = Path(PROJECT_ROOT) / "data" / "nutrition" / "recipes.json"
    catalog = (
        NutritionCatalog.from_json(catalog_path)
        if catalog_path.exists()
        else NutritionCatalog()
    )
    history_service = _ScopedMealHistoryProvider(factory)
    facade = McpToolFacade(
        RecipeMcpTools(retrieval_service),
        RecommendationMcpTools(recommendation_service),
        NutritionMcpTools(
            history_service,
            NutritionService(catalog),
            user_id=settings.mcp_user_id,
        ),
    )
    return McpRuntime(facade, retrieval_service, engine)


def create_fastmcp_server(facade: McpToolFacade):
    """Import the optional MCP package only when an enabled server is requested."""

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise McpDependencyMissingError(
            "MCP is enabled but the optional 'mcp' package is not installed"
        ) from exc

    server = FastMCP("recipe-assistant")

    @server.tool(name="recipe_search")
    def recipe_search(
        query: str,
        strategy: str | None = None,
        recipe_names: list[str] | None = None,
        include_ingredients: list[str] | None = None,
        exclude_ingredients: list[str] | None = None,
        tools: list[str] | None = None,
        categories: list[str] | None = None,
        top_k: int = 5,
    ) -> dict:
        """Search normalized recipe evidence without exposing retrieval internals."""

        return facade.recipe_search(
            RecipeSearchInput(
                query=query,
                strategy=strategy,
                recipe_names=tuple(recipe_names or ()),
                include_ingredients=tuple(include_ingredients or ()),
                exclude_ingredients=tuple(exclude_ingredients or ()),
                tools=tuple(tools or ()),
                categories=tuple(categories or ()),
                top_k=top_k,
            )
        ).model_dump(mode="json")

    @server.tool(name="recipe_detail")
    def recipe_detail(recipe_id: str) -> dict:
        """Return one normalized recipe evidence record by recipe identifier."""

        return facade.recipe_detail(
            RecipeDetailInput(recipe_id=recipe_id)
        ).model_dump(mode="json")

    @server.tool(name="recipe_candidates")
    def recipe_candidates(query: str, top_k: int = 5) -> dict:
        """Recall evidence-backed candidates through RecommendationService."""

        return facade.recipe_candidates(
            RecipeCandidatesInput(query=query, top_k=top_k)
        ).model_dump(mode="json")

    @server.tool(name="nutrition_summary")
    def nutrition_summary(days: int = 7) -> dict:
        """Summarize only confirmed meals for the trusted server-side user."""

        return facade.nutrition_summary(
            NutritionSummaryInput(days=days)
        ).model_dump(mode="json")

    return server


def main() -> int:
    settings = McpServerSettings()
    if not settings.mcp_enabled:
        return 0
    runtime = build_default_runtime(settings)
    try:
        server = create_fastmcp_server(runtime.facade)
        server.run(transport=settings.mcp_transport)
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
