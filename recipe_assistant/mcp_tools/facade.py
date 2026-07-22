"""Allowlisted aggregation of high-level MCP tools."""

from __future__ import annotations

from recipe_assistant.mcp_tools.nutrition_tools import NutritionMcpTools
from recipe_assistant.mcp_tools.recipe_tools import RecipeMcpTools
from recipe_assistant.mcp_tools.recommendation_tools import RecommendationMcpTools
from recipe_assistant.mcp_tools.schemas import (
    NutritionSummaryInput,
    NutritionSummaryResult,
    RecipeCandidatesInput,
    RecipeCandidatesResult,
    RecipeDetailInput,
    RecipeDetailResult,
    RecipeSearchInput,
    RecipeSearchResult,
)


class McpToolFacade:
    """Expose only reviewed high-level operations, never infrastructure primitives."""

    TOOL_NAMES = (
        "recipe_search",
        "recipe_detail",
        "recipe_candidates",
        "nutrition_summary",
    )

    def __init__(
        self,
        recipe_tools: RecipeMcpTools,
        recommendation_tools: RecommendationMcpTools,
        nutrition_tools: NutritionMcpTools,
    ) -> None:
        self.recipe_tools = recipe_tools
        self.recommendation_tools = recommendation_tools
        self.nutrition_tools = nutrition_tools

    def recipe_search(self, request: RecipeSearchInput) -> RecipeSearchResult:
        return self.recipe_tools.recipe_search(request)

    def recipe_detail(self, request: RecipeDetailInput) -> RecipeDetailResult:
        return self.recipe_tools.recipe_detail(request)

    def recipe_candidates(
        self, request: RecipeCandidatesInput
    ) -> RecipeCandidatesResult:
        return self.recommendation_tools.recipe_candidates(request)

    def nutrition_summary(
        self, request: NutritionSummaryInput
    ) -> NutritionSummaryResult:
        return self.nutrition_tools.nutrition_summary(request)
