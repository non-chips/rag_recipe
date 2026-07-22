"""Deterministic hard constraints for recipe recommendations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ConstraintModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class TemporaryConstraints(ConstraintModel):
    available_ingredients: tuple[str, ...] = ()
    excluded_ingredients: tuple[str, ...] = ()
    available_tools: tuple[str, ...] = ()
    max_time_minutes: int | None = Field(default=None, ge=1)
    city: str = ""


class PreferenceContext(ConstraintModel):
    preferred_cuisines: tuple[str, ...] = ()
    disliked_ingredients: tuple[str, ...] = ()
    allergens: tuple[str, ...] = ()


class RecipeCandidate(ConstraintModel):
    recipe_id: str = Field(min_length=1)
    recipe_name: str | None = None
    ingredients: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    cook_time_minutes: int | None = Field(default=None, ge=1)
    category: str = ""
    weather_tags: tuple[str, ...] = ()
    source_path: str = ""
    evidence: str = ""
    retrieval_score: float = 0.0
    ranking_score: float = 0.0
    ranking_features: dict[str, float] = Field(default_factory=dict)


class RejectedCandidate(ConstraintModel):
    candidate: RecipeCandidate
    reasons: tuple[str, ...]


class ConstraintValidationResult(ConstraintModel):
    accepted: tuple[RecipeCandidate, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()
    hard_constraints_applied: tuple[str, ...] = ()


def _normalized(values: tuple[str, ...]) -> set[str]:
    return {value.strip().casefold() for value in values if value.strip()}


class ConstraintService:
    """Apply hard filters that cannot be overridden by an LLM."""

    def validate(
        self,
        candidates: tuple[RecipeCandidate, ...],
        constraints: TemporaryConstraints,
        preferences: PreferenceContext,
    ) -> ConstraintValidationResult:
        excluded = _normalized(constraints.excluded_ingredients)
        allergens = _normalized(preferences.allergens)
        disliked = _normalized(preferences.disliked_ingredients)
        available_tools = _normalized(constraints.available_tools)
        applied: list[str] = ["data_source"]
        if excluded:
            applied.append("excluded_ingredients")
        if allergens:
            applied.append("allergens")
        if disliked:
            applied.append("disliked_ingredients")
        if available_tools:
            applied.append("available_tools")
        if constraints.max_time_minutes is not None:
            applied.append("max_time_minutes")

        accepted: list[RecipeCandidate] = []
        rejected: list[RejectedCandidate] = []
        for candidate in candidates:
            reasons: list[str] = []
            ingredients = _normalized(candidate.ingredients)
            if not candidate.source_path or not candidate.evidence:
                reasons.append("missing_evidence_source")
            if (excluded or allergens or disliked) and not ingredients:
                reasons.append("missing_ingredient_data")
            if ingredients & excluded:
                reasons.append("excluded_ingredient_conflict")
            if ingredients & allergens:
                reasons.append("allergen_conflict")
            if ingredients & disliked:
                reasons.append("disliked_ingredient_conflict")
            if available_tools:
                candidate_tools = _normalized(candidate.tools)
                if not candidate_tools:
                    reasons.append("missing_tool_data")
                elif not candidate_tools.issubset(available_tools):
                    reasons.append("unavailable_tool")
            if constraints.max_time_minutes is not None:
                if candidate.cook_time_minutes is None:
                    reasons.append("missing_time_data")
                elif candidate.cook_time_minutes > constraints.max_time_minutes:
                    reasons.append("time_limit_exceeded")
            if reasons:
                rejected.append(RejectedCandidate(candidate=candidate, reasons=tuple(reasons)))
            else:
                accepted.append(candidate)
        return ConstraintValidationResult(
            accepted=tuple(accepted),
            rejected=tuple(rejected),
            hard_constraints_applied=tuple(applied),
        )
