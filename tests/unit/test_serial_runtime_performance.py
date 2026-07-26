from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter, sleep

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.coordinator import (
    CollaborativeRecipeCoordinator,
    CoordinatorLimits,
)
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ClaimDecision,
    EventType,
    ExpertCapability,
    thaw_value,
)
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.agents.skills import SkillContextAgent
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.services.skills import SkillRegistry


_SKILL_AGENT = SkillContextAgent(
    SkillRegistry.load(Path(__file__).resolve().parents[2] / "skills")
)


def _expert_registry(expert) -> ExpertRegistry:
    return ExpertRegistry([expert, _SKILL_AGENT])


_CANDIDATE = {
    "recipe_id": "tomato-noodles",
    "recipe_name": "Tomato noodles",
    "ingredients": ("tomato", "noodles"),
    "tools": ("pot",),
    "cook_time_minutes": 15,
    "source_path": "recipes/tomato-noodles.md",
    "evidence": "Cook the noodles and tomato sauce.",
}


@dataclass
class _TimedRecommendationExpert:
    name: str = "timed_recommendation"
    capabilities: frozenset[ExpertCapability] = frozenset(
        {ExpertCapability.RECIPE_RECOMMENDATION}
    )
    delays: dict[str, float] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def decide(self, task: AgentTask, board) -> ClaimDecision:
        del board
        return ClaimDecision(
            expert_name=self.name,
            accepted=True,
            confidence=1.0,
            reason=f"serial claim for {task.id}",
        )

    def execute(self, task: AgentTask, board) -> AgentArtifact:
        self.calls.append(task.id)
        delay = self.delays.get(task.id, 0.0)
        if delay:
            sleep(delay)
        payloads = {
            "recommendation.extract_constraints": {},
            "recommendation.weather": {"available": True, "city": "test"},
            "recommendation.preferences": {},
            "recommendation.retrieve": {
                "stage": "recalled",
                "candidates": (_CANDIDATE,),
                "warnings": (),
            },
            "recommendation.rank": {
                "stage": "ranked",
                "candidates": (_CANDIDATE,),
                "warnings": (),
            },
            "recommendation.validate": {
                "accepted": (_CANDIDATE,),
                "rejected": (),
                "hard_constraints_applied": ("data_source",),
            },
            "recommendation.response_plan": {
                "answer_mode": "constraint_checked_recommendation",
                "message": "Safe grounded recommendation.",
                "candidates": (_CANDIDATE,),
            },
        }
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}",
            owner=self.name,
            kind=task.expected_artifacts[0],
            payload=payloads[task.id],
            confidence=1.0,
            task_id=task.id,
        )


def _board() -> CollaborationBlackboard:
    return CollaborationBlackboard(
        run_id="serial-performance-run",
        user_id=1,
        session_id="serial-performance-session",
        user_input="recommend dinner in test city",
        route=RouteDecision(
            route=RouteType.RECIPE_RECOMMENDATION,
            confidence=1.0,
            reason="test",
            requires_weather=True,
        ),
    )


def _normalized_trace(outcome) -> list[tuple]:
    return [
        (
            event.event_type.value,
            event.actor,
            event.task_id,
            event.artifact_id,
            event.message,
            {
                key: thaw_value(value)
                for key, value in event.metadata.items()
                if key != "duration_ms"
            },
        )
        for event in outcome.blackboard.events
    ]


def _normalized_artifacts(outcome) -> list[tuple]:
    return [
        (
            artifact.id,
            artifact.owner,
            artifact.kind.value,
            artifact.task_id,
            thaw_value(artifact.payload),
            artifact.confidence,
            artifact.review_of,
            artifact.revision_of,
        )
        for artifact in outcome.blackboard.artifacts
    ]


def test_single_writer_order_and_outputs_are_repeatable() -> None:
    first = CollaborativeRecipeCoordinator(
        _expert_registry(_TimedRecommendationExpert()),
        limits=CoordinatorLimits(max_claims_per_round=4),
    ).coordinate(_board())
    second = CollaborativeRecipeCoordinator(
        _expert_registry(_TimedRecommendationExpert()),
        limits=CoordinatorLimits(max_claims_per_round=4),
    ).coordinate(_board())

    assert _normalized_trace(first) == _normalized_trace(second)
    assert _normalized_artifacts(first) == _normalized_artifacts(second)
    assert thaw_value(first.final_artifact.payload) == thaw_value(
        second.final_artifact.payload
    )

    active_task = ""
    for event in first.blackboard.events:
        if event.event_type is EventType.TASK_CLAIMED:
            assert not active_task
            active_task = event.task_id
        elif event.event_type in {
            EventType.TASK_COMPLETED,
            EventType.TASK_FAILED,
        }:
            if event.task_id == active_task:
                if event.event_type is EventType.TASK_COMPLETED:
                    assert event.metadata["duration_ms"] >= 0
                active_task = ""
    assert not active_task


def test_independent_io_remains_at_serial_baseline_without_parallel_overhead() -> None:
    delays = {
        "recommendation.weather": 0.01,
        "recommendation.preferences": 0.01,
    }
    started = perf_counter()
    outcome = CollaborativeRecipeCoordinator(
        _expert_registry(_TimedRecommendationExpert(delays=delays))
    ).coordinate(_board())
    elapsed = perf_counter() - started

    serial_baseline = sum(delays.values())
    assert outcome.final_artifact.kind is ArtifactKind.RESPONSE_PROPOSAL
    assert elapsed >= serial_baseline
    assert elapsed < serial_baseline + 0.15


def test_io_deadline_produces_deterministic_weather_fallback() -> None:
    outcome = CollaborativeRecipeCoordinator(
        _expert_registry(
            _TimedRecommendationExpert(
                delays={"recommendation.weather": 0.01}
            )
        ),
        limits=CoordinatorLimits(io_timeout_seconds=0.001),
    ).coordinate(_board())

    weather = outcome.blackboard.artifact_for(
        task_id="recommendation.weather",
        kind=ArtifactKind.WEATHER_CONTEXT,
    )
    assert weather is not None
    assert weather.payload["available"] is False
    assert any("I/O deadline" in warning for warning in outcome.warnings)
    assert any(
        event.event_type is EventType.FALLBACK_APPLIED
        and event.task_id == "recommendation.weather"
        for event in outcome.blackboard.events
    )
