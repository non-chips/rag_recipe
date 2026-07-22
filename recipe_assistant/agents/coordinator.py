"""Deterministic task templates and budgeted expert coordination."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentEvent,
    AgentTask,
    ArtifactKind,
    EventType,
    ExpertCapability,
    TaskPriority,
    TaskStatus,
)
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType


class CoordinationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class CoordinatorLimits:
    max_steps: int = 12
    max_budget: int = 12

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.max_budget < 1:
            raise ValueError("coordinator limits must be positive")


@dataclass(frozen=True, slots=True)
class CoordinatorOutcome:
    blackboard: CollaborationBlackboard
    status: CoordinationStatus
    steps_used: int
    budget_used: int
    warnings: tuple[str, ...] = ()

    @property
    def final_artifact(self) -> AgentArtifact:
        for artifact in self.blackboard.artifacts:
            if artifact.id == self.blackboard.final_artifact_id:
                return artifact
        raise RuntimeError("coordinator outcome has no selected artifact")


class RecipeCoordinator:
    """Execute fixed route templates without owning domain tools."""

    def __init__(
        self,
        registry: ExpertRegistry,
        limits: CoordinatorLimits | None = None,
    ) -> None:
        self.registry = registry
        self.limits = limits or CoordinatorLimits()

    def build_tasks(self, decision: RouteDecision) -> tuple[AgentTask, ...]:
        if decision.route is RouteType.RECIPE_KNOWLEDGE:
            return self._knowledge_tasks()
        if decision.route is RouteType.RECIPE_RECOMMENDATION:
            return self._recommendation_tasks(decision.requires_weather)
        if decision.route is RouteType.NUTRITION_PLANNING:
            return self._nutrition_tasks()
        if decision.route is RouteType.COMPLEX:
            return self._complex_tasks()
        raise ValueError("SIMPLE route must not enter the coordinator")

    def coordinate(self, blackboard: CollaborationBlackboard) -> CoordinatorOutcome:
        board = blackboard
        tasks = self.build_tasks(board.route)
        for task in tasks:
            board = board.add_task(task)

        warnings: list[str] = []
        steps_used = 0
        budget_used = 0
        budget_exhausted = False

        for task in tasks:
            if budget_exhausted:
                board = self._skip_task(board, task, "budget already exhausted")
                continue
            if not board.dependencies_succeeded(task):
                warning = f"task {task.id} skipped because a dependency did not succeed"
                warnings.append(warning)
                board = self._skip_task(board, task, warning)
                continue
            if (
                steps_used >= self.limits.max_steps
                or budget_used + task.estimated_cost > self.limits.max_budget
            ):
                budget_exhausted = True
                warning = f"budget exhausted before task {task.id}"
                warnings.append(warning)
                board = board.append_event(
                    AgentEvent(
                        event_type=EventType.BUDGET_EXHAUSTED,
                        actor="coordinator",
                        task_id=task.id,
                        message=warning,
                        metadata={
                            "steps_used": steps_used,
                            "budget_used": budget_used,
                        },
                    )
                )
                board = self._skip_task(board, task, warning)
                continue

            steps_used += 1
            budget_used += task.estimated_cost
            board = board.with_task_status(task.id, TaskStatus.RUNNING)
            board = board.append_event(
                AgentEvent(
                    event_type=EventType.TASK_STARTED,
                    actor="coordinator",
                    task_id=task.id,
                )
            )

            try:
                expert = self.registry.resolve(task.capability)
                artifacts = expert.execute(task, board)
                if isinstance(artifacts, AgentArtifact):
                    artifacts = (artifacts,)
                else:
                    artifacts = tuple(artifacts)
                for artifact in artifacts:
                    if artifact.task_id != task.id:
                        raise ValueError(
                            f"expert artifact task mismatch: {artifact.task_id} != {task.id}"
                        )
                    board = board.add_artifact(artifact)
                    board = board.append_event(
                        AgentEvent(
                            event_type=EventType.ARTIFACT_ADDED,
                            actor=expert.name,
                            task_id=task.id,
                            artifact_id=artifact.id,
                            metadata={"kind": artifact.kind.value},
                        )
                    )

                missing = tuple(
                    kind
                    for kind in task.expected_artifacts
                    if not board.artifacts_for(kind=kind, task_id=task.id)
                )
                if missing:
                    names = ", ".join(kind.value for kind in missing)
                    warning = f"task {task.id} did not publish required artifacts: {names}"
                    warnings.append(warning)
                    board = board.with_task_status(task.id, TaskStatus.FAILED)
                    board = board.append_event(
                        AgentEvent(
                            event_type=EventType.MISSING_ARTIFACT,
                            actor="coordinator",
                            task_id=task.id,
                            message=warning,
                        )
                    )
                    continue

                board = board.with_task_status(task.id, TaskStatus.SUCCEEDED)
                board = board.append_event(
                    AgentEvent(
                        event_type=EventType.TASK_COMPLETED,
                        actor=expert.name,
                        task_id=task.id,
                    )
                )
            except Exception as exc:
                warning = f"task {task.id} failed: {exc}"
                warnings.append(warning)
                board = board.with_task_status(task.id, TaskStatus.FAILED)
                board = board.append_event(
                    AgentEvent(
                        event_type=EventType.TASK_FAILED,
                        actor="coordinator",
                        task_id=task.id,
                        message=warning,
                        metadata={"error_type": type(exc).__name__},
                    )
                )

        response_plans = board.artifacts_for(kind=ArtifactKind.RESPONSE_PLAN)
        if response_plans:
            selected = max(response_plans, key=lambda artifact: artifact.confidence)
        else:
            warning = "no response plan was produced; selected a structured error artifact"
            warnings.append(warning)
            fallback_task = tasks[-1]
            selected = AgentArtifact(
                id=f"{board.run_id}:fallback",
                owner="coordinator",
                kind=ArtifactKind.ERROR,
                payload={
                    "message": "当前协作结果不完整，请基于已有信息降级回答或请求澄清。",
                    "warnings": warnings,
                },
                confidence=0.0,
                task_id=fallback_task.id,
                metadata={"degraded": True},
            )
            board = board.add_artifact(selected)
            board = board.append_event(
                AgentEvent(
                    event_type=EventType.DEGRADED,
                    actor="coordinator",
                    task_id=fallback_task.id,
                    artifact_id=selected.id,
                    message=warning,
                )
            )

        board = board.select_final(selected.id)
        status = CoordinationStatus.DEGRADED if warnings else CoordinationStatus.SUCCEEDED
        return CoordinatorOutcome(
            blackboard=board,
            status=status,
            steps_used=steps_used,
            budget_used=budget_used,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _skip_task(
        board: CollaborationBlackboard,
        task: AgentTask,
        reason: str,
    ) -> CollaborationBlackboard:
        board = board.with_task_status(task.id, TaskStatus.SKIPPED)
        return board.append_event(
            AgentEvent(
                event_type=EventType.TASK_SKIPPED,
                actor="coordinator",
                task_id=task.id,
                message=reason,
            )
        )

    @staticmethod
    def _task(
        task_id: str,
        title: str,
        capability: ExpertCapability,
        expected: ArtifactKind,
        depends_on: tuple[str, ...] = (),
        *,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> AgentTask:
        return AgentTask(
            id=task_id,
            title=title,
            capability=capability,
            priority=priority,
            depends_on=depends_on,
            expected_artifacts=(expected,),
        )

    def _knowledge_tasks(self) -> tuple[AgentTask, ...]:
        return (
            self._task(
                "knowledge.extract_constraints",
                "ExtractConstraints",
                ExpertCapability.RECIPE_KNOWLEDGE,
                ArtifactKind.QUERY_CONSTRAINTS,
            ),
            self._task(
                "knowledge.retrieve",
                "RetrieveRecipeKnowledge",
                ExpertCapability.RECIPE_KNOWLEDGE,
                ArtifactKind.RECIPE_EVIDENCE,
                ("knowledge.extract_constraints",),
            ),
            self._task(
                "knowledge.evidence_check",
                "EvidenceCheck",
                ExpertCapability.RECIPE_KNOWLEDGE,
                ArtifactKind.CONSTRAINT_VALIDATION,
                ("knowledge.retrieve",),
            ),
            self._task(
                "knowledge.response_plan",
                "BuildResponsePlan",
                ExpertCapability.RECIPE_KNOWLEDGE,
                ArtifactKind.RESPONSE_PLAN,
                ("knowledge.evidence_check",),
            ),
        )

    def _recommendation_tasks(self, requires_weather: bool) -> tuple[AgentTask, ...]:
        tasks = [
            self._task(
                "recommendation.extract_constraints",
                "ExtractConstraints",
                ExpertCapability.RECIPE_RECOMMENDATION,
                ArtifactKind.QUERY_CONSTRAINTS,
            )
        ]
        context_dependencies = ["recommendation.extract_constraints"]
        if requires_weather:
            tasks.append(
                self._task(
                    "recommendation.weather",
                    "GetWeather",
                    ExpertCapability.RECIPE_RECOMMENDATION,
                    ArtifactKind.WEATHER_CONTEXT,
                    ("recommendation.extract_constraints",),
                )
            )
            context_dependencies.append("recommendation.weather")
        tasks.append(
            self._task(
                "recommendation.preferences",
                "LoadPreferences",
                ExpertCapability.RECIPE_RECOMMENDATION,
                ArtifactKind.USER_PREFERENCE_CONTEXT,
                ("recommendation.extract_constraints",),
            )
        )
        context_dependencies.append("recommendation.preferences")
        tasks.extend(
            [
                self._task(
                    "recommendation.retrieve",
                    "RetrieveCandidates",
                    ExpertCapability.RECIPE_RECOMMENDATION,
                    ArtifactKind.RECIPE_CANDIDATES,
                    tuple(context_dependencies),
                ),
                self._task(
                    "recommendation.rank",
                    "RankCandidates",
                    ExpertCapability.RECIPE_RECOMMENDATION,
                    ArtifactKind.RECIPE_CANDIDATES,
                    ("recommendation.retrieve",),
                ),
                self._task(
                    "recommendation.validate",
                    "ValidateConstraints",
                    ExpertCapability.RECIPE_RECOMMENDATION,
                    ArtifactKind.CONSTRAINT_VALIDATION,
                    ("recommendation.rank",),
                ),
                self._task(
                    "recommendation.response_plan",
                    "BuildResponsePlan",
                    ExpertCapability.RECIPE_RECOMMENDATION,
                    ArtifactKind.RESPONSE_PLAN,
                    ("recommendation.validate",),
                ),
            ]
        )
        return tuple(tasks)

    def _nutrition_tasks(self) -> tuple[AgentTask, ...]:
        return (
            self._task(
                "nutrition.meal_history",
                "LoadConfirmedMealHistory",
                ExpertCapability.NUTRITION_PLANNING,
                ArtifactKind.MEAL_HISTORY,
            ),
            self._task(
                "nutrition.summary",
                "CalculateNutritionSummary",
                ExpertCapability.NUTRITION_PLANNING,
                ArtifactKind.NUTRITION_SUMMARY,
                ("nutrition.meal_history",),
            ),
            self._task(
                "nutrition.guidance",
                "BuildNutritionGuidance",
                ExpertCapability.NUTRITION_PLANNING,
                ArtifactKind.NUTRITION_GOAL,
                ("nutrition.summary",),
            ),
            self._task(
                "nutrition.response_plan",
                "BuildResponsePlan",
                ExpertCapability.NUTRITION_PLANNING,
                ArtifactKind.RESPONSE_PLAN,
                ("nutrition.guidance",),
            ),
        )

    def _complex_tasks(self) -> tuple[AgentTask, ...]:
        return (
            self._task(
                "complex.nutrition_goal",
                "NutritionPlanningExpert",
                ExpertCapability.NUTRITION_PLANNING,
                ArtifactKind.NUTRITION_GOAL,
                priority=TaskPriority.HIGH,
            ),
            self._task(
                "complex.recipe_candidates",
                "RecipeRecommendationExpert",
                ExpertCapability.RECIPE_RECOMMENDATION,
                ArtifactKind.RECIPE_CANDIDATES,
                ("complex.nutrition_goal",),
                priority=TaskPriority.HIGH,
            ),
            self._task(
                "complex.recipe_evidence",
                "RecipeKnowledgeExpert",
                ExpertCapability.RECIPE_KNOWLEDGE,
                ArtifactKind.RECIPE_EVIDENCE,
                ("complex.recipe_candidates",),
                priority=TaskPriority.HIGH,
            ),
            self._task(
                "complex.validate",
                "ConstraintValidation",
                ExpertCapability.RECIPE_RECOMMENDATION,
                ArtifactKind.CONSTRAINT_VALIDATION,
                ("complex.recipe_evidence",),
            ),
            self._task(
                "complex.response_plan",
                "BuildResponsePlan",
                ExpertCapability.RECIPE_RECOMMENDATION,
                ArtifactKind.RESPONSE_PLAN,
                ("complex.validate",),
            ),
        )
