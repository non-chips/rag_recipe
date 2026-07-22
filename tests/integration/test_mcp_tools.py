from __future__ import annotations

import builtins
from datetime import datetime, timezone

import pytest

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
from recipe_assistant.mcp_tools import server as mcp_server
from recipe_assistant.schemas.nutrition import (
    ConfirmedMealHistory,
    ConfirmedMealRecord,
    ConfirmedMealType,
    NutritionDataQuality,
    RecipeNutritionData,
)
from recipe_assistant.schemas.retrieval import (
    RetrievalHit,
    RetrievalResult,
    RetrievalStrategy,
)
from recipe_assistant.services.nutrition import NutritionCatalog, NutritionService
from recipe_assistant.services.recommendation import RecommendationService
from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.nutrition_tools import create_nutrition_service_tools
from recipe_assistant.tools.recipe_knowledge_tools import create_recipe_knowledge_tool
from recipe_assistant.tools.recommendation_tools import (
    create_recommendation_service_tools,
)


class _FakeRetrievalService:
    def __init__(self) -> None:
        self.requests = []

    def retrieve(self, request):
        self.requests.append(request)
        return RetrievalResult(
            query=request.query,
            strategy=RetrievalStrategy.DENSE_BM25,
            hits=[
                RetrievalHit(
                    recipe_id="recipe-1",
                    recipe_name="番茄炒蛋",
                    source_path="recipes.json",
                    content="番茄与鸡蛋的结构化菜谱证据",
                    retrieval_sources=["bm25", "chroma"],
                    fused_score=0.8,
                    metadata={
                        "ingredients": ["番茄", "鸡蛋"],
                        "tools": ["炒锅"],
                        "category": "家常菜",
                        "cook_time_minutes": 15,
                    },
                )
            ],
            confidence=0.8,
        )


class _FakeHistoryService:
    def load_confirmed(self, user_id: int, *, days: int = 7):
        end_at = datetime(2026, 7, 22, tzinfo=timezone.utc)
        return ConfirmedMealHistory(
            user_id=user_id,
            records=(
                ConfirmedMealRecord(
                    recipe_id="recipe-1",
                    event_type=ConfirmedMealType.CONSUME,
                    servings=1.0,
                    source="confirmed",
                    confidence=1.0,
                    occurred_at=end_at,
                ),
            ),
            included_event_types=(ConfirmedMealType.CONSUME,),
            start_at=end_at,
            end_at=end_at,
        )


def _facade():
    retrieval = _FakeRetrievalService()
    recommendation = RecommendationService(retrieval)
    history = _FakeHistoryService()
    nutrition = NutritionService(
        NutritionCatalog(
            (
                RecipeNutritionData(
                    recipe_id="recipe-1",
                    serving_size=1.0,
                    calories_kcal=220,
                    protein_g=12,
                    food_categories=("蔬菜", "蛋类"),
                    source="verified-catalog",
                    quality=NutritionDataQuality.VERIFIED,
                    calculation_version="test-v1",
                ),
            )
        )
    )
    return (
        McpToolFacade(
            RecipeMcpTools(retrieval),
            RecommendationMcpTools(recommendation),
            NutritionMcpTools(history, nutrition, user_id=7),
        ),
        retrieval,
        recommendation,
        history,
        nutrition,
    )


def _context() -> ToolContext:
    return ToolContext(
        run_id="mcp-semantic-test",
        user_id=7,
        session_id="session",
        route="RECIPE_KNOWLEDGE",
        permissions=frozenset({"user_data:read"}),
    )


def test_recipe_search_matches_local_tool_service_semantics() -> None:
    facade, retrieval, *_rest = _facade()
    arguments = {
        "query": "番茄炒蛋",
        "include_ingredients": ["番茄"],
        "top_k": 5,
    }
    local = create_recipe_knowledge_tool(retrieval).invoke(arguments, _context())
    mcp = facade.recipe_search(
        RecipeSearchInput(
            query="番茄炒蛋",
            include_ingredients=("番茄",),
            top_k=5,
        )
    ).model_dump(mode="json")

    assert mcp == local
    assert retrieval.requests[-1].candidate_k == retrieval.requests[-2].candidate_k == 20


def test_recipe_detail_and_candidates_are_high_level_service_results() -> None:
    facade, _retrieval, recommendation, *_rest = _facade()
    detail = facade.recipe_detail(RecipeDetailInput(recipe_id="recipe-1"))
    local_candidates = create_recommendation_service_tools(recommendation)[0].invoke(
        {"query": "家常菜", "top_k": 3},
        _context(),
    )
    mcp_candidates = facade.recipe_candidates(
        RecipeCandidatesInput(query="家常菜", top_k=3)
    ).model_dump(mode="json")

    assert detail.found is True
    assert detail.detail is not None and detail.detail.recipe_id == "recipe-1"
    assert mcp_candidates == local_candidates
    assert mcp_candidates["candidates"][0]["recipe_id"] == "recipe-1"


def test_nutrition_summary_matches_local_service_adapter_semantics() -> None:
    facade, _retrieval, _recommendation, history, nutrition = _facade()
    local_tools = create_nutrition_service_tools(history, nutrition)
    calculate = next(
        tool for tool in local_tools if tool.name == "calculate_recipe_nutrition"
    )
    local = calculate.invoke({"recipe_ids": ["recipe-1"]}, _context())
    mcp = facade.nutrition_summary(
        NutritionSummaryInput(days=7)
    ).model_dump(mode="json")

    assert mcp == local
    assert mcp["confirmed_meal_count"] == 1
    assert mcp["metrics"]["calories"]["value"] == 220.0


def test_allowlist_excludes_raw_storage_and_identity_arguments() -> None:
    facade, *_rest = _facade()
    assert facade.TOOL_NAMES == (
        "recipe_search",
        "recipe_detail",
        "recipe_candidates",
        "nutrition_summary",
    )
    prohibited = {
        "chroma_query_raw",
        "neo4j_cypher_execute",
        "database_execute",
        "read_all_chat_messages",
        "read_raw_user_profile",
    }
    assert prohibited.isdisjoint(facade.TOOL_NAMES)
    for schema in (
        RecipeSearchInput,
        RecipeDetailInput,
        RecipeCandidatesInput,
        NutritionSummaryInput,
    ):
        assert "user_id" not in schema.model_fields


def test_disabled_mcp_does_not_build_resources_or_import_runtime(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MCP_ENABLED", "false")

    def fail_if_built(_settings):
        raise AssertionError("disabled MCP must not initialize resources")

    monkeypatch.setattr(mcp_server, "build_default_runtime", fail_if_built)
    monkeypatch.setattr(
        mcp_server,
        "create_fastmcp_server",
        lambda _facade: (_ for _ in ()).throw(
            AssertionError("disabled MCP must not import FastMCP")
        ),
    )
    assert mcp_server.main() == 0


def test_missing_optional_mcp_dependency_is_actionable(monkeypatch) -> None:
    facade, *_rest = _facade()
    original_import = builtins.__import__

    def controlled_import(name, *args, **kwargs):
        if name.startswith("mcp"):
            raise ImportError("test missing optional package")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", controlled_import)
    with pytest.raises(mcp_server.McpDependencyMissingError, match="optional 'mcp'"):
        mcp_server.create_fastmcp_server(facade)
