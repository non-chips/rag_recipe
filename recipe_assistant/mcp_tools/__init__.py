"""Optional high-level MCP adapters; importing this package requires no MCP runtime."""

from recipe_assistant.mcp_tools.facade import McpToolFacade
from recipe_assistant.mcp_tools.nutrition_tools import NutritionMcpTools
from recipe_assistant.mcp_tools.recipe_tools import RecipeMcpTools
from recipe_assistant.mcp_tools.recommendation_tools import RecommendationMcpTools

__all__ = [
    "McpToolFacade",
    "NutritionMcpTools",
    "RecipeMcpTools",
    "RecommendationMcpTools",
]
