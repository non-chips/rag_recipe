"""Pydantic schemas for local tool arguments, results and audit traces."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from recipe_assistant.schemas.retrieval import RetrievalStrategy
from recipe_assistant.tools.governance import ToolRiskLevel


class ToolRole(str, Enum):
    COORDINATOR = "coordinator"
    KNOWLEDGE_EXPERT = "knowledge_expert"
    RECOMMENDATION_EXPERT = "recommendation_expert"
    NUTRITION_EXPERT = "nutrition_expert"


class ToolTraceStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchRecipeKnowledgeInput(ToolArguments):
    query: str = Field(min_length=1)
    strategy: RetrievalStrategy | None = None
    recipe_names: list[str] = Field(default_factory=list)
    include_ingredients: list[str] = Field(default_factory=list)
    exclude_ingredients: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)


class RecommendRecipesInput(ToolArguments):
    query: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)


class CurrentWeatherInput(ToolArguments):
    city: str = Field(min_length=1)


class MealHistoryInput(ToolArguments):
    days: int = Field(default=7, ge=1, le=90)


class SaveMealRecordInput(ToolArguments):
    recipe_id: str = Field(min_length=1)
    meal_type: str | None = None
    notes: str | None = Field(default=None, max_length=500)


class CalculateNutritionInput(ToolArguments):
    recipe_ids: list[str] = Field(min_length=1, max_length=20)


class CreateNutritionReportInput(ToolArguments):
    title: str = Field(min_length=1, max_length=100)
    recipe_ids: list[str] = Field(min_length=1, max_length=50)


class SendReportEmailInput(ToolArguments):
    report_id: str = Field(min_length=1)
    recipient_label: str = Field(min_length=1, max_length=100)


class ToolInvocationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    output: Any


class ToolCallTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    run_id: str
    user_id: int
    session_id: str
    role: ToolRole
    tool_name: str
    risk_level: ToolRiskLevel | None = None
    status: ToolTraceStatus
    argument_names: list[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime
    duration_ms: float = Field(ge=0.0)
    error_type: str | None = None
    error_message: str | None = None
