"""Thin local tools backed by the retrieval service."""

from __future__ import annotations

from pydantic import BaseModel

from recipe_assistant.schemas.retrieval import RetrievalRequest
from recipe_assistant.services.retrieval import RetrievalService
from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.governance import ToolPolicy, ToolRiskLevel
from recipe_assistant.tools.registry import LocalTool
from recipe_assistant.tools.schemas import SearchRecipeKnowledgeInput


def create_recipe_knowledge_tool(retrieval_service: RetrievalService) -> LocalTool:
    """Adapt an existing RetrievalService without owning infrastructure."""

    def search(arguments: BaseModel, context: ToolContext) -> dict:
        del context
        parsed = SearchRecipeKnowledgeInput.model_validate(arguments)
        result = retrieval_service.retrieve(
            RetrievalRequest(
                query=parsed.query,
                strategy=parsed.strategy,
                recipe_names=parsed.recipe_names,
                include_ingredients=parsed.include_ingredients,
                exclude_ingredients=parsed.exclude_ingredients,
                tools=parsed.tools,
                categories=parsed.categories,
                top_k=parsed.top_k,
                candidate_k=max(20, parsed.top_k),
            )
        )
        return result.model_dump(mode="json")

    return LocalTool(
        name="search_recipe_knowledge",
        description="检索菜谱知识、食材、步骤和相关依据。",
        args_schema=SearchRecipeKnowledgeInput,
        handler=search,
        policy=ToolPolicy(risk_level=ToolRiskLevel.READ_ONLY),
    )
