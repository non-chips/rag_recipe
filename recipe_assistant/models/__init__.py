"""Persistence entity exports and metadata registration."""

from recipe_assistant.core.database import Base
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.message import ChatMessage, MessageRole
from recipe_assistant.models.recipe_interaction import InteractionType, RecipeInteraction
from recipe_assistant.models.session import ChatSession
from recipe_assistant.models.user import UserAccount, UserProfile

__all__ = [
    "AgentRunTrace",
    "Base",
    "ChatMessage",
    "ChatSession",
    "InteractionType",
    "MessageRole",
    "RecipeInteraction",
    "UserAccount",
    "UserProfile",
]
