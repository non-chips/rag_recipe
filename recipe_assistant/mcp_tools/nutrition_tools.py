"""User-scoped MCP nutrition summary composed from existing Services."""

from __future__ import annotations

from typing import Protocol

from recipe_assistant.mcp_tools.schemas import (
    NutritionSummaryInput,
    NutritionSummaryResult,
)
from recipe_assistant.schemas.nutrition import ConfirmedMealHistory
from recipe_assistant.services.nutrition import NutritionService


class ConfirmedMealHistoryProvider(Protocol):
    def load_confirmed(
        self, user_id: int, *, days: int = 7
    ) -> ConfirmedMealHistory: ...


class NutritionMcpTools:
    """Keep trusted user identity outside the MCP-visible input schema."""

    def __init__(
        self,
        history_service: ConfirmedMealHistoryProvider,
        nutrition_service: NutritionService,
        *,
        user_id: int,
    ) -> None:
        if user_id < 1:
            raise ValueError("MCP user_id must be positive")
        self.history_service = history_service
        self.nutrition_service = nutrition_service
        self.user_id = user_id

    def nutrition_summary(
        self, request: NutritionSummaryInput
    ) -> NutritionSummaryResult:
        history = self.history_service.load_confirmed(
            self.user_id,
            days=request.days,
        )
        summary = self.nutrition_service.summarize(history)
        return NutritionSummaryResult.model_validate(summary.model_dump(mode="python"))
