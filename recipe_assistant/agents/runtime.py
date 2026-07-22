"""Thin runtime assembling a blackboard and deterministic coordinator."""

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.coordinator import CoordinatorOutcome, RecipeCoordinator
from recipe_assistant.agents.result import RunContext
from recipe_assistant.schemas.agent.route import RouteDecision


class RecipeAgentRuntime:
    def __init__(self, coordinator: RecipeCoordinator) -> None:
        self.coordinator = coordinator

    def run(
        self,
        context: RunContext,
        route_decision: RouteDecision,
    ) -> CoordinatorOutcome:
        blackboard = CollaborationBlackboard(
            run_id=context.run_id,
            user_id=context.user_id,
            session_id=context.session_public_id,
            user_input=context.normalized_input,
            route=route_decision,
        )
        return self.coordinator.coordinate(blackboard)
