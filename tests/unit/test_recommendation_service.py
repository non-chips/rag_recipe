from __future__ import annotations

from recipe_assistant.schemas.retrieval import (
    RetrievalHit,
    RetrievalResult,
    RetrievalStrategy,
)
from recipe_assistant.services.constraint import (
    PreferenceContext,
    TemporaryConstraints,
)
from recipe_assistant.services.recommendation import RecommendationService
from recipe_assistant.services.weather import WeatherContext


class _FakeRetrievalService:
    def retrieve(self, request):
        return RetrievalResult(
            query=request.query,
            strategy=RetrievalStrategy.ADVANCED_HYBRID,
            hits=[
                RetrievalHit(
                    recipe_id="r1",
                    recipe_name="番茄炒蛋",
                    source_path="recipes/r1.md",
                    content="食材与步骤证据",
                    fused_score=0.5,
                    metadata={
                        "ingredients": ["番茄", "鸡蛋"],
                        "tools": ["炒锅"],
                        "cook_time_minutes": 12,
                        "category": "家常菜",
                        "weather_tags": ["晴"],
                    },
                ),
                RetrievalHit(
                    recipe_id="r1",
                    recipe_name="番茄炒蛋",
                    source_path="recipes/r1.md",
                    content="重复但分数较低的证据",
                    fused_score=0.2,
                ),
                RetrievalHit(
                    recipe_id="r2",
                    recipe_name="烤蔬菜",
                    source_path="recipes/r2.md",
                    content="烤制证据",
                    fused_score=0.6,
                    metadata={
                        "ingredients": ["土豆"],
                        "tools": ["烤箱"],
                        "cook_time_minutes": 30,
                    },
                ),
            ],
            confidence=0.5,
        )


def test_recall_deduplicates_and_preserves_retrieval_evidence() -> None:
    service = RecommendationService(_FakeRetrievalService())  # type: ignore[arg-type]

    result = service.recall("推荐晚餐", top_k=5)

    assert [candidate.recipe_id for candidate in result.candidates] == ["r1", "r2"]
    assert result.candidates[0].evidence == "食材与步骤证据"
    assert result.candidates[0].ingredients == ("番茄", "鸡蛋")


def test_ranking_is_deterministic_and_exposes_features() -> None:
    service = RecommendationService(_FakeRetrievalService())  # type: ignore[arg-type]
    candidates = service.recall("推荐晚餐").candidates

    ranked = service.rank_candidates(
        candidates,
        TemporaryConstraints(
            available_ingredients=("番茄", "鸡蛋"),
            available_tools=("炒锅",),
            max_time_minutes=20,
        ),
        PreferenceContext(preferred_cuisines=("家常菜",)),
        WeatherContext(available=True, city="北京", condition="晴"),
    )

    assert [candidate.recipe_id for candidate in ranked] == ["r1", "r2"]
    assert ranked[0].ranking_features == {
        "retrieval": 0.5,
        "ingredient_coverage": 1.0,
        "preferred_cuisine": 1.0,
        "tool_match": 1.0,
        "time_fit": 1.0,
        "weather_match": 1.0,
    }
