"""Recipe interaction API DTOs."""

from datetime import datetime

from pydantic import Field

from recipe_assistant.models.recipe_interaction import InteractionType
from recipe_assistant.schemas.api.common import ApiSchema


class RecipeInteractionCreate(ApiSchema):
    recipe_id: str = Field(min_length=1, max_length=100)
    event_type: InteractionType
    servings: float | None = Field(default=None, gt=0)
    source: str | None = Field(default=None, max_length=100)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    occurred_at: datetime | None = None


class RecipeInteractionRead(RecipeInteractionCreate):
    id: int
    user_id: int
    session_id: int | None
    occurred_at: datetime
