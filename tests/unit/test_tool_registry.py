from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from recipe_assistant.schemas.retrieval import RetrievalResult, RetrievalStrategy
from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.governance import ToolPolicy, ToolRiskLevel
from recipe_assistant.tools.recipe_knowledge_tools import create_recipe_knowledge_tool
from recipe_assistant.tools.registry import LocalTool, ToolRegistry
from recipe_assistant.tools.schemas import (
    SearchRecipeKnowledgeInput,
    ToolArguments,
    ToolRole,
)


class _QueryInput(ToolArguments):
    query: str = Field(min_length=1)


def _context() -> ToolContext:
    return ToolContext(
        run_id="run-1",
        user_id=42,
        session_id="session-1",
        route="recipe_knowledge",
        permissions=frozenset({"user_data:read", "user_data:write"}),
    )


def _tool(name: str) -> LocalTool:
    def handler(arguments: BaseModel, context: ToolContext) -> dict[str, Any]:
        return {
            "query": arguments.model_dump()["query"],
            "injected_user_id": context.user_id,
        }

    return LocalTool(
        name=name,
        description=name,
        args_schema=_QueryInput,
        handler=handler,
        policy=ToolPolicy(ToolRiskLevel.READ_ONLY),
    )


def test_registry_exposes_distinct_role_allowlists() -> None:
    names = [
        "ask_recipe_knowledge_expert",
        "ask_recipe_recommendation_expert",
        "ask_nutrition_planning_expert",
        "search_recipe_knowledge",
        "recommend_recipes",
        "calculate_recipe_nutrition",
    ]
    registry = ToolRegistry(_tool(name) for name in names)

    assert [tool.name for tool in registry.for_coordinator()] == names[:3]
    assert [tool.name for tool in registry.for_knowledge_expert()] == [
        "search_recipe_knowledge"
    ]
    assert [tool.name for tool in registry.for_recommendation_expert()] == [
        "search_recipe_knowledge",
        "recommend_recipes",
    ]
    assert [tool.name for tool in registry.for_nutrition_expert()] == [
        "search_recipe_knowledge",
        "calculate_recipe_nutrition",
    ]


def test_tool_context_is_injected_and_not_exposed_in_argument_schema() -> None:
    registry = ToolRegistry([_tool("search_recipe_knowledge")])

    result = registry.invoke(
        role=ToolRole.KNOWLEDGE_EXPERT,
        tool_name="search_recipe_knowledge",
        arguments={"query": "番茄炒蛋"},
        context=_context(),
    )

    assert result.output == {"query": "番茄炒蛋", "injected_user_id": 42}
    assert "user_id" not in _QueryInput.model_fields
    assert "session_id" not in _QueryInput.model_fields


def test_registry_rejects_schema_that_exposes_protected_context() -> None:
    class _UnsafeInput(ToolArguments):
        user_id: int

    unsafe = LocalTool(
        name="unsafe",
        description="unsafe",
        args_schema=_UnsafeInput,
        handler=lambda _arguments, _context: None,
        policy=ToolPolicy(ToolRiskLevel.READ_ONLY),
    )

    try:
        ToolRegistry([unsafe])
    except ValueError as exc:
        assert "user_id" in str(exc)
    else:
        raise AssertionError("protected tool argument should be rejected")


class _FakeRetrievalService:
    def __init__(self) -> None:
        self.requests = []

    def retrieve(self, request):
        self.requests.append(request)
        return RetrievalResult(
            query=request.query,
            strategy=request.strategy or RetrievalStrategy.ADVANCED_HYBRID,
        )


def test_recipe_knowledge_tool_delegates_to_existing_service() -> None:
    service = _FakeRetrievalService()
    tool = create_recipe_knowledge_tool(service)  # type: ignore[arg-type]
    registry = ToolRegistry([tool])

    result = registry.invoke(
        role=ToolRole.KNOWLEDGE_EXPERT,
        tool_name="search_recipe_knowledge",
        arguments={"query": "清蒸鱼", "top_k": 3},
        context=_context(),
    )

    assert service.requests[0].query == "清蒸鱼"
    assert service.requests[0].top_k == 3
    assert result.output["query"] == "清蒸鱼"
    assert "user_id" not in SearchRecipeKnowledgeInput.model_fields
