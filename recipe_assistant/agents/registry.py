"""Deterministic registry for capability-scoped expert executors."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ClaimDecision,
    ExpertCapability,
)


class ExpertNotFoundError(LookupError):
    """Raised when no registered expert exposes the required capability."""


class ExpertExecutor(Protocol):
    name: str
    capabilities: frozenset[ExpertCapability]

    def decide(
        self,
        task: AgentTask,
        blackboard: CollaborationBlackboard,
    ) -> ClaimDecision:
        """Return an immutable decision about claiming one open task."""

    def execute(
        self,
        task: AgentTask,
        blackboard: CollaborationBlackboard,
    ) -> AgentArtifact | Sequence[AgentArtifact]:
        """Execute one immutable task and return newly published artifacts."""


@dataclass(frozen=True, slots=True)
class ExpertCandidate:
    """An accepted claim paired with the expert that made it."""

    expert: ExpertExecutor
    decision: ClaimDecision


class ExpertRegistry:
    """Register experts and expose deterministic claim candidates."""

    def __init__(self, experts: Iterable[ExpertExecutor] = ()) -> None:
        self._experts: list[ExpertExecutor] = []
        self._names: set[str] = set()
        for expert in experts:
            self.register(expert)

    def register(self, expert: ExpertExecutor) -> None:
        if not expert.name or expert.name in self._names:
            raise ValueError(f"expert name is empty or duplicated: {expert.name}")
        if not expert.capabilities:
            raise ValueError("expert must declare at least one capability")
        self._experts.append(expert)
        self._names.add(expert.name)

    def resolve(self, capability: ExpertCapability) -> ExpertExecutor:
        """Compatibility resolver for the current fixed coordinator."""

        for expert in self._experts:
            if capability in expert.capabilities:
                return expert
        raise ExpertNotFoundError(f"no expert registered for {capability.value}")

    def candidates(
        self,
        task: AgentTask,
        blackboard: CollaborationBlackboard,
    ) -> tuple[ExpertCandidate, ...]:
        """Return accepted claims ordered by confidence, then stable expert name."""

        candidates: list[ExpertCandidate] = []
        for expert in self._experts:
            if task.capability not in expert.capabilities:
                continue
            decision = expert.decide(task, blackboard)
            if decision.expert_name != expert.name:
                raise ValueError(
                    "claim decision expert_name does not match registered expert: "
                    f"{decision.expert_name} != {expert.name}"
                )
            if decision.accepted:
                candidates.append(ExpertCandidate(expert=expert, decision=decision))
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.decision.confidence,
                    candidate.expert.name,
                ),
            )
        )

    def claim_candidates(
        self,
        task: AgentTask,
        blackboard: CollaborationBlackboard,
    ) -> tuple[ExpertCandidate, ...]:
        """Named alias used by the upcoming collaborative coordinator."""

        return self.candidates(task, blackboard)
