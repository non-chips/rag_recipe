from __future__ import annotations

from dataclasses import dataclass, field

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.coordinator import (
    CollaborativeRecipeCoordinator,
    CoordinatorLimits,
    RecipeCoordinator,
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


def _candidate() -> dict:
    return {
        "recipe_id": "peanut-noodles",
        "recipe_name": "Peanut noodles",
        "ingredients": ("noodles", "peanut"),
        "tools": ("pot",),
        "cook_time_minutes": 15,
        "source_path": "recipes/peanut-noodles.md",
        "evidence": "Cook noodles and mix with peanut sauce.",
    }


@dataclass
class _CoordinatorExpert:
    name: str = "coordinator-expert"
    capabilities: frozenset[ExpertCapability] = frozenset(ExpertCapability)
    calls: list[str] = field(default_factory=list)
    failures_left: dict[str, int] = field(default_factory=dict)

    def decide(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> ClaimDecision:
        del board
        accepted = task.capability in self.capabilities
        return ClaimDecision(
            expert_name=self.name,
            accepted=accepted,
            confidence=1.0 if accepted else 0.0,
            reason=f"execute {task.id}" if accepted else "",
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

        candidate = _candidate()
        payloads = {
            "recommendation.extract_constraints": {},
            "recommendation.weather": {"available": True},
            "recommendation.preferences": {"allergens": ("peanut",)},
            "recommendation.retrieve": {
                "stage": "recalled",
                "candidates": (candidate,),
                "warnings": (),
            },
            "recommendation.rank": {
                "stage": "ranked",
                "candidates": (candidate,),
                "warnings": (),
            },
            "recommendation.validate": {
                "accepted": (candidate,),
                "rejected": (),
                "hard_constraints_applied": (),
            },
            "recommendation.response_plan": {
                "answer_mode": "constraint_checked_recommendation",
                "message": "Try peanut noodles.",
                "candidates": (candidate,),
            },
            "context.skills": {
                "selected_skill_refs": (),
                "signals": (),
                "risk": "LOW",
                "prompt_context": "# Active behavioral Skills\n- none",
                "selection_reason": "no trusted signals",
                "hard_constraints_authoritative": True,
            },
        }
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}:{len(self.calls)}",
            owner=self.name,
            kind=task.expected_artifacts[0],
            payload=payloads.get(task.id, {"task": task.id}),
            confidence=1.0,
            task_id=task.id,
        )


def _board(*, weather: bool = True) -> CollaborationBlackboard:
    return CollaborationBlackboard(
        run_id="coordinator-skill-run",
        user_id=1,
        session_id="coordinator-skill-session",
        user_input="recommend dinner",
        route=RouteDecision(
            route=RouteType.RECIPE_RECOMMENDATION,
            confidence=1.0,
            reason="test",
            requires_weather=weather,
        ),
    )


def test_coordinator_skill_context_precedes_proposal_and_is_a_dependency() -> None:
    outcome = CollaborativeRecipeCoordinator(
        ExpertRegistry([_CoordinatorExpert()])
    ).coordinate(_board())
    board = outcome.blackboard

    skill_task = board.tasks["context.skills"]
    proposal_task = board.tasks["quality.proposal.0"]
    assert skill_task.capability is ExpertCapability.SKILL_SELECTION
    assert skill_task.expected_artifacts == (ArtifactKind.SKILL_CONTEXT,)
    assert skill_task.depends_on == ("recommendation.response_plan",)
    assert proposal_task.depends_on == (
        "recommendation.response_plan",
        "context.skills",
    )

    opened = {
        event.task_id: event.sequence
        for event in board.events
        if event.event_type is EventType.TASK_OPENED
    }
    completed = {
        event.task_id: event.sequence
        for event in board.events
        if event.event_type is EventType.TASK_COMPLETED
    }
    assert completed["recommendation.response_plan"] < opened["context.skills"]
    assert completed["context.skills"] < opened["quality.proposal.0"]

    dependencies = tuple(
        board.tasks["quality.proposal.0"].metadata["artifact_dependencies"]
    )
    assert {
        "task_id": "context.skills",
        "kind": ArtifactKind.SKILL_CONTEXT.value,
    } in dependencies
    skill_artifact = board.artifact_for(
        task_id="context.skills",
        kind=ArtifactKind.SKILL_CONTEXT,
    )
    assert skill_artifact is not None
    assert skill_artifact.id in outcome.final_artifact.payload["references"]
    skill_trace_event = next(
        event
        for event in board.events
        if event.event_type is EventType.ARTIFACT_ADDED
        and event.task_id == "context.skills"
    )
    assert len(str(skill_trace_event.metadata["skill_context_hash"])) == 64
    assert "prompt_context" not in skill_trace_event.metadata


def test_coordinator_skill_context_is_not_duplicated_on_replay() -> None:
    coordinator = CollaborativeRecipeCoordinator(
        ExpertRegistry([_CoordinatorExpert()])
    )
    outcome = coordinator.coordinate(_board())

    replayed = coordinator.derive_missing_work(outcome.blackboard)
    replayed = coordinator.derive_missing_work(replayed)

    assert tuple(replayed.tasks).count("context.skills") == 1
    assert len(
        replayed.artifacts_for(
            task_id="context.skills",
            kind=ArtifactKind.SKILL_CONTEXT,
        )
    ) == 1


def test_coordinator_does_not_open_proposal_without_skill_artifact() -> None:
    coordinator = CollaborativeRecipeCoordinator(ExpertRegistry())
    board = _board(weather=False)
    for task in coordinator.build_tasks(board.route):
        board = board.add_task(
            AgentTask(
                id=task.id,
                title=task.title,
                capability=task.capability,
                status=TaskStatus.SUCCEEDED,
                priority=task.priority,
                depends_on=task.depends_on,
                expected_artifacts=task.expected_artifacts,
            )
        )
    board = board.add_task(
        AgentTask(
            id="context.skills",
            title="SelectSkillContext",
            capability=ExpertCapability.SKILL_SELECTION,
            status=TaskStatus.SUCCEEDED,
            depends_on=("recommendation.response_plan",),
            expected_artifacts=(ArtifactKind.SKILL_CONTEXT,),
        )
    )

    derived = coordinator.derive_missing_work(board)

    assert "quality.proposal.0" not in derived.tasks


def test_coordinator_budget_allows_weather_retry_and_one_revision() -> None:
    expert = _CoordinatorExpert()
    expert.failures_left["recommendation.retrieve"] = 1

    outcome = CollaborativeRecipeCoordinator(
        ExpertRegistry([expert])
    ).coordinate(_board())

    assert expert.calls.count("recommendation.retrieve") == 2
    assert outcome.steps_used == 13
    assert outcome.budget_used == 13
    assert outcome.steps_used <= CoordinatorLimits().max_steps
    assert outcome.budget_used <= CoordinatorLimits().max_budget
    assert "quality.revision.1" in outcome.blackboard.tasks
    assert not any(
        event.event_type is EventType.BUDGET_EXHAUSTED
        for event in outcome.blackboard.events
    )


def test_coordinator_budget_still_stops_excess_work() -> None:
    outcome = CollaborativeRecipeCoordinator(
        ExpertRegistry([_CoordinatorExpert()]),
        limits=CoordinatorLimits(max_steps=2, max_budget=2),
    ).coordinate(_board())

    assert any(
        event.event_type is EventType.BUDGET_EXHAUSTED
        for event in outcome.blackboard.events
    )
    assert outcome.steps_used == 2
    assert outcome.budget_used == 2


def test_fixed_coordinator_templates_remain_skill_free() -> None:
    tasks = RecipeCoordinator(ExpertRegistry()).build_tasks(_board().route)

    assert all(task.id != "context.skills" for task in tasks)
    assert all(
        task.capability is not ExpertCapability.SKILL_SELECTION
        for task in tasks
    )
