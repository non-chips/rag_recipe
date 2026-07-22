"""Candidate recall and deterministic recommendation ranking."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from recipe_assistant.schemas.retrieval import RetrievalRequest
from recipe_assistant.services.constraint import (
    PreferenceContext,
    RecipeCandidate,
    TemporaryConstraints,
)
from recipe_assistant.services.retrieval import RetrievalService
from recipe_assistant.services.weather import WeatherContext


class RecommendationRecall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1)
    candidates: tuple[RecipeCandidate, ...] = ()
    warnings: tuple[str, ...] = ()
    fallback_used: bool = False


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class RecommendationService:
    """Recall only retrieved recipes, then expose explainable ranking features."""

    def __init__(self, retrieval_service: RetrievalService) -> None:
        self.retrieval_service = retrieval_service

    def recall(self, query: str, *, top_k: int = 20) -> RecommendationRecall:
        result = self.retrieval_service.retrieve(
            RetrievalRequest(query=query, top_k=top_k, candidate_k=max(20, top_k))
        )
        deduplicated: dict[str, RecipeCandidate] = {}
        for hit in result.hits:
            metadata = hit.metadata
            candidate = RecipeCandidate(
                recipe_id=hit.recipe_id,
                recipe_name=hit.recipe_name,
                ingredients=_strings(metadata.get("ingredients")),
                tools=_strings(metadata.get("tools")),
                cook_time_minutes=_positive_int(
                    metadata.get("cook_time_minutes") or metadata.get("time_minutes")
                ),
                category=str(metadata.get("category") or ""),
                weather_tags=_strings(metadata.get("weather_tags")),
                source_path=hit.source_path,
                evidence=hit.content,
                retrieval_score=hit.fused_score,
            )
            previous = deduplicated.get(candidate.recipe_id)
            if previous is None or candidate.retrieval_score > previous.retrieval_score:
                deduplicated[candidate.recipe_id] = candidate
        return RecommendationRecall(
            query=result.query,
            candidates=tuple(deduplicated.values()),
            warnings=tuple(result.warnings),
            fallback_used=result.fallback_used,
        )

    @staticmethod
    def rank_candidates(
        candidates: tuple[RecipeCandidate, ...],
        constraints: TemporaryConstraints,
        preferences: PreferenceContext,
        weather: WeatherContext | None = None,
    ) -> tuple[RecipeCandidate, ...]:
        available = {item.casefold() for item in constraints.available_ingredients}
        available_tools = {item.casefold() for item in constraints.available_tools}
        preferred = {item.casefold() for item in preferences.preferred_cuisines}
        ranked: list[RecipeCandidate] = []
        for candidate in candidates:
            ingredients = {item.casefold() for item in candidate.ingredients}
            coverage = len(ingredients & available) / len(available) if available else 0.0
            cuisine = 1.0 if candidate.category.casefold() in preferred else 0.0
            candidate_tools = {item.casefold() for item in candidate.tools}
            tool_match = (
                1.0
                if available_tools
                and candidate_tools
                and candidate_tools.issubset(available_tools)
                else 0.0
            )
            time_fit = (
                1.0
                if constraints.max_time_minutes is not None
                and candidate.cook_time_minutes is not None
                and candidate.cook_time_minutes <= constraints.max_time_minutes
                else 0.0
            )
            weather_tags = {item.casefold() for item in candidate.weather_tags}
            condition = weather.condition.casefold() if weather is not None else ""
            weather_match = (
                1.0
                if weather is not None
                and weather.available
                and condition
                and any(tag in condition or condition in tag for tag in weather_tags)
                else 0.0
            )
            features = {
                "retrieval": candidate.retrieval_score,
                "ingredient_coverage": coverage,
                "preferred_cuisine": cuisine,
                "tool_match": tool_match,
                "time_fit": time_fit,
                "weather_match": weather_match,
            }
            score = (
                candidate.retrieval_score
                + coverage * 0.25
                + cuisine * 0.1
                + tool_match * 0.1
                + time_fit * 0.1
                + weather_match * 0.05
            )
            ranked.append(
                candidate.model_copy(
                    update={"ranking_score": score, "ranking_features": features}
                )
            )
        return tuple(
            sorted(ranked, key=lambda item: (-item.ranking_score, item.recipe_id))
        )
