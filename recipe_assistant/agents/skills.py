"""Independent expert that publishes validated business Skill context."""

from __future__ import annotations

from typing import ClassVar, Protocol

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ClaimDecision,
    ExpertCapability,
)
from recipe_assistant.services.skill_signals import SkillSignalExtractor
from recipe_assistant.services.skills import (
    SkillContextPayload,
    SkillRegistry,
    SkillSelectionRequest,
    SkillSignal,
)


class SignalExtractor(Protocol):
    def extract(
        self,
        board: CollaborationBlackboard,
    ) -> tuple[SkillSignal, ...]: ...


class SkillContextAgent:
    """Select Skills through the shared Registry and publish one trusted Artifact."""

    name: ClassVar[str] = "skill_context_agent"
    capabilities: ClassVar[frozenset[ExpertCapability]] = frozenset(
        {ExpertCapability.SKILL_SELECTION}
    )

    def __init__(
        self,
        registry: SkillRegistry,
        signal_extractor: SignalExtractor | None = None,
    ) -> None:
        self.registry = registry
        self.signal_extractor = signal_extractor or SkillSignalExtractor()

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
            reason=(
                "select validated business Skills for response behavior"
                if accepted
                else ""
            ),
        )

    def execute(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        if task.capability not in self.capabilities:
            raise ValueError(f"unsupported capability: {task.capability.value}")

        signals = self.signal_extractor.extract(board)
        selection = self.registry.select(
            SkillSelectionRequest(
                route=board.route.route,
                signals=frozenset(signals),
            )
        )
        payload = SkillContextPayload(
            selected_skill_refs=list(selection.selected_skill_refs),
            signals=list(signals),
            risk=selection.effective_risk,
            prompt_context=selection.prompt_context,
            selection_reason=self._selection_reason(
                board,
                signals,
                selection.selected_skill_refs,
            ),
            hard_constraints_authoritative=True,
        )
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}",
            owner=self.name,
            kind=ArtifactKind.SKILL_CONTEXT,
            payload=payload.model_dump(mode="json"),
            confidence=1.0,
            task_id=task.id,
            metadata={
                "selected_skill_count": len(payload.selected_skill_refs),
                "signal_count": len(payload.signals),
            },
        )

    @staticmethod
    def _selection_reason(
        board: CollaborationBlackboard,
        signals: tuple[SkillSignal, ...],
        selected_skill_refs: tuple[str, ...],
    ) -> str:
        signal_text = ",".join(signal.value for signal in signals) or "none"
        selected_text = ",".join(selected_skill_refs) or "none"
        return (
            f"route={board.route.route.value};"
            f"signals={signal_text};"
            f"selected={selected_text}"
        )
