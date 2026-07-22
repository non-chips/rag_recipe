from __future__ import annotations

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.coordinator import RecipeCoordinator
from recipe_assistant.agents.events import ArtifactKind
from recipe_assistant.agents.experts.recipe_knowledge import RecipeKnowledgeExpert
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.schemas.retrieval import RetrievalHit, RetrievalResult, RetrievalStrategy
from recipe_assistant.tools.recipe_knowledge_tools import create_recipe_knowledge_tool
from recipe_assistant.tools.registry import ToolRegistry


class _FakeRetrievalService:
    def __init__(self, *, with_hits: bool = True) -> None:
        self.with_hits = with_hits
        self.requests = []

    def retrieve(self, request):
        self.requests.append(request)
        hits = []
        if self.with_hits:
            hits.append(
                RetrievalHit(
                    recipe_id="tomato-egg",
                    recipe_name="番茄炒蛋",
                    source_path="recipes/番茄炒蛋.md",
                    content="食材：番茄、鸡蛋。步骤：先炒鸡蛋，再炒番茄后混合。",
                    retrieval_sources=["bm25"],
                    fused_score=0.8,
                )
            )
        return RetrievalResult(
            query=request.query,
            strategy=RetrievalStrategy.BM25_KEYWORD,
            hits=hits,
            confidence=1 / 3 if hits else 0.0,
        )


def _run(service: _FakeRetrievalService, query: str = "番茄炒蛋有哪些食材和步骤"):
    tool = create_recipe_knowledge_tool(service)  # type: ignore[arg-type]
    expert = RecipeKnowledgeExpert(ToolRegistry([tool]))
    coordinator = RecipeCoordinator(ExpertRegistry([expert]))
    board = CollaborationBlackboard(
        run_id="run-knowledge",
        user_id=7,
        session_id="session-knowledge",
        user_input=query,
        route=RouteDecision(
            route=RouteType.RECIPE_KNOWLEDGE,
            confidence=1.0,
            reason="recipe facts",
        ),
    )
    return coordinator.coordinate(board)


def test_expert_uses_retrieval_tool_and_publishes_grounded_plan() -> None:
    service = _FakeRetrievalService()
    outcome = _run(service)

    assert service.requests[0].query == "番茄炒蛋有哪些食材和步骤"
    evidence = outcome.blackboard.artifacts_for(kind=ArtifactKind.RECIPE_EVIDENCE)[0]
    assert evidence.payload["items"][0]["recipe_id"] == "tomato-egg"
    plan = outcome.final_artifact
    assert plan.kind is ArtifactKind.RESPONSE_PLAN
    assert plan.payload["grounded_only"] is True
    assert plan.payload["degraded"] is False
    assert plan.payload["source_paths"] == ("recipes/番茄炒蛋.md",)


def test_expert_classifies_comparison_and_substitution_without_extra_tools() -> None:
    outcome = _run(_FakeRetrievalService(), "黄油和橄榄油有什么区别，可以互相替代吗")
    constraints = outcome.blackboard.artifacts_for(
        kind=ArtifactKind.QUERY_CONSTRAINTS
    )[0]

    assert set(constraints.payload["topics"]) == {"comparison", "substitution"}


def test_expert_degrades_explicitly_when_no_evidence_is_found() -> None:
    outcome = _run(_FakeRetrievalService(with_hits=False))
    evidence = outcome.blackboard.artifacts_for(kind=ArtifactKind.RECIPE_EVIDENCE)[0]

    assert evidence.payload["sufficient"] is False
    assert evidence.metadata["degraded"] is True
    assert outcome.final_artifact.payload["answer_mode"] == "insufficient_evidence"
    assert "没有找到足够信息" in outcome.final_artifact.payload["message"]


def test_knowledge_role_exposes_only_the_search_tool() -> None:
    service = _FakeRetrievalService()
    registry = ToolRegistry([create_recipe_knowledge_tool(service)])  # type: ignore[arg-type]

    assert [tool.name for tool in registry.for_knowledge_expert()] == [
        "search_recipe_knowledge"
    ]

