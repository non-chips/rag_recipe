"""Source-aware serving conversion and period nutrition aggregation."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from recipe_assistant.schemas.nutrition import (
    ConfirmedMealHistory,
    NutritionDataQuality,
    NutritionGoal,
    NutritionMetric,
    NutritionSummary,
    RecipeNutritionData,
)


_METRICS: dict[str, tuple[str, str]] = {
    "calories_kcal": ("calories", "kcal"),
    "protein_g": ("protein", "g"),
    "fat_g": ("fat", "g"),
    "carbohydrate_g": ("carbohydrate", "g"),
    "fiber_g": ("fiber", "g"),
    "sodium_mg": ("sodium", "mg"),
}
_QUALITY_ORDER = {
    NutritionDataQuality.VERIFIED: 0,
    NutritionDataQuality.CALCULATED: 1,
    NutritionDataQuality.ESTIMATED: 2,
    NutritionDataQuality.INCOMPLETE: 3,
    NutritionDataQuality.UNKNOWN: 4,
}


class NutritionCatalog:
    def __init__(self, records: Iterable[RecipeNutritionData] = ()) -> None:
        self._records = {record.recipe_id: record for record in records}

    @classmethod
    def from_json(cls, path: str | Path) -> "NutritionCatalog":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("nutrition data file must contain a JSON list")
        return cls(RecipeNutritionData.model_validate(item) for item in payload)

    def get(self, recipe_id: str) -> RecipeNutritionData | None:
        return self._records.get(recipe_id)


class NutritionService:
    CALCULATION_VERSION = "nutrition_summary_v1"

    def __init__(self, catalog: NutritionCatalog) -> None:
        self.catalog = catalog

    def summarize(self, history: ConfirmedMealHistory) -> NutritionSummary:
        total_records = len(history.records)
        totals = {name: 0.0 for _field, (name, _unit) in _METRICS.items()}
        counts = {name: 0 for _field, (name, _unit) in _METRICS.items()}
        qualities: dict[str, list[NutritionDataQuality]] = {
            name: [] for _field, (name, _unit) in _METRICS.items()
        }
        sources: dict[str, set[str]] = {
            name: set() for _field, (name, _unit) in _METRICS.items()
        }
        category_distribution: dict[str, int] = {}
        covered_records = 0
        recipe_ids: set[str] = set()
        limitations: list[str] = []

        for meal in history.records:
            recipe_ids.add(meal.recipe_id)
            nutrition = self.catalog.get(meal.recipe_id)
            if nutrition is None:
                continue
            for category in nutrition.food_categories:
                category_distribution[category] = category_distribution.get(category, 0) + 1
            if meal.servings is None:
                continue
            covered_records += 1
            multiplier = meal.servings / (nutrition.serving_size or 1.0)
            for field_name, (metric_name, _unit) in _METRICS.items():
                value = getattr(nutrition, field_name)
                if value is None:
                    continue
                totals[metric_name] += value * multiplier
                counts[metric_name] += 1
                qualities[metric_name].append(nutrition.quality)
                sources[metric_name].add(nutrition.source)

        coverage = covered_records / total_records if total_records else 0.0
        if not total_records:
            limitations.append("没有已确认的摄入记录")
        if covered_records < total_records:
            limitations.append("部分记录缺少营养数据或份量，未纳入精确指标")
        metrics: dict[str, NutritionMetric] = {}
        for _field_name, (metric_name, unit) in _METRICS.items():
            metric_coverage = counts[metric_name] / total_records if total_records else 0.0
            quality = (
                max(qualities[metric_name], key=_QUALITY_ORDER.get)
                if qualities[metric_name]
                else NutritionDataQuality.UNKNOWN
            )
            metrics[metric_name] = NutritionMetric(
                value=round(totals[metric_name], 3) if counts[metric_name] else None,
                unit=unit,
                data_quality=quality,
                source=tuple(sorted(sources[metric_name])),
                coverage=metric_coverage,
            )
        precise = coverage >= 0.6 and any(item.value is not None for item in metrics.values())
        if not precise:
            limitations.append("营养覆盖率不足，报告降级为食物类别与多样性概览")
        return NutritionSummary(
            confirmed_meal_count=total_records,
            distinct_recipe_count=len(recipe_ids),
            data_coverage=coverage,
            metrics=metrics,
            food_category_distribution=category_distribution,
            precise_metrics_available=precise,
            limitations=tuple(dict.fromkeys(limitations)),
            calculation_version=self.CALCULATION_VERSION,
        )

    @staticmethod
    def build_goal(summary: NutritionSummary) -> NutritionGoal:
        observed = set(summary.food_category_distribution)
        common_categories = ("蔬菜", "全谷物", "豆类", "水果")
        to_vary = tuple(category for category in common_categories if category not in observed)
        guidance = ["下一周期优先增加食物类别多样性，并继续确认实际摄入记录。"]
        if summary.precise_metrics_available:
            guidance.append("营养数值仅作为已记录餐次的来源化概览，不代表医疗诊断。")
        else:
            guidance.append("当前数据不足，不给出精确营养缺乏结论。")
        return NutritionGoal(
            mode="food_category_diversity",
            food_categories_to_vary=to_vary,
            target_recipe_diversity=max(3, summary.distinct_recipe_count + 1),
            guidance=tuple(guidance),
            based_on_confirmed_meals=summary.confirmed_meal_count,
        )

    @classmethod
    def build_empty_summary(cls) -> NutritionSummary:
        return NutritionSummary(
            confirmed_meal_count=0,
            distinct_recipe_count=0,
            data_coverage=0.0,
            metrics={
                metric_name: NutritionMetric(
                    value=None,
                    unit=unit,
                    data_quality=NutritionDataQuality.UNKNOWN,
                    coverage=0.0,
                )
                for _field, (metric_name, unit) in _METRICS.items()
            },
            precise_metrics_available=False,
            limitations=(
                "没有已确认的摄入记录",
                "营养覆盖率不足，报告降级为食物类别与多样性概览",
            ),
            calculation_version=cls.CALCULATION_VERSION,
        )
