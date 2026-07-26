from __future__ import annotations

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ExpertCapability,
    TaskStatus,
)
from recipe_assistant.agents.experts.recipe_knowledge import (
    KnowledgeConstraints,
    KnowledgeTopic,
)
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.schemas.nutrition import NutritionGoal, NutritionSummary
from recipe_assistant.services.constraint import (
    ConstraintValidationResult,
    PreferenceContext,
    RecipeCandidate,
    RejectedCandidate,
    TemporaryConstraints,
)
from recipe_assistant.services.skill_signals import SkillSignalExtractor
from recipe_assistant.services.skills import SkillSignal
from recipe_assistant.services.weather import WeatherContext


def _board(
    *,
    route: RouteType = RouteType.RECIPE_RECOMMENDATION,
    user_input: str = "推荐一道家常菜",
    requires_weather: bool = False,
    artifacts: tuple[tuple[ArtifactKind, object], ...] = (),
    task_status: TaskStatus = TaskStatus.SUCCEEDED,
) -> CollaborationBlackboard:
    tasks: dict[str, AgentTask] = {}
    published: list[AgentArtifact] = []
    for index, (kind, payload) in enumerate(artifacts):
        task_id = f"task.{index}"
        tasks[task_id] = AgentTask(
            id=task_id,
            title=f"Publish{kind.value}",
            capability=ExpertCapability.RECIPE_RECOMMENDATION,
            status=task_status,
            expected_artifacts=(kind,),
            claimed_by="fixture" if task_status is TaskStatus.SUCCEEDED else "",
            claim_confidence=1.0 if task_status is TaskStatus.SUCCEEDED else None,
            claim_reason="fixture artifact" if task_status is TaskStatus.SUCCEEDED else "",
        )
        data = (
            payload.model_dump(mode="json")
            if hasattr(payload, "model_dump")
            else payload
        )
        published.append(
            AgentArtifact(
                id=f"artifact.{index}",
                owner="fixture",
                kind=kind,
                payload=data,
                confidence=1.0,
                task_id=task_id,
            )
        )
    return CollaborationBlackboard(
        run_id="run-signals",
        user_id=1,
        session_id="session-signals",
        user_input=user_input,
        route=RouteDecision(
            route=route,
            confidence=1.0,
            reason="fixture route",
            requires_weather=requires_weather,
        ),
        tasks=tasks,
        artifacts=tuple(published),
    )


def _extract(board: CollaborationBlackboard) -> tuple[SkillSignal, ...]:
    return SkillSignalExtractor().extract(board)


def _validation(*reasons: str, applied: tuple[str, ...] = ()) -> ConstraintValidationResult:
    rejected = (
        RejectedCandidate(
            candidate=RecipeCandidate(recipe_id="recipe-1"),
            reasons=tuple(reasons),
        ),
    ) if reasons else ()
    return ConstraintValidationResult(
        rejected=rejected,
        hard_constraints_applied=applied,
    )


def test_allergy_signal_from_preference_artifact() -> None:
    board = _board(
        artifacts=(
            (
                ArtifactKind.USER_PREFERENCE_CONTEXT,
                PreferenceContext(allergens=("花生",)),
            ),
        )
    )

    assert _extract(board) == (SkillSignal.ALLERGY_MENTIONED,)


def test_allergy_signal_absent_for_empty_preferences() -> None:
    board = _board(
        artifacts=(
            (ArtifactKind.USER_PREFERENCE_CONTEXT, PreferenceContext()),
        )
    )

    assert SkillSignal.ALLERGY_MENTIONED not in _extract(board)


def test_allergy_signal_tolerates_malformed_preference_schema() -> None:
    board = _board(
        artifacts=(
            (ArtifactKind.USER_PREFERENCE_CONTEXT, {"allergens": "花生"}),
        )
    )

    assert SkillSignal.ALLERGY_MENTIONED not in _extract(board)


def test_allergy_signal_from_validation_applied_or_conflict() -> None:
    applied = _board(
        artifacts=(
            (
                ArtifactKind.CONSTRAINT_VALIDATION,
                _validation(applied=("allergens",)),
            ),
        )
    )
    conflict = _board(
        artifacts=(
            (
                ArtifactKind.CONSTRAINT_VALIDATION,
                _validation("allergen_conflict"),
            ),
        )
    )

    assert SkillSignal.ALLERGY_MENTIONED in _extract(applied)
    assert SkillSignal.ALLERGY_MENTIONED in _extract(conflict)


def test_excluded_signal_from_recommendation_constraints() -> None:
    board = _board(
        artifacts=(
            (
                ArtifactKind.QUERY_CONSTRAINTS,
                TemporaryConstraints(excluded_ingredients=("香菜",)),
            ),
        )
    )

    assert SkillSignal.EXCLUDED_INGREDIENT_PRESENT in _extract(board)


def test_excluded_signal_from_knowledge_constraints() -> None:
    board = _board(
        route=RouteType.RECIPE_KNOWLEDGE,
        artifacts=(
            (
                ArtifactKind.QUERY_CONSTRAINTS,
                KnowledgeConstraints(
                    query="不要牛奶",
                    topics=(KnowledgeTopic.INGREDIENTS,),
                    exclude_ingredients=("牛奶",),
                ),
            ),
        ),
    )

    assert SkillSignal.EXCLUDED_INGREDIENT_PRESENT in _extract(board)


def test_excluded_signal_absent_for_empty_or_malformed_constraints() -> None:
    empty = _board(
        artifacts=(
            (ArtifactKind.QUERY_CONSTRAINTS, TemporaryConstraints()),
        )
    )
    malformed = _board(
        artifacts=(
            (ArtifactKind.QUERY_CONSTRAINTS, {"excluded_ingredients": "香菜"}),
        )
    )

    assert SkillSignal.EXCLUDED_INGREDIENT_PRESENT not in _extract(empty)
    assert SkillSignal.EXCLUDED_INGREDIENT_PRESENT not in _extract(malformed)


def test_excluded_signal_from_validation_conflict() -> None:
    board = _board(
        artifacts=(
            (
                ArtifactKind.CONSTRAINT_VALIDATION,
                _validation("excluded_ingredient_conflict"),
            ),
        )
    )

    assert SkillSignal.EXCLUDED_INGREDIENT_PRESENT in _extract(board)


def test_substitution_signal_prefers_structured_knowledge_topic() -> None:
    board = _board(
        route=RouteType.RECIPE_KNOWLEDGE,
        artifacts=(
            (
                ArtifactKind.QUERY_CONSTRAINTS,
                KnowledgeConstraints(
                    query="牛奶可以换成豆浆吗",
                    topics=(KnowledgeTopic.SUBSTITUTION,),
                ),
            ),
        ),
    )

    assert SkillSignal.SUBSTITUTION_REQUESTED in _extract(board)


def test_substitution_fallback_is_current_turn_only_and_conservative() -> None:
    positive = _board(user_input="牛奶可以用豆浆代替吗")
    ordinary_change = _board(user_input="这道不喜欢，换个菜")

    assert SkillSignal.SUBSTITUTION_REQUESTED in _extract(positive)
    assert SkillSignal.SUBSTITUTION_REQUESTED not in _extract(ordinary_change)


def test_substitution_signal_tolerates_missing_or_malformed_schema() -> None:
    missing = _board(user_input="普通菜谱问题")
    malformed = _board(
        route=RouteType.RECIPE_KNOWLEDGE,
        user_input="牛奶可以用豆浆代替吗",
        artifacts=(
            (ArtifactKind.QUERY_CONSTRAINTS, {"topics": ["substitution"]}),
        ),
    )

    assert SkillSignal.SUBSTITUTION_REQUESTED not in _extract(missing)
    assert SkillSignal.SUBSTITUTION_REQUESTED not in _extract(malformed)


def test_weather_signal_from_route_flag_and_complex_weather_artifact() -> None:
    flagged = _board(requires_weather=True)
    artifact = _board(
        route=RouteType.COMPLEX,
        artifacts=(
            (
                ArtifactKind.WEATHER_CONTEXT,
                WeatherContext(available=True, city="上海", condition="晴"),
            ),
        ),
    )

    assert SkillSignal.WEATHER_CONTEXT_REQUIRED in _extract(flagged)
    assert SkillSignal.WEATHER_CONTEXT_REQUIRED in _extract(artifact)


def test_weather_signal_absent_without_flag_or_valid_artifact() -> None:
    missing = _board()
    malformed = _board(
        route=RouteType.COMPLEX,
        artifacts=(
            (ArtifactKind.WEATHER_CONTEXT, {"city": "上海"}),
        ),
    )

    assert SkillSignal.WEATHER_CONTEXT_REQUIRED not in _extract(missing)
    assert SkillSignal.WEATHER_CONTEXT_REQUIRED not in _extract(malformed)


def test_nutrition_signal_requires_route_and_structured_artifact() -> None:
    summary = NutritionSummary(
        confirmed_meal_count=0,
        distinct_recipe_count=0,
        data_coverage=0.0,
        precise_metrics_available=False,
        calculation_version="1.0.0",
    )
    nutrition = _board(
        route=RouteType.NUTRITION_PLANNING,
        artifacts=((ArtifactKind.NUTRITION_SUMMARY, summary),),
    )
    complex_goal = _board(
        route=RouteType.COMPLEX,
        artifacts=(
            (
                ArtifactKind.NUTRITION_GOAL,
                NutritionGoal(
                    mode="diversity",
                    target_recipe_diversity=3,
                    based_on_confirmed_meals=1,
                ),
            ),
        ),
    )

    assert SkillSignal.NUTRITION_REPORT_REQUESTED in _extract(nutrition)
    assert SkillSignal.NUTRITION_REPORT_REQUESTED in _extract(complex_goal)


def test_nutrition_signal_does_not_trigger_early_or_on_wrong_schema() -> None:
    no_artifact = _board(
        route=RouteType.NUTRITION_PLANNING,
        user_input="分析一下营养",
    )
    wrong_route = _board(
        route=RouteType.RECIPE_RECOMMENDATION,
        artifacts=(
            (
                ArtifactKind.NUTRITION_GOAL,
                NutritionGoal(
                    mode="diversity",
                    target_recipe_diversity=3,
                    based_on_confirmed_meals=1,
                ),
            ),
        ),
    )
    malformed = _board(
        route=RouteType.NUTRITION_PLANNING,
        artifacts=((ArtifactKind.NUTRITION_SUMMARY, {"data_coverage": 1.0}),),
    )

    assert SkillSignal.NUTRITION_REPORT_REQUESTED not in _extract(no_artifact)
    assert SkillSignal.NUTRITION_REPORT_REQUESTED not in _extract(wrong_route)
    assert SkillSignal.NUTRITION_REPORT_REQUESTED not in _extract(malformed)


def test_failed_task_artifacts_are_not_trusted() -> None:
    board = _board(
        requires_weather=False,
        artifacts=(
            (
                ArtifactKind.USER_PREFERENCE_CONTEXT,
                PreferenceContext(allergens=("花生",)),
            ),
        ),
        task_status=TaskStatus.FAILED,
    )

    assert _extract(board) == ()


def test_multiple_signals_are_deduplicated_and_stably_sorted() -> None:
    board = _board(
        route=RouteType.COMPLEX,
        user_input="牛奶可以用豆浆代替吗",
        requires_weather=True,
        artifacts=(
            (
                ArtifactKind.USER_PREFERENCE_CONTEXT,
                PreferenceContext(allergens=("花生",)),
            ),
            (
                ArtifactKind.QUERY_CONSTRAINTS,
                KnowledgeConstraints(
                    query="不要牛奶，牛奶可以用豆浆代替吗",
                    topics=(KnowledgeTopic.SUBSTITUTION,),
                    exclude_ingredients=("牛奶",),
                ),
            ),
            (
                ArtifactKind.NUTRITION_GOAL,
                NutritionGoal(
                    mode="diversity",
                    target_recipe_diversity=3,
                    based_on_confirmed_meals=1,
                ),
            ),
        ),
    )

    expected = (
        SkillSignal.ALLERGY_MENTIONED,
        SkillSignal.EXCLUDED_INGREDIENT_PRESENT,
        SkillSignal.NUTRITION_REPORT_REQUESTED,
        SkillSignal.SUBSTITUTION_REQUESTED,
        SkillSignal.WEATHER_CONTEXT_REQUIRED,
    )
    extractor = SkillSignalExtractor()

    assert extractor.extract(board) == expected
    assert extractor.extract(board) == expected
