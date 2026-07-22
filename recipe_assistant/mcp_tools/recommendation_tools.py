"""High-level MCP candidate recall backed by RecommendationService."""

from recipe_assistant.mcp_tools.schemas import (
    RecipeCandidatesInput,
    RecipeCandidatesResult,
)
from recipe_assistant.services.recommendation import RecommendationService


class RecommendationMcpTools:
    def __init__(self, recommendation_service: RecommendationService) -> None:
        self.recommendation_service = recommendation_service

    def recipe_candidates(
        self, request: RecipeCandidatesInput
    ) -> RecipeCandidatesResult:
        result = self.recommendation_service.recall(
            request.query,
            top_k=request.top_k,
        )
        return RecipeCandidatesResult.model_validate(result.model_dump(mode="python"))
