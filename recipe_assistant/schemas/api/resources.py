"""DTOs for health, meal confirmation and nutrition report endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from recipe_assistant.models import InteractionType
from recipe_assistant.schemas.api.common import ApiSchema
from recipe_assistant.schemas.nutrition import NutritionReport


class HealthComponent(ApiSchema):
    status: Literal["UP", "DEGRADED", "DOWN", "DISABLED"]
    detail: str = ""


class HealthResponse(ApiSchema):
    status: Literal["UP", "DEGRADED", "DOWN"]
    components: dict[str, HealthComponent]


class MealConfirmRequest(ApiSchema):
    recipe_id: str = Field(min_length=1, max_length=100)
    event_type: Literal[InteractionType.COOK, InteractionType.CONSUME]
    servings: float | None = Field(default=None, gt=0)
    source: str = Field(default="api_confirmation", min_length=1, max_length=100)
    occurred_at: datetime | None = None


class NutritionReportRequest(ApiSchema):
    title: str = Field(default="确认饮食记录营养概览", min_length=1, max_length=100)
    days: int = Field(default=7, ge=1, le=90)


class NutritionReportRead(ApiSchema):
    report: NutritionReport

