"""Business route and simple-chat schemas."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RouteType(str, Enum):
    SIMPLE = "SIMPLE"
    RECIPE_KNOWLEDGE = "RECIPE_KNOWLEDGE"
    RECIPE_RECOMMENDATION = "RECIPE_RECOMMENDATION"
    NUTRITION_PLANNING = "NUTRITION_PLANNING"
    COMPLEX = "COMPLEX"


class RouteDecision(BaseModel):
    """Structured output of business-level routing."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    route: RouteType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    requires_weather: bool = False
    requires_meal_history: bool = False
    requires_multiple_experts: bool = False


class SimpleChatCategory(str, Enum):
    GREETING = "GREETING"
    THANKS = "THANKS"
    CAPABILITY = "CAPABILITY"
    FAREWELL = "FAREWELL"
    EMPTY = "EMPTY"
    GENERAL = "GENERAL"


class SimpleChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: SimpleChatCategory
    message: str = Field(min_length=1)
