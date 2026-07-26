"""Deterministic task templates and budgeted expert coordination."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from time import perf_counter

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
from recipe_assistant.agents.quality import GuardrailAgent, ResponseAgent
from recipe_assistant.agents.registry import ExpertCandidate, ExpertRegistry
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.services.skills import SkillContextPayload


class CoordinationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class CoordinatorLimits:
    max_steps: int = 14
    max_budget: int = 14
    max_rounds: int = 24
    max_claims_per_round: int = 1
    max_claims_per_agent: int = 12
    max_revisions: int = 1
    io_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if (
            self.max_steps < 1
            or self.max_budget < 1
            or self.max_rounds < 1
            or self.max_claims_per_round < 1
            or self.max_claims_per_agent < 1
            or self.max_revisions < 0
            or self.io_timeout_seconds <= 0
        ):
            raise ValueError("coordinator limits must be positive")


@dataclass(frozen=True, slots=True)
class CoordinatorOutcome:
    blackboard: CollaborationBlackboard
    status: CoordinationStatus
    steps_used: int
    budget_used: int
    warnings: tuple[str, ...] = ()
    rounds_used: int = 0

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


_PRIORITY_RANK = {
    TaskPriority.LOW: 0,
    TaskPriority.NORMAL: 1,
    TaskPriority.HIGH: 2,
    TaskPriority.CRITICAL: 3,
}


class CollaborativeRecipeCoordinator(RecipeCoordinator):
    """Derive open work and select executors through auditable claims."""

    def __init__(
        self,
        registry: ExpertRegistry,
        limits: CoordinatorLimits | None = None,
        *,
        response_agent: ResponseAgent | None = None,
        guardrail_agent: GuardrailAgent | None = None,
    ) -> None:
        super().__init__(registry, limits)
        self.response_agent = response_agent or ResponseAgent()
        self.guardrail_agent = guardrail_agent or GuardrailAgent()

    def derive_missing_work(
        self,
        board: CollaborationBlackboard,
    ) -> CollaborationBlackboard:
        """Open template work whose exact output is not already present."""

        for template in self.build_tasks(board.route):
            if template.id in board.tasks:
                continue
            if any(
                board.artifact_for(task_id=template.id, kind=kind) is None
                for kind in template.expected_artifacts
            ):
                board = board.add_task(replace(template, status=TaskStatus.OPEN))
        return self._derive_quality_work(board)

    def coordinate(self, blackboard: CollaborationBlackboard) -> CoordinatorOutcome:
        board = blackboard
        warnings: list[str] = []
        steps_used = 0
        budget_used = 0
        rounds_used = 0
        claim_counts: dict[str, int] = {}

        while rounds_used < self.limits.max_rounds:
            rounds_used += 1
            board = self.derive_missing_work(board)
            board, dependency_warnings = self._skip_blocked_dependencies(board)
            warnings.extend(dependency_warnings)
            open_tasks = tuple(
                task
                for task in board.tasks.values()
                if task.status is TaskStatus.OPEN
                and board.dependencies_succeeded(task)
            )
            if not open_tasks:
                break

            scheduled = []
            for task in open_tasks:
                candidates = tuple(
                    candidate
                    for candidate in self._claim_candidates(task, board)
                    if claim_counts.get(candidate.expert.name, 0)
                    < self.limits.max_claims_per_agent
                )
                if not candidates:
                    warning = f"task {task.id} has no eligible expert claim"
                    warnings.append(warning)
                    board = board.with_task_status(task.id, TaskStatus.FAILED)
                    board = board.append_event(
                        AgentEvent(
                            event_type=EventType.NO_CLAIM,
                            actor="coordinator",
                            task_id=task.id,
                            message=warning,
                        )
                    )
                    continue
                scheduled.append((task, candidates[0]))

            scheduled.sort(
                key=lambda item: (
                    -_PRIORITY_RANK[item[0].priority],
                    -item[1].decision.confidence,
                    item[1].expert.name,
                    item[0].id,
                )
            )
            if not scheduled:
                continue

            # The collaborative blackboard has exactly one writer: claim and
            # finish one task before the next derive cycle.
            for task, candidate in scheduled[:1]:
                if (
                    steps_used >= self.limits.max_steps
                    or budget_used + task.estimated_cost > self.limits.max_budget
                ):
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
                    board = self._skip_remaining_open(board, warning)
                    break

                claim_counts[candidate.expert.name] = (
                    claim_counts.get(candidate.expert.name, 0) + 1
                )
                board = board.claim_task(task.id, candidate.decision)
                board, used_steps, used_budget, task_warnings = self._execute_claim(
                    board,
                    task,
                    candidate.expert,
                    steps_available=self.limits.max_steps - steps_used,
                    budget_available=self.limits.max_budget - budget_used,
                )
                steps_used += used_steps
                budget_used += used_budget
                warnings.extend(task_warnings)

            if any(
                event.event_type is EventType.BUDGET_EXHAUSTED
                for event in board.events
            ):
                break
        else:
            warning = f"round limit reached after {self.limits.max_rounds} rounds"
            warnings.append(warning)
            board = board.append_event(
                AgentEvent(
                    event_type=EventType.ROUND_LIMIT_REACHED,
                    actor="coordinator",
                    message=warning,
                    metadata={"rounds_used": rounds_used},
                )
            )
            board = self._skip_remaining_open(board, warning)

        selected, board, final_warnings = self._select_reviewed_final(board)
        warnings.extend(final_warnings)
        board = board.select_final(selected.id)
        return CoordinatorOutcome(
            blackboard=board,
            status=(
                CoordinationStatus.DEGRADED
                if warnings
                else CoordinationStatus.SUCCEEDED
            ),
            steps_used=steps_used,
            budget_used=budget_used,
            warnings=tuple(warnings),
            rounds_used=rounds_used,
        )

    def _execute_claim(
        self,
        board: CollaborationBlackboard,
        task: AgentTask,
        expert,
        *,
        steps_available: int,
        budget_available: int,
    ) -> tuple[CollaborationBlackboard, int, int, list[str]]:
        warnings: list[str] = []
        attempts = 0
        max_attempts = 2 if self._is_retrieval_task(task) else 1
        while attempts < max_attempts:
            if (
                steps_available - attempts < 1
                or budget_available - attempts * task.estimated_cost
                < task.estimated_cost
            ):
                warning = f"budget exhausted before retrying task {task.id}"
                warnings.append(warning)
                board = board.append_event(
                    AgentEvent(
                        event_type=EventType.BUDGET_EXHAUSTED,
                        actor="coordinator",
                        task_id=task.id,
                        message=warning,
                    )
                )
                board = board.with_task_status(task.id, TaskStatus.FAILED)
                return board, attempts, attempts * task.estimated_cost, warnings

            attempts += 1
            board = (
                board.with_task_status(task.id, TaskStatus.RUNNING)
                if attempts == 1
                else board
            )
            board = board.append_event(
                AgentEvent(
                    event_type=EventType.TASK_STARTED,
                    actor=expert.name,
                    task_id=task.id,
                    metadata={"attempt": attempts},
                )
            )
            attempt_started = perf_counter()
            try:
                produced = expert.execute(task, board)
                duration_ms = (perf_counter() - attempt_started) * 1000
                if (
                    self._is_io_task(task)
                    and duration_ms > self.limits.io_timeout_seconds * 1000
                ):
                    raise TimeoutError(
                        f"task exceeded {self.limits.io_timeout_seconds:g}s "
                        "I/O deadline"
                    )
                artifacts = (
                    (produced,) if isinstance(produced, AgentArtifact) else tuple(produced)
                )
                for artifact in artifacts:
                    if artifact.task_id != task.id:
                        raise ValueError(
                            f"expert artifact task mismatch: {artifact.task_id} != {task.id}"
                        )
                    board = board.add_artifact(artifact)
                    artifact_metadata = {"kind": artifact.kind.value}
                    if artifact.kind is ArtifactKind.SKILL_CONTEXT:
                        artifact_metadata.update(
                            SkillContextPayload.model_validate(
                                artifact.payload
                            ).audit_projection()
                        )
                    board = board.append_event(
                        AgentEvent(
                            event_type=EventType.ARTIFACT_ADDED,
                            actor=expert.name,
                            task_id=task.id,
                            artifact_id=artifact.id,
                            metadata=artifact_metadata,
                        )
                    )
                    if artifact.metadata.get("purpose") in {
                        "response_generation",
                        "route_classification",
                    }:
                        board = board.append_event(
                            AgentEvent(
                                event_type=EventType.LLM_COMPLETED,
                                actor=expert.name,
                                task_id=task.id,
                                artifact_id=artifact.id,
                                message=str(artifact.metadata["purpose"]),
                                metadata={
                                    key: artifact.metadata.get(key)
                                    for key in (
                                        "llm_used",
                                        "model_name",
                                        "purpose",
                                        "latency_ms",
                                        "fallback_reason",
                                        "token_usage",
                                    )
                                },
                            )
                        )
                    if artifact.kind in {ArtifactKind.REVIEW, ArtifactKind.CRITIQUE}:
                        board = board.append_event(
                            AgentEvent(
                                event_type=EventType.ARTIFACT_REVIEWED,
                                actor=expert.name,
                                task_id=task.id,
                                artifact_id=artifact.id,
                                message=(
                                    "proposal approved"
                                    if artifact.kind is ArtifactKind.REVIEW
                                    else "proposal rejected"
                                ),
                                metadata={
                                    "review_of": artifact.review_of,
                                    "approved": artifact.kind is ArtifactKind.REVIEW,
                                },
                            )
                        )
                    if artifact.metadata.get("degraded"):
                        warning = str(
                            artifact.metadata.get("warning")
                            or f"task {task.id} produced a degraded artifact"
                        )
                        warnings.append(warning)
                        board = board.append_event(
                            AgentEvent(
                                event_type=EventType.DEGRADED,
                                actor=expert.name,
                                task_id=task.id,
                                artifact_id=artifact.id,
                                message=warning,
                            )
                        )
                if task.metadata.get("artifact_policy") == "any":
                    missing = (
                        ()
                        if any(
                            board.artifact_for(task_id=task.id, kind=kind)
                            is not None
                            for kind in task.expected_artifacts
                        )
                        else task.expected_artifacts
                    )
                else:
                    missing = tuple(
                        kind
                        for kind in task.expected_artifacts
                        if board.artifact_for(task_id=task.id, kind=kind) is None
                    )
                if missing:
                    names = ", ".join(kind.value for kind in missing)
                    raise RuntimeError(
                        f"task {task.id} did not publish required artifacts: {names}"
                    )
                board = board.with_task_status(task.id, TaskStatus.SUCCEEDED)
                board = board.append_event(
                    AgentEvent(
                        event_type=EventType.TASK_COMPLETED,
                        actor=expert.name,
                        task_id=task.id,
                        metadata={
                            "attempt": attempts,
                            "duration_ms": round(duration_ms, 3),
                        },
                    )
                )
                return board, attempts, attempts * task.estimated_cost, warnings
            except Exception as exc:
                duration_ms = (perf_counter() - attempt_started) * 1000
                fallback = self._fallback_artifact(board, task, exc)
                if fallback is not None:
                    warning = f"task {task.id} degraded after failure: {exc}"
                    warnings.append(warning)
                    board = board.add_artifact(fallback)
                    board = board.append_event(
                        AgentEvent(
                            event_type=EventType.FALLBACK_APPLIED,
                            actor="coordinator",
                            task_id=task.id,
                            artifact_id=fallback.id,
                            message=warning,
                            metadata={"error_type": type(exc).__name__},
                        )
                    )
                    board = board.append_event(
                        AgentEvent(
                            event_type=EventType.ARTIFACT_ADDED,
                            actor="coordinator",
                            task_id=task.id,
                            artifact_id=fallback.id,
                            metadata={"kind": fallback.kind.value, "degraded": True},
                        )
                    )
                    board = board.with_task_status(task.id, TaskStatus.SUCCEEDED)
                    board = board.append_event(
                        AgentEvent(
                            event_type=EventType.TASK_COMPLETED,
                            actor="coordinator",
                            task_id=task.id,
                            metadata={
                                "attempt": attempts,
                                "duration_ms": round(duration_ms, 3),
                                "degraded": True,
                            },
                        )
                    )
                    return board, attempts, attempts * task.estimated_cost, warnings
                if attempts < max_attempts:
                    board = board.append_event(
                        AgentEvent(
                            event_type=EventType.FALLBACK_APPLIED,
                            actor="coordinator",
                            task_id=task.id,
                            message=f"retrying retrieval task once after failure: {exc}",
                            metadata={"attempt": attempts, "strategy": "single_retry"},
                        )
                    )
                    continue
                warning = f"task {task.id} failed: {exc}"
                warnings.append(warning)
                board = board.with_task_status(task.id, TaskStatus.FAILED)
                board = board.append_event(
                    AgentEvent(
                        event_type=EventType.TASK_FAILED,
                        actor="coordinator",
                        task_id=task.id,
                        message=warning,
                        metadata={
                            "attempts": attempts,
                            "duration_ms": round(duration_ms, 3),
                            "error_type": type(exc).__name__,
                        },
                    )
                )
                return board, attempts, attempts * task.estimated_cost, warnings
        raise AssertionError("unreachable retry state")

    @staticmethod
    def _fallback_artifact(
        board: CollaborationBlackboard,
        task: AgentTask,
        exc: Exception,
    ) -> AgentArtifact | None:
        if task.id == "recommendation.weather":
            kind = ArtifactKind.WEATHER_CONTEXT
            payload = {"available": False, "warning": str(exc)}
        elif task.id == "recommendation.preferences":
            kind = ArtifactKind.USER_PREFERENCE_CONTEXT
            payload = {
                "preferred_cuisines": (),
                "disliked_ingredients": (),
                "allergens": (),
            }
        else:
            return None
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}:fallback",
            owner="coordinator",
            kind=kind,
            payload=payload,
            confidence=0.0,
            task_id=task.id,
            metadata={"degraded": True, "warning": str(exc)},
        )

    @staticmethod
    def _is_retrieval_task(task: AgentTask) -> bool:
        return task.id in {
            "knowledge.retrieve",
            "recommendation.retrieve",
            "complex.recipe_candidates",
            "complex.recipe_evidence",
        }

    @classmethod
    def _is_io_task(cls, task: AgentTask) -> bool:
        return cls._is_retrieval_task(task) or task.id in {
            "recommendation.weather",
            "recommendation.preferences",
            "nutrition.meal_history",
        }

    @staticmethod
    def _skip_blocked_dependencies(
        board: CollaborationBlackboard,
    ) -> tuple[CollaborationBlackboard, list[str]]:
        warnings: list[str] = []
        terminal = {TaskStatus.FAILED, TaskStatus.SKIPPED}
        for task in tuple(board.tasks.values()):
            if task.status is not TaskStatus.OPEN:
                continue
            failed = tuple(
                dependency
                for dependency in task.depends_on
                if dependency in board.tasks
                and board.tasks[dependency].status in terminal
            )
            if not failed:
                continue
            warning = (
                f"task {task.id} skipped because dependencies failed: "
                + ", ".join(failed)
            )
            warnings.append(warning)
            board = RecipeCoordinator._skip_task(board, task, warning)
        return board, warnings

    @staticmethod
    def _skip_remaining_open(
        board: CollaborationBlackboard,
        reason: str,
    ) -> CollaborationBlackboard:
        for task in tuple(board.tasks.values()):
            if task.status is TaskStatus.OPEN:
                board = RecipeCoordinator._skip_task(board, task, reason)
        return board

    def _claim_candidates(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> tuple[ExpertCandidate, ...]:
        if task.capability is ExpertCapability.RESPONSE_GENERATION:
            decision = self.response_agent.decide(task, board)
            return (
                ExpertCandidate(expert=self.response_agent, decision=decision),
            )
        if task.capability is ExpertCapability.QUALITY_REVIEW:
            decision = self.guardrail_agent.decide(task, board)
            return (
                ExpertCandidate(expert=self.guardrail_agent, decision=decision),
            )
        return self.registry.claim_candidates(task, board)

    def _derive_quality_work(
        self,
        board: CollaborationBlackboard,
    ) -> CollaborationBlackboard:
        response_plan_task_id = self.build_tasks(board.route)[-1].id
        response_plan_task = board.tasks.get(response_plan_task_id)
        if (
            response_plan_task is None
            or response_plan_task.status is not TaskStatus.SUCCEEDED
        ):
            return board

        skill_task_id = "context.skills"
        if skill_task_id not in board.tasks:
            return board.add_task(
                AgentTask(
                    id=skill_task_id,
                    title="SelectSkillContext",
                    capability=ExpertCapability.SKILL_SELECTION,
                    status=TaskStatus.OPEN,
                    priority=TaskPriority.HIGH,
                    depends_on=(response_plan_task_id,),
                    expected_artifacts=(ArtifactKind.SKILL_CONTEXT,),
                )
            )
        skill_task = board.tasks[skill_task_id]
        if skill_task.status is not TaskStatus.SUCCEEDED:
            return board
        if (
            board.artifact_for(
                task_id=skill_task_id,
                kind=ArtifactKind.SKILL_CONTEXT,
            )
            is None
        ):
            return board

        proposal_task_id = "quality.proposal.0"
        if proposal_task_id not in board.tasks:
            board = board.add_task(
                AgentTask(
                    id=proposal_task_id,
                    title="BuildResponseProposal",
                    capability=ExpertCapability.RESPONSE_GENERATION,
                    status=TaskStatus.OPEN,
                    priority=TaskPriority.HIGH,
                    depends_on=(response_plan_task_id, skill_task_id),
                    expected_artifacts=(ArtifactKind.RESPONSE_PROPOSAL,),
                    metadata={
                        "response_plan_task_id": response_plan_task_id,
                        "revision_number": 0,
                        "artifact_dependencies": self._quality_dependencies(board),
                    },
                )
            )

        for revision_number in range(self.limits.max_revisions + 1):
            current_proposal_task_id = (
                "quality.proposal.0"
                if revision_number == 0
                else f"quality.revision.{revision_number}"
            )
            proposal_task = board.tasks.get(current_proposal_task_id)
            if proposal_task is None or proposal_task.status is not TaskStatus.SUCCEEDED:
                break

            review_task_id = f"quality.review.{revision_number}"
            if review_task_id not in board.tasks:
                board = board.add_task(
                    AgentTask(
                        id=review_task_id,
                        title="ReviewResponseProposal",
                        capability=ExpertCapability.QUALITY_REVIEW,
                        status=TaskStatus.OPEN,
                        priority=TaskPriority.CRITICAL,
                        depends_on=(current_proposal_task_id,),
                        expected_artifacts=(
                            ArtifactKind.REVIEW,
                            ArtifactKind.CRITIQUE,
                        ),
                        metadata={
                            "artifact_policy": "any",
                            "proposal_task_id": current_proposal_task_id,
                            "skill_task_id": "context.skills",
                            **self._guardrail_dependency_ids(board),
                        },
                    )
                )
                break

            review_task = board.tasks[review_task_id]
            if review_task.status is not TaskStatus.SUCCEEDED:
                break
            approved = board.artifact_for(
                task_id=review_task_id,
                kind=ArtifactKind.REVIEW,
            )
            if approved is not None:
                break
            critique = board.artifact_for(
                task_id=review_task_id,
                kind=ArtifactKind.CRITIQUE,
            )
            if critique is None or revision_number >= self.limits.max_revisions:
                break

            next_revision = revision_number + 1
            revision_task_id = f"quality.revision.{next_revision}"
            if revision_task_id not in board.tasks:
                prior_proposal = board.artifact_for(
                    task_id=current_proposal_task_id,
                    kind=ArtifactKind.RESPONSE_PROPOSAL,
                )
                if prior_proposal is None:
                    break
                board = board.add_task(
                    AgentTask(
                        id=revision_task_id,
                        title="ReviseResponseProposal",
                        capability=ExpertCapability.RESPONSE_GENERATION,
                        status=TaskStatus.OPEN,
                        priority=TaskPriority.CRITICAL,
                        depends_on=(review_task_id,),
                        expected_artifacts=(ArtifactKind.RESPONSE_PROPOSAL,),
                        revision_of=current_proposal_task_id,
                        metadata={
                            "response_plan_task_id": response_plan_task_id,
                            "revision_number": next_revision,
                            "prior_proposal_id": prior_proposal.id,
                            "critique_task_id": review_task_id,
                            "artifact_dependencies": self._quality_dependencies(
                                board
                            ),
                        },
                    )
                )
                board = board.append_event(
                    AgentEvent(
                        event_type=EventType.REVISION_REQUESTED,
                        actor="coordinator",
                        task_id=revision_task_id,
                        artifact_id=critique.id,
                        message="guardrail critique requested a bounded revision",
                        metadata={
                            "revision_number": next_revision,
                            "revision_of": current_proposal_task_id,
                        },
                    )
                )
                break
        return board

    @staticmethod
    def _quality_dependencies(
        board: CollaborationBlackboard,
    ) -> tuple[dict[str, str], ...]:
        relevant_kinds = {
            ArtifactKind.CONVERSATION_CONTEXT,
            ArtifactKind.SKILL_CONTEXT,
            ArtifactKind.QUERY_CONSTRAINTS,
            ArtifactKind.RECIPE_EVIDENCE,
            ArtifactKind.RECIPE_CANDIDATES,
            ArtifactKind.USER_PREFERENCE_CONTEXT,
            ArtifactKind.WEATHER_CONTEXT,
            ArtifactKind.NUTRITION_SUMMARY,
            ArtifactKind.NUTRITION_GOAL,
            ArtifactKind.CONSTRAINT_VALIDATION,
        }
        return tuple(
            {"task_id": artifact.task_id, "kind": artifact.kind.value}
            for artifact in board.artifacts
            if artifact.kind in relevant_kinds
        )

    @staticmethod
    def _guardrail_dependency_ids(
        board: CollaborationBlackboard,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for artifact in board.artifacts:
            if (
                artifact.kind is ArtifactKind.QUERY_CONSTRAINTS
                and artifact.task_id == "recommendation.extract_constraints"
            ):
                result["constraints_task_id"] = artifact.task_id
            elif artifact.kind is ArtifactKind.USER_PREFERENCE_CONTEXT:
                result["preferences_task_id"] = artifact.task_id
            elif artifact.kind is ArtifactKind.CONSTRAINT_VALIDATION:
                result["validation_task_id"] = artifact.task_id
        return result

    @staticmethod
    def _select_reviewed_final(
        board: CollaborationBlackboard,
    ) -> tuple[AgentArtifact, CollaborationBlackboard, list[str]]:
        critiqued_proposals = {
            artifact.review_of
            for artifact in board.artifacts_for(kind=ArtifactKind.CRITIQUE)
            if artifact.review_of
        }
        approved_reviews = tuple(
            artifact
            for artifact in board.artifacts_for(kind=ArtifactKind.REVIEW)
            if artifact.payload.get("approved") is True
            and artifact.review_of
            and artifact.review_of not in critiqued_proposals
            and board.tasks[artifact.task_id].status is TaskStatus.SUCCEEDED
        )
        if approved_reviews:
            review = approved_reviews[-1]
            proposal = board.artifact_by_id(review.review_of)
            if proposal is None or proposal.kind is not ArtifactKind.RESPONSE_PROPOSAL:
                raise ValueError("approved review references no response proposal")
            if board.tasks[proposal.task_id].status is not TaskStatus.SUCCEEDED:
                raise ValueError("approved proposal task did not succeed")
            board = board.append_event(
                AgentEvent(
                    event_type=EventType.FINAL_ACCEPTED,
                    actor="coordinator",
                    task_id=proposal.task_id,
                    artifact_id=proposal.id,
                    message="guardrail-approved proposal accepted as final",
                    metadata={"review_artifact_id": review.id},
                )
            )
            return proposal, board, []

        critiques = board.artifacts_for(kind=ArtifactKind.CRITIQUE)
        warning = (
            "response proposal did not pass deterministic quality review; "
            "selected a safe degraded response"
        )
        task_id = next(reversed(board.tasks), "coordinator.fallback")
        if task_id not in board.tasks:
            board = board.add_task(
                AgentTask(
                    id=task_id,
                    title="Fallback",
                    capability=ExpertCapability.RESPONSE_GENERATION,
                    status=TaskStatus.OPEN,
                )
            )
        selected = AgentArtifact(
            id=f"{board.run_id}:quality-fallback",
            owner="coordinator",
            kind=ArtifactKind.ERROR,
            payload={
                "message": "当前回答未通过食品安全或硬约束审核，请补充条件后重试。",
                "warnings": (warning,),
            },
            confidence=0.0,
            task_id=task_id,
            metadata={"degraded": True, "quality_gate": True},
        )
        board = board.add_artifact(selected)
        board = board.append_event(
            AgentEvent(
                event_type=EventType.DEGRADED,
                actor="coordinator",
                task_id=task_id,
                artifact_id=selected.id,
                message=warning,
            )
        )
        if critiques:
            violations = tuple(
                dict.fromkeys(
                    str(violation)
                    for critique in critiques
                    for violation in critique.payload.get("violations", ())
                )
            )
            board = board.append_event(
                AgentEvent(
                    event_type=EventType.BAD_CASE_CANDIDATE,
                    actor="coordinator",
                    task_id=task_id,
                    artifact_id=critiques[-1].id,
                    message="quality revisions exhausted; queued for non-blocking review",
                    metadata={
                        "trigger": "QUALITY_REVISIONS_EXHAUSTED",
                        "hard_constraint_violations": violations,
                    },
                )
            )
        return selected, board, [warning]

    @staticmethod
    def _select_final(
        board: CollaborationBlackboard,
    ) -> tuple[AgentArtifact, CollaborationBlackboard, list[str]]:
        response_plans = board.artifacts_for(kind=ArtifactKind.RESPONSE_PLAN)
        if response_plans:
            return (
                max(response_plans, key=lambda artifact: artifact.confidence),
                board,
                [],
            )
        warning = "no response plan was produced; selected a structured error artifact"
        task_id = next(reversed(board.tasks), "coordinator.fallback")
        if task_id not in board.tasks:
            board = board.add_task(
                AgentTask(
                    id=task_id,
                    title="Fallback",
                    capability=ExpertCapability.RECIPE_RECOMMENDATION,
                    status=TaskStatus.OPEN,
                )
            )
        selected = AgentArtifact(
            id=f"{board.run_id}:fallback",
            owner="coordinator",
            kind=ArtifactKind.ERROR,
            payload={
                "message": "当前协作结果不完整，请基于已有信息降级回答或请求澄清。",
                "warnings": (warning,),
            },
            confidence=0.0,
            task_id=task_id,
            metadata={"degraded": True},
        )
        board = board.add_artifact(selected)
        board = board.append_event(
            AgentEvent(
                event_type=EventType.DEGRADED,
                actor="coordinator",
                task_id=task_id,
                artifact_id=selected.id,
                message=warning,
            )
        )
        return selected, board, [warning]
