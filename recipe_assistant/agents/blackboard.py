"""Immutable append-only collaboration blackboard."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from pydantic import ConfigDict

from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentEvent,
    AgentTask,
    ArtifactKind,
    EventType,
    TaskStatus,
)
from recipe_assistant.schemas.agent.route import RouteDecision


class _FrozenRouteDecision(RouteDecision):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset(
        {TaskStatus.RUNNING, TaskStatus.SKIPPED, TaskStatus.FAILED}
    ),
    TaskStatus.RUNNING: frozenset(
        {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.SKIPPED}
    ),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.SKIPPED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class CollaborationBlackboard:
    run_id: str
    user_id: int
    session_id: str
    user_input: str
    route: RouteDecision
    tasks: Mapping[str, AgentTask] = field(default_factory=dict)
    artifacts: tuple[AgentArtifact, ...] = ()
    events: tuple[AgentEvent, ...] = ()
    final_artifact_id: str = ""

    def __post_init__(self) -> None:
        if not self.run_id or not self.session_id:
            raise ValueError("blackboard run_id and session_id must be non-empty")
        object.__setattr__(self, "tasks", MappingProxyType(dict(self.tasks)))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(
            self,
            "route",
            _FrozenRouteDecision.model_validate(self.route.model_dump()),
        )

    def add_task(self, task: AgentTask) -> "CollaborationBlackboard":
        if task.id in self.tasks:
            raise ValueError(f"task id already exists: {task.id}")
        tasks = dict(self.tasks)
        tasks[task.id] = task
        updated = replace(self, tasks=tasks)
        return updated.append_event(
            AgentEvent(
                event_type=EventType.TASK_ADDED,
                actor="coordinator",
                task_id=task.id,
                message=task.title,
            )
        )

    def with_task_status(
        self,
        task_id: str,
        status: TaskStatus,
    ) -> "CollaborationBlackboard":
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task id: {task_id}")
        if status not in _TASK_TRANSITIONS[task.status]:
            raise ValueError(f"invalid task transition: {task.status.value} -> {status.value}")
        tasks = dict(self.tasks)
        tasks[task_id] = replace(task, status=status)
        return replace(self, tasks=tasks)

    def add_artifact(self, artifact: AgentArtifact) -> "CollaborationBlackboard":
        if any(item.id == artifact.id for item in self.artifacts):
            raise ValueError(f"artifact id already exists: {artifact.id}")
        if artifact.task_id not in self.tasks:
            raise ValueError(f"artifact references unknown task: {artifact.task_id}")
        return replace(self, artifacts=(*self.artifacts, artifact))

    def append_event(self, event: AgentEvent) -> "CollaborationBlackboard":
        expected_sequence = len(self.events) + 1
        if event.sequence not in (0, expected_sequence):
            raise ValueError(
                f"event sequence must be {expected_sequence}, got {event.sequence}"
            )
        sequenced = replace(event, sequence=expected_sequence)
        return replace(self, events=(*self.events, sequenced))

    def select_final(self, artifact_id: str) -> "CollaborationBlackboard":
        if self.final_artifact_id:
            raise ValueError("final artifact has already been selected")
        if not any(item.id == artifact_id for item in self.artifacts):
            raise ValueError(f"final artifact does not exist: {artifact_id}")
        updated = replace(self, final_artifact_id=artifact_id)
        return updated.append_event(
            AgentEvent(
                event_type=EventType.FINAL_SELECTED,
                actor="coordinator",
                artifact_id=artifact_id,
            )
        )

    def artifacts_for(
        self,
        *,
        kind: ArtifactKind | None = None,
        task_id: str | None = None,
    ) -> tuple[AgentArtifact, ...]:
        return tuple(
            artifact
            for artifact in self.artifacts
            if (kind is None or artifact.kind is kind)
            and (task_id is None or artifact.task_id == task_id)
        )

    def dependencies_succeeded(self, task: AgentTask) -> bool:
        return all(
            dependency in self.tasks
            and self.tasks[dependency].status is TaskStatus.SUCCEEDED
            for dependency in task.depends_on
        )

    def trace_events(self) -> list[dict]:
        return [event.to_trace_dict() for event in self.events]
