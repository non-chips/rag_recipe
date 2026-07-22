"""Deterministic registry for capability-scoped expert executors."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import AgentArtifact, AgentTask, ExpertCapability


class ExpertNotFoundError(LookupError):
    """Raised when no registered expert exposes the required capability."""


class ExpertExecutor(Protocol):
    name: str
    capabilities: frozenset[ExpertCapability]

    def execute(
        self,
        task: AgentTask,
        blackboard: CollaborationBlackboard,
    ) -> AgentArtifact | Sequence[AgentArtifact]:
        """Execute one immutable task and return newly published artifacts."""


class ExpertRegistry:
    """Resolve experts in stable registration order; no bidding loop is used."""

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
        for expert in self._experts:
            if capability in expert.capabilities:
                return expert
        raise ExpertNotFoundError(f"no expert registered for {capability.value}")
