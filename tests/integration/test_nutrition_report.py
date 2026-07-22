from __future__ import annotations

import json
from types import SimpleNamespace

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.coordinator import CoordinationStatus, RecipeCoordinator
from recipe_assistant.agents.events import (
    AgentArtifact,
    ArtifactKind,
    ExpertCapability,
    thaw_value,
)
from recipe_assistant.agents.experts.nutrition_planning import NutritionPlanningExpert
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.core.database import utc_now
from recipe_assistant.models import InteractionType
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.schemas.nutrition import (
    ConfirmedMealHistory,
    ConfirmedMealType,
    NutritionDataQuality,
    RecipeNutritionData,
)
from recipe_assistant.services.meal_history import MealHistoryService
from recipe_assistant.services.nutrition import NutritionCatalog, NutritionService
from recipe_assistant.services.report import ReportService
from recipe_assistant.tools.nutrition_tools import create_nutrition_service_tools
from recipe_assistant.tools.registry import ToolRegistry


class _Interactions:
    def list_for_user(self, user_id, event_types=None):
        del user_id
        items = [
            SimpleNamespace(
                recipe_id="vegetable-rice",
                event_type=InteractionType.CONSUME,
                servings=1,
                source="user_confirmation",
                confidence=1.0,
                occurred_at=utc_now(),
            ),
            SimpleNamespace(
                recipe_id="asked-recipe",
                event_type=InteractionType.QUERY,
                servings=None,
                source="chat",
                confidence=None,
                occurred_at=utc_now(),
            ),
        ]
        return [item for item in items if item.event_type in (event_types or set())]


def _nutrition_expert() -> NutritionPlanningExpert:
    history = MealHistoryService(_Interactions())  # type: ignore[arg-type]
    nutrition = NutritionService(
        NutritionCatalog(
            [
                RecipeNutritionData(
                    recipe_id="vegetable-rice",
                    serving_size=1,
                    calories_kcal=350,
                    protein_g=12,
                    fiber_g=8,
                    food_categories=("蔬菜", "全谷物"),
                    source="test-source-v1",
                    quality=NutritionDataQuality.VERIFIED,
                    calculation_version="v1",
                )
            ]
        )
    )
    tools = create_nutrition_service_tools(history, nutrition)
    return NutritionPlanningExpert(ToolRegistry(tools))


def _board(route: RouteType) -> CollaborationBlackboard:
    return CollaborationBlackboard(
        run_id=f"run-{route.value.lower()}",
        user_id=5,
        session_id="nutrition-session",
        user_input="根据我确认吃过的记录生成营养概览并推荐下一餐",
        route=RouteDecision(
            route=route,
            confidence=1.0,
            reason="nutrition request",
            requires_meal_history=True,
            requires_multiple_experts=route is RouteType.COMPLEX,
        ),
    )


def test_nutrition_expert_publishes_source_aware_json_report() -> None:
    outcome = RecipeCoordinator(
        ExpertRegistry([_nutrition_expert()])
    ).coordinate(_board(RouteType.NUTRITION_PLANNING))

    assert outcome.status is CoordinationStatus.SUCCEEDED
    assert outcome.blackboard.artifacts_for(kind=ArtifactKind.MEAL_HISTORY)
    assert outcome.blackboard.artifacts_for(kind=ArtifactKind.NUTRITION_SUMMARY)
    assert outcome.blackboard.artifacts_for(kind=ArtifactKind.NUTRITION_GOAL)
    report = outcome.blackboard.artifacts_for(kind=ArtifactKind.REPORT_DRAFT)[0]
    assert report.payload["data_basis"] == ("CONSUME",)
    assert report.payload["confirmed_meal_count"] == 1
    assert report.payload["metrics"]["calories"]["source"] == ("test-source-v1",)
    report_json = json.dumps(thaw_value(report.payload), ensure_ascii=False)
    assert "asked-recipe" not in report_json
    assert outcome.final_artifact.kind is ArtifactKind.RESPONSE_PLAN
    assert outcome.final_artifact.payload["medical_advice"] is False


def test_report_with_insufficient_data_contains_no_precise_metrics() -> None:
    summary = NutritionService.build_empty_summary()
    goal = NutritionService.build_goal(summary)
    history = ConfirmedMealHistory(
        user_id=5,
        included_event_types=(ConfirmedMealType.CONSUME,),
    )

    report = ReportService().create_draft(
        run_id="empty-report",
        title="空历史营养概览",
        history=history,
        summary=summary,
        goal=goal,
    )

    assert report.metrics == {}
    assert report.data_coverage == 0.0
    assert "食物类别与多样性" in report.observations[0]
    json.loads(report.model_dump_json())


class _DownstreamExpert:
    def __init__(self, name, capability):
        self.name = name
        self.capabilities = frozenset({capability})
        self.saw_nutrition_goal = False

    def execute(self, task, board):
        if task.capability is ExpertCapability.RECIPE_RECOMMENDATION:
            self.saw_nutrition_goal = bool(
                board.artifacts_for(kind=ArtifactKind.NUTRITION_GOAL)
            )
        kind = task.expected_artifacts[0]
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}",
            owner=self.name,
            kind=kind,
            payload={"source": "fake downstream", "task": task.title},
            confidence=1.0,
            task_id=task.id,
        )


def test_complex_flow_hands_nutrition_goal_to_recommendation() -> None:
    recommendation = _DownstreamExpert(
        "recommendation",
        ExpertCapability.RECIPE_RECOMMENDATION,
    )
    knowledge = _DownstreamExpert("knowledge", ExpertCapability.RECIPE_KNOWLEDGE)
    coordinator = RecipeCoordinator(
        ExpertRegistry([_nutrition_expert(), recommendation, knowledge])  # type: ignore[list-item]
    )

    outcome = coordinator.coordinate(_board(RouteType.COMPLEX))

    assert outcome.status is CoordinationStatus.SUCCEEDED
    assert recommendation.saw_nutrition_goal is True
    goal = outcome.blackboard.artifacts_for(kind=ArtifactKind.NUTRITION_GOAL)[0]
    assert goal.payload["based_on_confirmed_meals"] == 1
    assert outcome.final_artifact.kind is ArtifactKind.RESPONSE_PLAN
