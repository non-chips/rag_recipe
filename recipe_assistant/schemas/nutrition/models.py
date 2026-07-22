"""Structured nutrition data, calculation and report contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NutritionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class NutritionDataQuality(str, Enum):
    VERIFIED = "VERIFIED"
    CALCULATED = "CALCULATED"
    ESTIMATED = "ESTIMATED"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class RecipeNutritionData(NutritionModel):
    recipe_id: str = Field(min_length=1)
    serving_size: float | None = Field(default=None, gt=0)
    calories_kcal: float | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)
    carbohydrate_g: float | None = Field(default=None, ge=0)
    fiber_g: float | None = Field(default=None, ge=0)
    sodium_mg: float | None = Field(default=None, ge=0)
    food_categories: tuple[str, ...] = ()
    source: str = Field(min_length=1)
    quality: NutritionDataQuality
    calculation_version: str = Field(min_length=1)


class ConfirmedMealType(str, Enum):
    CONSUME = "CONSUME"
    COOK = "COOK"


class ConfirmedMealRecord(NutritionModel):
    recipe_id: str = Field(min_length=1)
    event_type: ConfirmedMealType
    servings: float | None = Field(default=None, gt=0)
    source: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value


class ConfirmedMealHistory(NutritionModel):
    user_id: int = Field(gt=0)
    records: tuple[ConfirmedMealRecord, ...] = ()
    included_event_types: tuple[ConfirmedMealType, ...]
    start_at: datetime | None = None
    end_at: datetime | None = None


class NutritionMetric(NutritionModel):
    value: float | None = None
    unit: str = Field(min_length=1)
    data_quality: NutritionDataQuality
    source: tuple[str, ...] = ()
    coverage: float = Field(ge=0, le=1)


class NutritionSummary(NutritionModel):
    confirmed_meal_count: int = Field(ge=0)
    distinct_recipe_count: int = Field(ge=0)
    data_coverage: float = Field(ge=0, le=1)
    metrics: dict[str, NutritionMetric] = Field(default_factory=dict)
    food_category_distribution: dict[str, int] = Field(default_factory=dict)
    precise_metrics_available: bool
    limitations: tuple[str, ...] = ()
    calculation_version: str = Field(min_length=1)


class NutritionGoal(NutritionModel):
    mode: str
    food_categories_to_vary: tuple[str, ...] = ()
    target_recipe_diversity: int = Field(ge=0)
    guidance: tuple[str, ...] = ()
    based_on_confirmed_meals: int = Field(ge=0)
    medical_advice: bool = False


class NutritionReport(NutritionModel):
    report_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    generated_at: datetime
    period_start: datetime | None = None
    period_end: datetime | None = None
    data_basis: tuple[str, ...]
    confirmed_meal_count: int = Field(ge=0)
    data_coverage: float = Field(ge=0, le=1)
    recipe_diversity: int = Field(ge=0)
    food_category_distribution: dict[str, int] = Field(default_factory=dict)
    metrics: dict[str, NutritionMetric] = Field(default_factory=dict)
    observations: tuple[str, ...] = ()
    food_based_guidance: tuple[str, ...] = ()
    next_period_goal: NutritionGoal
    limitations: tuple[str, ...] = ()
    generation_version: str = Field(min_length=1)

