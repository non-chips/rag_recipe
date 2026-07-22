from recipe_assistant.services.constraint import (
    ConstraintService,
    PreferenceContext,
    RecipeCandidate,
    TemporaryConstraints,
)


def _candidate(**updates) -> RecipeCandidate:
    values = {
        "recipe_id": "safe",
        "recipe_name": "番茄炒蛋",
        "ingredients": ("番茄", "鸡蛋"),
        "tools": ("炒锅",),
        "cook_time_minutes": 12,
        "source_path": "recipes/safe.md",
        "evidence": "可核验菜谱证据",
    }
    values.update(updates)
    return RecipeCandidate(**values)


def test_allergen_and_excluded_ingredients_are_hard_filtered() -> None:
    validation = ConstraintService().validate(
        (
            _candidate(),
            _candidate(recipe_id="peanut", ingredients=("鸡肉", "花生")),
            _candidate(recipe_id="celery", ingredients=("芹菜", "豆干")),
        ),
        TemporaryConstraints(excluded_ingredients=("芹菜",)),
        PreferenceContext(allergens=("花生",)),
    )

    assert [candidate.recipe_id for candidate in validation.accepted] == ["safe"]
    reasons = {item.candidate.recipe_id: item.reasons for item in validation.rejected}
    assert "allergen_conflict" in reasons["peanut"]
    assert "excluded_ingredient_conflict" in reasons["celery"]


def test_tool_time_and_source_constraints_fail_closed_on_missing_data() -> None:
    validation = ConstraintService().validate(
        (
            _candidate(recipe_id="unknown", tools=(), cook_time_minutes=None),
            _candidate(recipe_id="slow", cook_time_minutes=45),
            _candidate(recipe_id="unsourced", source_path=""),
        ),
        TemporaryConstraints(available_tools=("炒锅",), max_time_minutes=20),
        PreferenceContext(),
    )

    assert validation.accepted == ()
    reasons = {item.candidate.recipe_id: item.reasons for item in validation.rejected}
    assert {"missing_tool_data", "missing_time_data"}.issubset(reasons["unknown"])
    assert "time_limit_exceeded" in reasons["slow"]
    assert "missing_evidence_source" in reasons["unsourced"]


def test_disliked_ingredients_are_separate_from_temporary_exclusions() -> None:
    constraints = TemporaryConstraints(excluded_ingredients=("香菜",))
    preferences = PreferenceContext(disliked_ingredients=("葱",))

    validation = ConstraintService().validate(
        (_candidate(ingredients=("鸡蛋", "葱")),),
        constraints,
        preferences,
    )

    assert constraints.excluded_ingredients == ("香菜",)
    assert preferences.disliked_ingredients == ("葱",)
    assert validation.rejected[0].reasons == ("disliked_ingredient_conflict",)

