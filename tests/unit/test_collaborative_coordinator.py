from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.coordinator import (
    CollaborativeRecipeCoordinator,
    CoordinationStatus,
    CoordinatorLimits,
)
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ClaimDecision,
    EventType,
    ExpertCapability,
    TaskStatus,
)
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType


@dataclass
class _ClaimingExpert:
    name: str
    capabilities: frozenset[ExpertCapability]
    confidence: float = 1.0
    calls: list[str] = field(default_factory=list)
    failures_left: dict[str, int] = field(default_factory=dict)

    def decide(self, task: AgentTask, board: CollaborationBlackboard) -> ClaimDecision:
        del board
        accepted = task.capability in self.capabilities
        return ClaimDecision(
            expert_name=self.name,
            accepted=accepted,
            confidence=self.confidence if accepted else 0.0,
            reason=f"{self.name} claims {task.id}" if accepted else "",
        )

    def execute(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        self.calls.append(task.id)
        remaining = self.failures_left.get(task.id, 0)
        if remaining:
            self.failures_left[task.id] = remaining - 1
            raise RuntimeError(f"temporary failure for {task.id}")
        kind = task.expected_artifacts[0]
        payload = {"task": task.id}
        if kind is ArtifactKind.QUERY_CONSTRAINTS:
            payload = {}
        elif kind is ArtifactKind.USER_PREFERENCE_CONTEXT:
            payload = {}
        elif kind is ArtifactKind.WEATHER_CONTEXT:
            payload = {"available": False}
        elif kind is ArtifactKind.CONSTRAINT_VALIDATION:
            payload = {
                "accepted": (),
                "rejected": (),
                "hard_constraints_applied": (),
            }
        elif kind is ArtifactKind.SKILL_CONTEXT:
            payload = {
                "selected_skill_refs": (),
                "signals": (),
                "risk": "LOW",
                "prompt_context": "# Active behavioral Skills\n- none",
                "selection_reason": "no trusted signals",
                "hard_constraints_authoritative": True,
            }
        elif kind is ArtifactKind.RESPONSE_PLAN:
            payload = {"message": "safe structured response plan"}
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}:{len(self.calls)}",
            owner=self.name,
            kind=kind,
            payload=payload,
            confidence=0.9,
            task_id=task.id,
        )


def _board(route: RouteType, *, weather: bool = False) -> CollaborationBlackboard:
    return CollaborationBlackboard(
        run_id=f"collaborative-{route.value.lower()}",
        user_id=1,
        session_id="collaborative-session",
        user_input="test query",
        route=RouteDecision(
            route=route,
            confidence=0.9,
            reason="test",
            requires_weather=weather,
        ),
    )


def _all_capabilities(name: str = "all", confidence: float = 1.0) -> _ClaimingExpert:
    return _ClaimingExpert(name, frozenset(ExpertCapability), confidence)


@pytest.mark.parametrize(
    ("route", "weather"),
    [
        (RouteType.RECIPE_KNOWLEDGE, False),
        (RouteType.RECIPE_RECOMMENDATION, True),
        (RouteType.NUTRITION_PLANNING, False),
        (RouteType.COMPLEX, False),
    ],
)
def test_collaborative_mode_derives_and_completes_all_routes(
    route: RouteType,
    weather: bool,
) -> None:
    expert = _all_capabilities()
    outcome = CollaborativeRecipeCoordinator(
        ExpertRegistry([expert])
    ).coordinate(_board(route, weather=weather))

    assert outcome.status is CoordinationStatus.SUCCEEDED
    assert outcome.final_artifact.kind is ArtifactKind.RESPONSE_PROPOSAL
    assert all(
        task.status is TaskStatus.SUCCEEDED
        for task in outcome.blackboard.tasks.values()
    )
    assert any(
        event.event_type is EventType.TASK_OPENED
        for event in outcome.blackboard.events
    )


def test_claim_confidence_selects_expert_not_registration_order() -> None:
    first = _all_capabilities("registered-first", 0.2)
    winner = _all_capabilities("claim-winner", 0.9)

    outcome = CollaborativeRecipeCoordinator(
        ExpertRegistry([first, winner])
    ).coordinate(_board(RouteType.RECIPE_KNOWLEDGE))

    assert not first.calls
    assert winner.calls
    claim = next(
        event
        for event in outcome.blackboard.events
        if event.event_type is EventType.TASK_CLAIMED
    )
    assert claim.actor == "claim-winner"
    assert claim.metadata["confidence"] == 0.9
    assert "claims" in claim.message


def test_retrieval_failure_retries_once_and_stops() -> None:
    expert = _all_capabilities()
    expert.failures_left["knowledge.retrieve"] = 2

    outcome = CollaborativeRecipeCoordinator(
        ExpertRegistry([expert])
    ).coordinate(_board(RouteType.RECIPE_KNOWLEDGE))

    assert expert.calls.count("knowledge.retrieve") == 2
    assert outcome.blackboard.tasks["knowledge.retrieve"].status is TaskStatus.FAILED
    assert outcome.blackboard.tasks["knowledge.evidence_check"].status is TaskStatus.SKIPPED
    retry_events = [
        event
        for event in outcome.blackboard.events
        if event.event_type is EventType.FALLBACK_APPLIED
        and event.task_id == "knowledge.retrieve"
    ]
    assert len(retry_events) == 1


@pytest.mark.parametrize(
    ("failed_task", "fallback_kind"),
    [
        ("recommendation.weather", ArtifactKind.WEATHER_CONTEXT),
        (
            "recommendation.preferences",
            ArtifactKind.USER_PREFERENCE_CONTEXT,
        ),
    ],
)
def test_optional_context_failure_publishes_traced_fallback(
    failed_task: str,
    fallback_kind: ArtifactKind,
) -> None:
    expert = _all_capabilities()
    expert.failures_left[failed_task] = 1

    outcome = CollaborativeRecipeCoordinator(
        ExpertRegistry([expert])
    ).coordinate(_board(RouteType.RECIPE_RECOMMENDATION, weather=True))

    fallback = outcome.blackboard.artifact_for(
        task_id=failed_task,
        kind=fallback_kind,
    )
    assert fallback is not None
    assert fallback.metadata["degraded"] is True
    assert outcome.blackboard.tasks[failed_task].status is TaskStatus.SUCCEEDED
    assert any(
        event.event_type is EventType.FALLBACK_APPLIED
        and event.task_id == failed_task
        for event in outcome.blackboard.events
    )


def test_no_claim_and_budget_exhaustion_are_traced() -> None:
    no_claim = CollaborativeRecipeCoordinator(ExpertRegistry()).coordinate(
        _board(RouteType.RECIPE_KNOWLEDGE)
    )
    budget = CollaborativeRecipeCoordinator(
        ExpertRegistry([_all_capabilities()]),
        limits=CoordinatorLimits(max_steps=1, max_budget=1),
    ).coordinate(_board(RouteType.RECIPE_KNOWLEDGE))

    assert any(
        event.event_type is EventType.NO_CLAIM
        for event in no_claim.blackboard.events
    )
    assert any(
        event.event_type is EventType.TASK_SKIPPED
        and "dependencies failed" in event.message
        for event in no_claim.blackboard.events
    )
    assert any(
        event.event_type is EventType.BUDGET_EXHAUSTED
        for event in budget.blackboard.events
    )


def test_round_and_agent_claim_limits_terminate_with_trace() -> None:
    expert = _all_capabilities()
    outcome = CollaborativeRecipeCoordinator(
        ExpertRegistry([expert]),
        limits=CoordinatorLimits(
            max_rounds=1,
            max_claims_per_round=1,
            max_claims_per_agent=1,
        ),
    ).coordinate(_board(RouteType.RECIPE_KNOWLEDGE))

    assert len(expert.calls) == 1
    assert any(
        event.event_type is EventType.ROUND_LIMIT_REACHED
        for event in outcome.blackboard.events
    )
