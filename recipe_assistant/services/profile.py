"""Read-only profile snapshot service for one agent run."""

from recipe_assistant.agents.result import ProfileSnapshot
from recipe_assistant.repositories.interfaces import ProfileRepository


class ProfileService:
    def __init__(self, repository: ProfileRepository) -> None:
        self.repository = repository

    def load_snapshot(self, user_id: int) -> ProfileSnapshot:
        profile = self.repository.get(user_id)
        if profile is None:
            return ProfileSnapshot()
        return ProfileSnapshot(
            preferred_cuisines=list(profile.preferred_cuisines_json or []),
            disliked_ingredients=list(profile.disliked_ingredients_json or []),
            allergens=list(profile.allergens_json or []),
            available_appliances=list(profile.available_appliances_json or []),
            default_servings=profile.default_servings,
            skill_level=profile.skill_level,
            planning_goal=profile.planning_goal,
        )
