"""Immutable collaboration tasks, artifacts and events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any

from recipe_assistant.core.database import utc_now


class ExpertCapability(str, Enum):
    RECIPE_KNOWLEDGE = "RECIPE_KNOWLEDGE"
    RECIPE_RECOMMENDATION = "RECIPE_RECOMMENDATION"
    NUTRITION_PLANNING = "NUTRITION_PLANNING"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TaskPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ArtifactKind(str, Enum):
    ROUTE_DECISION = "ROUTE_DECISION"
    QUERY_CONSTRAINTS = "QUERY_CONSTRAINTS"
    RECIPE_EVIDENCE = "RECIPE_EVIDENCE"
    RECIPE_CANDIDATES = "RECIPE_CANDIDATES"
    WEATHER_CONTEXT = "WEATHER_CONTEXT"
    USER_PREFERENCE_CONTEXT = "USER_PREFERENCE_CONTEXT"
    MEAL_HISTORY = "MEAL_HISTORY"
    NUTRITION_SUMMARY = "NUTRITION_SUMMARY"
    NUTRITION_GOAL = "NUTRITION_GOAL"
    CONSTRAINT_VALIDATION = "CONSTRAINT_VALIDATION"
    REPORT_DRAFT = "REPORT_DRAFT"
    RESPONSE_PLAN = "RESPONSE_PLAN"
    FINAL_RESPONSE = "FINAL_RESPONSE"
    ERROR = "ERROR"


class EventType(str, Enum):
    TASK_ADDED = "TASK_ADDED"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_SKIPPED = "TASK_SKIPPED"
    ARTIFACT_ADDED = "ARTIFACT_ADDED"
    FINAL_SELECTED = "FINAL_SELECTED"
    DEGRADED = "DEGRADED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    MISSING_ARTIFACT = "MISSING_ARTIFACT"


def freeze_value(value: Any) -> Any:
    """Recursively copy mutable containers into immutable equivalents."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze_value(item) for item in value)
    return value


def thaw_value(value: Any) -> Any:
    """Convert frozen collaboration values into JSON-compatible containers."""

    if isinstance(value, Mapping):
        return {str(key): thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_value(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(thaw_value(item) for item in value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


@dataclass(frozen=True, slots=True)
class AgentTask:
    id: str
    title: str
    capability: ExpertCapability
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    depends_on: tuple[str, ...] = ()
    expected_artifacts: tuple[ArtifactKind, ...] = ()
    estimated_cost: int = 1
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.title:
            raise ValueError("task id and title must be non-empty")
        if self.estimated_cost < 1:
            raise ValueError("task estimated_cost must be positive")
        object.__setattr__(self, "depends_on", tuple(self.depends_on))
        object.__setattr__(self, "expected_artifacts", tuple(self.expected_artifacts))
        object.__setattr__(self, "metadata", freeze_value(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentArtifact:
    id: str
    owner: str
    kind: ArtifactKind
    payload: Mapping[str, Any]
    confidence: float
    task_id: str
    created_at: datetime = field(default_factory=utc_now)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.owner or not self.task_id:
            raise ValueError("artifact id, owner and task_id must be non-empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("artifact confidence must be between 0 and 1")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("artifact created_at must be timezone-aware")
        object.__setattr__(self, "payload", freeze_value(self.payload))
        object.__setattr__(self, "metadata", freeze_value(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentEvent:
    event_type: EventType
    actor: str
    task_id: str = ""
    artifact_id: str = ""
    message: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.actor:
            raise ValueError("event actor must be non-empty")
        if self.sequence < 0:
            raise ValueError("event sequence cannot be negative")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("event created_at must be timezone-aware")
        object.__setattr__(self, "metadata", freeze_value(self.metadata))

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "actor": self.actor,
            "task_id": self.task_id,
            "artifact_id": self.artifact_id,
            "message": self.message,
            "metadata": thaw_value(self.metadata),
            "created_at": self.created_at.isoformat(),
        }
