from __future__ import annotations

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentTask,
    ArtifactKind,
    ExpertCapability,
    TaskStatus,
)
from recipe_assistant.agents.experts.recipe_recommendation import (
    RecipeRecommendationExpert,
)
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.tools.registry import ToolRegistry


def _board(*, user_input: str, retrieval_query: str) -> CollaborationBlackboard:
    return CollaborationBlackboard(
        run_id="constraint-context-run",
        user_id=1,
        session_id="constraint-context-session",
        user_input=user_input,
        retrieval_query=retrieval_query,
        route=RouteDecision(
            route=RouteType.RECIPE_RECOMMENDATION,
            confidence=1.0,
            reason="test",
        ),
    )


def _task() -> AgentTask:
    return AgentTask(
        id="recommendation.extract_constraints",
        title="ExtractConstraints",
        capability=ExpertCapability.RECIPE_RECOMMENDATION,
        status=TaskStatus.OPEN,
        expected_artifacts=(ArtifactKind.QUERY_CONSTRAINTS,),
    )


def test_assistant_history_time_does_not_become_current_user_constraint() -> None:
    expert = RecipeRecommendationExpert(ToolRegistry())
    board = _board(
        user_input="好，那你推荐的第一道菜怎么做？",
        retrieval_query=(
            "好，那你推荐的第一道菜怎么做？\n"
            "ASSISTANT: 豆腐焯水 1-2 分钟，再加入调味汁。"
        ),
    )

    artifact = expert.execute(_task(), board)

    assert artifact.payload["max_time_minutes"] is None


def test_current_user_time_constraint_is_still_extracted() -> None:
    expert = RecipeRecommendationExpert(ToolRegistry())
    board = _board(
        user_input="推荐一道20分钟内能做完的菜",
        retrieval_query="承接历史推荐，推荐一道20分钟内能做完的菜",
    )

    artifact = expert.execute(_task(), board)

    assert artifact.payload["max_time_minutes"] == 20
