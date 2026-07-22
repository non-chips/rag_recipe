from __future__ import annotations

from recipe_assistant.agents.coordinator import CoordinationStatus, RecipeCoordinator
from recipe_assistant.agents.events import ArtifactKind, EventType
from recipe_assistant.agents.experts.recipe_knowledge import RecipeKnowledgeExpert
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.agents.result import ProfileSnapshot, RunContext
from recipe_assistant.agents.runtime import RecipeAgentRuntime
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.schemas.retrieval import RetrievalHit, RetrievalResult, RetrievalStrategy
from recipe_assistant.tools.recipe_knowledge_tools import create_recipe_knowledge_tool
from recipe_assistant.tools.registry import ToolRegistry


class _OfflineRetrievalService:
    def retrieve(self, request):
        return RetrievalResult(
            query=request.query,
            strategy=RetrievalStrategy.VECTOR_ONLY,
            hits=[
                RetrievalHit(
                    recipe_id="steamed-fish",
                    recipe_name="清蒸鱼",
                    source_path="recipes/清蒸鱼.md",
                    content="工具：蒸锅。步骤：鱼处理干净后入蒸锅蒸制。",
                    retrieval_sources=["chroma"],
                    fused_score=0.7,
                )
            ],
            confidence=1 / 3,
        )


def test_recipe_question_runs_through_real_knowledge_expert() -> None:
    service = _OfflineRetrievalService()
    tools = ToolRegistry([create_recipe_knowledge_tool(service)])  # type: ignore[arg-type]
    expert = RecipeKnowledgeExpert(tools)
    runtime = RecipeAgentRuntime(RecipeCoordinator(ExpertRegistry([expert])))

    outcome = runtime.run(
        RunContext(
            run_id="run-e2e-knowledge",
            user_id=11,
            session_id=21,
            session_public_id="recipe-session",
            original_input="清蒸鱼需要什么工具，步骤是什么？",
            normalized_input="清蒸鱼需要什么工具，步骤是什么？",
            profile=ProfileSnapshot(),
        ),
        RouteDecision(
            route=RouteType.RECIPE_KNOWLEDGE,
            confidence=0.99,
            reason="knowledge question",
        ),
    )

    assert outcome.status is CoordinationStatus.SUCCEEDED
    assert outcome.final_artifact.kind is ArtifactKind.RESPONSE_PLAN
    assert outcome.final_artifact.payload["evidence"][0]["recipe_id"] == "steamed-fish"
    assert any(
        event.event_type is EventType.ARTIFACT_ADDED
        and event.actor == "recipe_knowledge_expert"
        for event in outcome.blackboard.events
    )
