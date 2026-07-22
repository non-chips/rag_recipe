from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.coordinator import (
    CoordinationStatus,
    CoordinatorLimits,
    RecipeCoordinator,
)
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    EventType,
    ExpertCapability,
    TaskStatus,
)
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType


@dataclass
class _FakeExpert:
    name: str
    capabilities: frozenset[ExpertCapability]
    calls: list[str] = field(default_factory=list)
    fail_tasks: set[str] = field(default_factory=set)
    omit_tasks: set[str] = field(default_factory=set)

    def execute(self, task: AgentTask, blackboard: CollaborationBlackboard):
        del blackboard
        self.calls.append(task.id)
        if task.id in self.fail_tasks:
            raise RuntimeError(f"fake failure for {task.id}")
        if task.id in self.omit_tasks:
            return ()
        kind = task.expected_artifacts[0]
        return AgentArtifact(
            id=f"{task.id}:artifact",
            owner=self.name,
            kind=kind,
            payload={"task": task.id, "kind": kind.value},
            confidence=0.9,
            task_id=task.id,
        )


def _decision(route: RouteType, **flags) -> RouteDecision:
    return RouteDecision(route=route, confidence=0.9, reason="test", **flags)


def _board(decision: RouteDecision) -> CollaborationBlackboard:
    return CollaborationBlackboard(
        run_id="run-coordinator",
        user_id=1,
        session_id="session-coordinator",
        user_input="test query",
        route=decision,
    )


def _experts():
    knowledge = _FakeExpert(
        "knowledge", frozenset({ExpertCapability.RECIPE_KNOWLEDGE})
    )
    recommendation = _FakeExpert(
        "recommendation", frozenset({ExpertCapability.RECIPE_RECOMMENDATION})
    )
    nutrition = _FakeExpert(
        "nutrition", frozenset({ExpertCapability.NUTRITION_PLANNING})
    )
    return knowledge, recommendation, nutrition


def test_fixed_templates_cover_four_business_routes() -> None:
    coordinator = RecipeCoordinator(ExpertRegistry())

    knowledge = coordinator.build_tasks(_decision(RouteType.RECIPE_KNOWLEDGE))
    recommendation = coordinator.build_tasks(
        _decision(RouteType.RECIPE_RECOMMENDATION, requires_weather=True)
    )
    nutrition = coordinator.build_tasks(_decision(RouteType.NUTRITION_PLANNING))
    complex_tasks = coordinator.build_tasks(_decision(RouteType.COMPLEX))

    assert [task.title for task in knowledge] == [
        "ExtractConstraints",
        "RetrieveRecipeKnowledge",
        "EvidenceCheck",
        "BuildResponsePlan",
    ]
    assert "GetWeather" in [task.title for task in recommendation]
    assert nutrition[0].expected_artifacts == (ArtifactKind.MEAL_HISTORY,)
    assert [task.capability for task in complex_tasks[:3]] == [
        ExpertCapability.NUTRITION_PLANNING,
        ExpertCapability.RECIPE_RECOMMENDATION,
        ExpertCapability.RECIPE_KNOWLEDGE,
    ]
    with pytest.raises(ValueError, match="SIMPLE"):
        coordinator.build_tasks(_decision(RouteType.SIMPLE))


def test_coordinator_executes_dependencies_and_selects_existing_response_plan() -> None:
    knowledge, recommendation, nutrition = _experts()
    coordinator = RecipeCoordinator(
        ExpertRegistry([knowledge, recommendation, nutrition])
    )

    outcome = coordinator.coordinate(_board(_decision(RouteType.RECIPE_KNOWLEDGE)))

    assert outcome.status is CoordinationStatus.SUCCEEDED
    assert knowledge.calls == [
        "knowledge.extract_constraints",
        "knowledge.retrieve",
        "knowledge.evidence_check",
        "knowledge.response_plan",
    ]
    assert all(
        task.status is TaskStatus.SUCCEEDED
        for task in outcome.blackboard.tasks.values()
    )
    assert outcome.final_artifact.kind is ArtifactKind.RESPONSE_PLAN
    assert outcome.final_artifact.id in {
        artifact.id for artifact in outcome.blackboard.artifacts
    }
    assert outcome.blackboard.events[-1].event_type is EventType.FINAL_SELECTED


def test_complex_route_uses_experts_in_fixed_dependency_order() -> None:
    knowledge, recommendation, nutrition = _experts()
    coordinator = RecipeCoordinator(
        ExpertRegistry([knowledge, recommendation, nutrition])
    )

    outcome = coordinator.coordinate(_board(_decision(RouteType.COMPLEX)))

    started = [
        event.task_id
        for event in outcome.blackboard.events
        if event.event_type is EventType.TASK_STARTED
    ]
    assert started == [
        "complex.nutrition_goal",
        "complex.recipe_candidates",
        "complex.recipe_evidence",
        "complex.validate",
        "complex.response_plan",
    ]


def test_missing_artifact_fails_task_skips_dependents_and_degrades() -> None:
    knowledge, recommendation, nutrition = _experts()
    knowledge.omit_tasks.add("knowledge.retrieve")
    coordinator = RecipeCoordinator(
        ExpertRegistry([knowledge, recommendation, nutrition])
    )

    outcome = coordinator.coordinate(_board(_decision(RouteType.RECIPE_KNOWLEDGE)))

    assert outcome.status is CoordinationStatus.DEGRADED
    assert outcome.blackboard.tasks["knowledge.retrieve"].status is TaskStatus.FAILED
    assert outcome.blackboard.tasks["knowledge.evidence_check"].status is TaskStatus.SKIPPED
    assert outcome.final_artifact.kind is ArtifactKind.ERROR
    assert any(
        event.event_type is EventType.MISSING_ARTIFACT
        for event in outcome.blackboard.events
    )


def test_expert_failure_and_missing_expert_both_degrade() -> None:
    knowledge, _recommendation, _nutrition = _experts()
    knowledge.fail_tasks.add("knowledge.extract_constraints")
    failed = RecipeCoordinator(ExpertRegistry([knowledge])).coordinate(
        _board(_decision(RouteType.RECIPE_KNOWLEDGE))
    )
    missing = RecipeCoordinator(ExpertRegistry()).coordinate(
        _board(_decision(RouteType.RECIPE_KNOWLEDGE))
    )

    assert failed.status is CoordinationStatus.DEGRADED
    assert missing.status is CoordinationStatus.DEGRADED
    assert failed.final_artifact.kind is ArtifactKind.ERROR
    assert missing.final_artifact.kind is ArtifactKind.ERROR
    assert any("fake failure" in warning for warning in failed.warnings)
    assert any("no expert registered" in warning for warning in missing.warnings)


def test_step_and_cost_budget_are_bounded() -> None:
    knowledge, recommendation, nutrition = _experts()
    coordinator = RecipeCoordinator(
        ExpertRegistry([knowledge, recommendation, nutrition]),
        limits=CoordinatorLimits(max_steps=2, max_budget=2),
    )

    outcome = coordinator.coordinate(_board(_decision(RouteType.RECIPE_KNOWLEDGE)))

    assert outcome.steps_used == 2
    assert outcome.budget_used == 2
    assert outcome.status is CoordinationStatus.DEGRADED
    assert len(knowledge.calls) == 2
    assert any(
        event.event_type is EventType.BUDGET_EXHAUSTED
        for event in outcome.blackboard.events
    )
