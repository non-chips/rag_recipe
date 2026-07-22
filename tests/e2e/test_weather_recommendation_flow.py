from __future__ import annotations

import pytest

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.coordinator import CoordinationStatus, RecipeCoordinator
from recipe_assistant.agents.events import ArtifactKind
from recipe_assistant.agents.experts.recipe_recommendation import (
    RecipeRecommendationExpert,
)
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.schemas.retrieval import (
    RetrievalHit,
    RetrievalResult,
    RetrievalStrategy,
)
from recipe_assistant.services.constraint import PreferenceContext
from recipe_assistant.services.recommendation import RecommendationService
from recipe_assistant.services.weather import WeatherService
from recipe_assistant.tools.recipe_knowledge_tools import create_recipe_knowledge_tool
from recipe_assistant.tools.recommendation_tools import create_recommendation_service_tools
from recipe_assistant.tools.registry import ToolRegistry


class _RecommendationRetrieval:
    def __init__(self) -> None:
        self.requests = []

    def retrieve(self, request):
        self.requests.append(request)
        if request.recipe_names:
            return RetrievalResult(
                query=request.query,
                strategy=RetrievalStrategy.BM25_KEYWORD,
                hits=[
                    RetrievalHit(
                        recipe_id="tomato-egg",
                        recipe_name="番茄炒蛋",
                        source_path="recipes/tomato-egg.md",
                        content="食材、厨具和时间补充证据",
                        metadata={
                            "ingredients": ["番茄", "鸡蛋"],
                            "tools": ["炒锅"],
                            "cook_time_minutes": 15,
                            "weather_tags": ["晴"],
                        },
                    )
                ],
                confidence=1 / 3,
            )
        return RetrievalResult(
            query=request.query,
            strategy=RetrievalStrategy.ADVANCED_HYBRID,
            hits=[
                RetrievalHit(
                    recipe_id="tomato-egg",
                    recipe_name="番茄炒蛋",
                    source_path="recipes/tomato-egg.md",
                    content="番茄炒蛋候选证据",
                    fused_score=0.8,
                ),
                RetrievalHit(
                    recipe_id="peanut-chicken",
                    recipe_name="花生鸡丁",
                    source_path="recipes/peanut-chicken.md",
                    content="花生鸡丁候选证据",
                    fused_score=0.9,
                    metadata={
                        "ingredients": ["花生", "鸡肉"],
                        "tools": ["炒锅"],
                        "cook_time_minutes": 15,
                    },
                ),
            ],
            confidence=0.6,
        )


def _run(weather_provider):
    retrieval = _RecommendationRetrieval()
    recommendation = RecommendationService(retrieval)  # type: ignore[arg-type]
    weather = WeatherService(weather_provider=weather_provider)
    tools = create_recommendation_service_tools(recommendation, weather)
    tools.append(create_recipe_knowledge_tool(retrieval))  # type: ignore[arg-type]
    expert = RecipeRecommendationExpert(
        ToolRegistry(tools),
        preference_provider=lambda _user_id: PreferenceContext(allergens=("花生",)),
    )
    board = CollaborationBlackboard(
        run_id="run-weather-recommendation",
        user_id=9,
        session_id="session-weather-recommendation",
        user_input="根据北京天气，我有番茄和鸡蛋，用炒锅，20分钟内，不要花生，推荐菜谱",
        route=RouteDecision(
            route=RouteType.RECIPE_RECOMMENDATION,
            confidence=1.0,
            reason="weather recommendation",
            requires_weather=True,
        ),
    )
    outcome = RecipeCoordinator(ExpertRegistry([expert])).coordinate(board)
    return outcome, retrieval


def test_weather_recommendation_filters_allergens_and_supplements_evidence() -> None:
    outcome, retrieval = _run(
        lambda city: {
            "success": True,
            "city": city,
            "weather": "晴",
            "temperature_c": "24",
        }
    )

    assert outcome.status is CoordinationStatus.SUCCEEDED
    weather = outcome.blackboard.artifacts_for(kind=ArtifactKind.WEATHER_CONTEXT)[0]
    assert weather.payload["available"] is True
    assert weather.payload["city"] == "北京"
    assert [item["recipe_id"] for item in outcome.final_artifact.payload["candidates"]] == [
        "tomato-egg"
    ]
    validation = outcome.blackboard.artifacts_for(
        kind=ArtifactKind.CONSTRAINT_VALIDATION
    )[0]
    assert validation.payload["rejected"][0]["candidate"]["recipe_id"] == "peanut-chicken"
    assert len(retrieval.requests) >= 2
    assert retrieval.requests[1].recipe_names == ["番茄炒蛋"]


def test_weather_failure_does_not_block_safe_recommendations() -> None:
    def unavailable(_city: str):
        raise RuntimeError("offline")

    outcome, _retrieval = _run(unavailable)

    weather = outcome.blackboard.artifacts_for(kind=ArtifactKind.WEATHER_CONTEXT)[0]
    assert weather.payload["available"] is False
    assert weather.metadata["degraded"] is True
    assert outcome.final_artifact.payload["candidates"][0]["recipe_id"] == "tomato-egg"


@pytest.mark.parametrize("ingredient", ["花生", "香菜"])
def test_explicit_exclusions_never_reappear_in_final_candidates(ingredient: str) -> None:
    outcome, _retrieval = _run(lambda city: {"success": True, "city": city})

    for candidate in outcome.final_artifact.payload["candidates"]:
        assert ingredient not in candidate["ingredients"]
