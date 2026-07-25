"""Thin runtime assembling a blackboard and deterministic coordinator."""

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.context import build_conversation_context
from recipe_assistant.agents.coordinator import (
    CollaborativeRecipeCoordinator,
    CoordinatorOutcome,
    RecipeCoordinator,
)
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentEvent,
    AgentTask,
    ArtifactKind,
    ClaimDecision,
    EventType,
    ExpertCapability,
    TaskStatus,
)
from recipe_assistant.agents.result import RunContext
from recipe_assistant.schemas.agent.route import RouteDecision


class RecipeAgentRuntime:
    def __init__(self, coordinator: RecipeCoordinator) -> None:
        self.coordinator = coordinator
        self.coordination_mode = (
            "collaborative"
            if isinstance(coordinator, CollaborativeRecipeCoordinator)
            else "fixed"
        )

    def run(
        self,
        context: RunContext,
        route_decision: RouteDecision,
    ) -> CoordinatorOutcome:
        snapshot = (
            dict(context.conversation_context)
            if context.conversation_context
            else build_conversation_context(
                context.history,
                context.normalized_input,
            )
        )
        blackboard = CollaborationBlackboard(
            run_id=context.run_id,
            user_id=context.user_id,
            session_id=context.session_public_id,
            user_input=context.normalized_input,
            retrieval_query=(
                context.retrieval_input
                or str(snapshot["retrieval_query"])
                or context.normalized_input
            ),
            route=route_decision,
        )
        if snapshot["messages"]:
            task_id = "context.conversation"
            task = AgentTask(
                id=task_id,
                title="BuildConversationContext",
                capability=ExpertCapability.CONTEXT_PREPARATION,
                status=TaskStatus.OPEN,
                expected_artifacts=(ArtifactKind.CONVERSATION_CONTEXT,),
            )
            blackboard = blackboard.add_task(task)
            blackboard = blackboard.claim_task(
                task_id,
                ClaimDecision(
                    expert_name="conversation_context_builder",
                    accepted=True,
                    confidence=1.0,
                    reason="prepare bounded session context",
                ),
            )
            blackboard = blackboard.with_task_status(task_id, TaskStatus.RUNNING)
            blackboard = blackboard.append_event(
                AgentEvent(
                    event_type=EventType.TASK_STARTED,
                    actor="conversation_context_builder",
                    task_id=task_id,
                )
            )
            artifact = AgentArtifact(
                id=f"{context.run_id}:{task_id}",
                owner="conversation_context_builder",
                kind=ArtifactKind.CONVERSATION_CONTEXT,
                payload=snapshot,
                confidence=1.0,
                task_id=task_id,
                metadata={
                    "message_count": len(snapshot["messages"]),
                    "context_applied": snapshot["context_applied"],
                    "resolution_source": snapshot.get("resolution_source", "none"),
                    "resolution_confidence": snapshot.get(
                        "resolution_confidence",
                        0.0,
                    ),
                    "resolved_intent": snapshot.get("resolved_intent", ""),
                    "resolved_recipe_names": snapshot.get(
                        "resolved_recipe_names",
                        [],
                    ),
                    "recommended_recipe_names": snapshot.get(
                        "recommended_recipe_names",
                        [],
                    ),
                    "rewritten_query": snapshot.get(
                        "retrieval_query",
                        context.normalized_input,
                    ),
                },
            )
            blackboard = blackboard.add_artifact(artifact)
            blackboard = blackboard.append_event(
                AgentEvent(
                    event_type=EventType.ARTIFACT_ADDED,
                    actor="conversation_context_builder",
                    task_id=task_id,
                    artifact_id=artifact.id,
                    metadata={
                        "kind": ArtifactKind.CONVERSATION_CONTEXT.value,
                        "message_count": len(snapshot["messages"]),
                        "context_applied": snapshot["context_applied"],
                        "resolution_source": snapshot.get(
                            "resolution_source",
                            "none",
                        ),
                        "resolution_confidence": snapshot.get(
                            "resolution_confidence",
                            0.0,
                        ),
                        "resolved_intent": snapshot.get("resolved_intent", ""),
                        "resolved_recipe_names": snapshot.get(
                            "resolved_recipe_names",
                            [],
                        ),
                        "recommended_recipe_names": snapshot.get(
                            "recommended_recipe_names",
                            [],
                        ),
                        "rewritten_query": snapshot.get(
                            "retrieval_query",
                            context.normalized_input,
                        ),
                    },
                )
            )
            blackboard = blackboard.with_task_status(task_id, TaskStatus.SUCCEEDED)
            blackboard = blackboard.append_event(
                AgentEvent(
                    event_type=EventType.TASK_COMPLETED,
                    actor="conversation_context_builder",
                    task_id=task_id,
                )
            )
        return self.coordinator.coordinate(blackboard)
