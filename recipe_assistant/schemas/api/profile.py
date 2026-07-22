"""Explicit user profile API DTOs."""

from datetime import datetime

from pydantic import AliasChoices, Field

from recipe_assistant.schemas.api.common import ApiSchema


class UserProfileUpdate(ApiSchema):
    preferred_cuisines: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("preferred_cuisines", "preferred_cuisines_json"),
    )
    disliked_ingredients: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "disliked_ingredients", "disliked_ingredients_json"
        ),
    )
    allergens: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("allergens", "allergens_json"),
    )
    available_appliances: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "available_appliances", "available_appliances_json"
        ),
    )
    default_servings: int | None = Field(default=None, ge=1, le=100)
    skill_level: str | None = Field(default=None, max_length=50)
    planning_goal: str | None = Field(default=None, max_length=255)


class UserProfileRead(UserProfileUpdate):
    user_id: int
    created_at: datetime
    updated_at: datetime
