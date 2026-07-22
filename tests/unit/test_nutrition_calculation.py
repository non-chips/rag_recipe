from datetime import timedelta

import pytest

from recipe_assistant.core.database import utc_now
from recipe_assistant.schemas.nutrition import (
    ConfirmedMealHistory,
    ConfirmedMealRecord,
    ConfirmedMealType,
    NutritionDataQuality,
    RecipeNutritionData,
)
from recipe_assistant.services.nutrition import NutritionCatalog, NutritionService


def _history(*records: ConfirmedMealRecord) -> ConfirmedMealHistory:
    now = utc_now()
    return ConfirmedMealHistory(
        user_id=1,
        records=records,
        included_event_types=(ConfirmedMealType.CONSUME,),
        start_at=now - timedelta(days=7),
        end_at=now,
    )


def _meal(recipe_id: str, servings: float | None) -> ConfirmedMealRecord:
    return ConfirmedMealRecord(
        recipe_id=recipe_id,
        event_type=ConfirmedMealType.CONSUME,
        servings=servings,
        source="user_confirmation",
        occurred_at=utc_now(),
    )


def test_serving_conversion_preserves_source_quality_and_coverage() -> None:
    data = RecipeNutritionData(
        recipe_id="r1",
        serving_size=2,
        calories_kcal=400,
        protein_g=20,
        food_categories=("蔬菜",),
        source="source-dataset-v1",
        quality=NutritionDataQuality.VERIFIED,
        calculation_version="v1",
    )
    service = NutritionService(NutritionCatalog([data]))

    summary = service.summarize(_history(_meal("r1", 1)))

    assert summary.metrics["calories"].value == pytest.approx(200)
    assert summary.metrics["protein"].value == pytest.approx(10)
    assert summary.metrics["calories"].unit == "kcal"
    assert summary.metrics["calories"].data_quality is NutritionDataQuality.VERIFIED
    assert summary.metrics["calories"].source == ("source-dataset-v1",)
    assert summary.metrics["calories"].coverage == 1.0


def test_missing_data_and_servings_reduce_coverage_and_force_degradation() -> None:
    data = RecipeNutritionData(
        recipe_id="known",
        serving_size=1,
        calories_kcal=300,
        food_categories=("全谷物",),
        source="source-dataset-v1",
        quality=NutritionDataQuality.CALCULATED,
        calculation_version="v1",
    )
    service = NutritionService(NutritionCatalog([data]))

    summary = service.summarize(
        _history(_meal("known", 1), _meal("unknown", 1), _meal("known", None))
    )

    assert summary.data_coverage == pytest.approx(1 / 3)
    assert summary.metrics["calories"].coverage == pytest.approx(1 / 3)
    assert summary.precise_metrics_available is False
    assert "报告降级" in summary.limitations[-1]


def test_empty_history_never_creates_numeric_estimates() -> None:
    summary = NutritionService.build_empty_summary()

    assert summary.precise_metrics_available is False
    assert all(metric.value is None for metric in summary.metrics.values())
    assert all(
        metric.data_quality is NutritionDataQuality.UNKNOWN
        for metric in summary.metrics.values()
    )

