"""Shared contracts for deterministic domain experts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ClaimDecision,
    ExpertCapability,
)
from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.registry import ToolRegistry


class ExpertPayload(BaseModel):
    """Immutable structured payload published inside an agent artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class BaseExpert(ABC):
    """Base implementation shared by capability-scoped local experts."""

    name: ClassVar[str]
    capabilities: ClassVar[frozenset[ExpertCapability]]

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self.tool_registry = tool_registry

    def decide(
        self,
        task: AgentTask,
        blackboard: CollaborationBlackboard,
    ) -> ClaimDecision:
        """Provide the default capability-based claim without executing tools."""

        del blackboard
        accepted = task.capability in self.capabilities
        return ClaimDecision(
            expert_name=self.name,
            accepted=accepted,
            confidence=1.0 if accepted else 0.0,
            reason=(
                f"{self.name} declares capability {task.capability.value}"
                if accepted
                else ""
            ),
        )

    @abstractmethod
    def execute(
        self,
        task: AgentTask,
        blackboard: CollaborationBlackboard,
    ) -> AgentArtifact | tuple[AgentArtifact, ...]:
        """Execute one coordinator task without mutating the blackboard."""

    def tool_context(self, blackboard: CollaborationBlackboard) -> ToolContext:
        return ToolContext(
            run_id=blackboard.run_id,
            user_id=blackboard.user_id,
            session_id=blackboard.session_id,
            route=blackboard.route.route.value,
        )

    def artifact_id(self, blackboard: CollaborationBlackboard, task: AgentTask) -> str:
        return f"{blackboard.run_id}:{task.id}"
