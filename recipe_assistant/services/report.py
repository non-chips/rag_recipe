"""Side-effect-free JSON nutrition report drafting."""

from __future__ import annotations

from recipe_assistant.core.database import utc_now
from recipe_assistant.schemas.nutrition import (
    ConfirmedMealHistory,
    NutritionGoal,
    NutritionReport,
    NutritionSummary,
)


class ReportService:
    GENERATION_VERSION = "nutrition_report_v1"

    def create_draft(
        self,
        *,
        run_id: str,
        title: str,
        history: ConfirmedMealHistory,
        summary: NutritionSummary,
        goal: NutritionGoal,
    ) -> NutritionReport:
        observations = (
            ("记录可用于来源化营养概览",)
            if summary.precise_metrics_available
            else ("记录仅支持食物类别与多样性观察",)
        )
        return NutritionReport(
            report_id=f"nutrition:{run_id}",
            title=title,
            generated_at=utc_now(),
            period_start=history.start_at,
            period_end=history.end_at,
            data_basis=tuple(item.value for item in history.included_event_types),
            confirmed_meal_count=summary.confirmed_meal_count,
            data_coverage=summary.data_coverage,
            recipe_diversity=summary.distinct_recipe_count,
            food_category_distribution=summary.food_category_distribution,
            metrics=summary.metrics if summary.precise_metrics_available else {},
            observations=observations,
            food_based_guidance=goal.guidance,
            next_period_goal=goal,
            limitations=summary.limitations,
            generation_version=self.GENERATION_VERSION,
        )

