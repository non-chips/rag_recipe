"""Typed high-level contracts exposed through the optional MCP boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from recipe_assistant.schemas.retrieval import (
    RetrievalHit,
    RetrievalResult,
    RetrievalStrategy,
)
from recipe_assistant.schemas.nutrition import NutritionSummary
from recipe_assistant.services.recommendation import RecommendationRecall


class McpToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RecipeSearchInput(McpToolSchema):
    query: str = Field(min_length=1)
    strategy: RetrievalStrategy | None = None
    recipe_names: tuple[str, ...] = ()
    include_ingredients: tuple[str, ...] = ()
    exclude_ingredients: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    top_k: int = Field(default=5, ge=1, le=20)


class RecipeDetailInput(McpToolSchema):
    recipe_id: str = Field(min_length=1, max_length=100)


class RecipeDetailResult(McpToolSchema):
    recipe_id: str
    found: bool
    detail: RetrievalHit | None = None
    warnings: tuple[str, ...] = ()


class RecipeCandidatesInput(McpToolSchema):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class NutritionSummaryInput(McpToolSchema):
    days: int = Field(default=7, ge=1, le=90)


class RecipeSearchResult(RetrievalResult):
    """Named MCP result retaining the canonical RetrievalResult contract."""


class RecipeCandidatesResult(RecommendationRecall):
    """Named MCP result retaining the canonical recommendation recall contract."""


class NutritionSummaryResult(NutritionSummary):
    """Named MCP result retaining the canonical NutritionSummary contract."""
