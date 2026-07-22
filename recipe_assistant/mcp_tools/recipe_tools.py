"""High-level MCP recipe tools backed only by RetrievalService."""

from __future__ import annotations

from recipe_assistant.mcp_tools.schemas import (
    RecipeDetailInput,
    RecipeDetailResult,
    RecipeSearchInput,
    RecipeSearchResult,
)
from recipe_assistant.schemas.retrieval import RetrievalRequest
from recipe_assistant.services.retrieval import RetrievalService


class RecipeMcpTools:
    def __init__(self, retrieval_service: RetrievalService) -> None:
        self.retrieval_service = retrieval_service

    def recipe_search(self, request: RecipeSearchInput) -> RecipeSearchResult:
        result = self.retrieval_service.retrieve(
            RetrievalRequest(
                query=request.query,
                strategy=request.strategy,
                recipe_names=list(request.recipe_names),
                include_ingredients=list(request.include_ingredients),
                exclude_ingredients=list(request.exclude_ingredients),
                tools=list(request.tools),
                categories=list(request.categories),
                top_k=request.top_k,
                candidate_k=max(20, request.top_k),
            )
        )
        return RecipeSearchResult.model_validate(result.model_dump(mode="python"))

    def recipe_detail(self, request: RecipeDetailInput) -> RecipeDetailResult:
        result = self.retrieval_service.retrieve(
            RetrievalRequest(
                query=request.recipe_id,
                recipe_names=[request.recipe_id],
                top_k=10,
                candidate_k=20,
            )
        )
        detail = next(
            (hit for hit in result.hits if hit.recipe_id == request.recipe_id),
            None,
        )
        return RecipeDetailResult(
            recipe_id=request.recipe_id,
            found=detail is not None,
            detail=detail,
            warnings=tuple(result.warnings),
        )
