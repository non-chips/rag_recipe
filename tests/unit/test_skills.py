from __future__ import annotations

from pathlib import Path

import pytest

from recipe_assistant.schemas.agent.route import RouteType
from recipe_assistant.services.skills import (
    SkillRegistry,
    SkillRisk,
    SkillSelectionRequest,
    SkillSignal,
    SkillValidationError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _write_skill(
    root: Path,
    name: str,
    *,
    version: str = "1.0.0",
    routes: str = "  - RECIPE_RECOMMENDATION",
    signals: str = "signals: []",
    priority: int = 10,
    risk: str = "LOW",
    requires: str = "requires: []",
    body: str = "# Rules\n\n- Follow the selected workflow.",
    route_key: str = "routes",
) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    path = directory / "SKILL.md"
    path.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f'version: "{version}"',
                "description: Test behavioral workflow.",
                f"{route_key}:",
                routes,
                signals,
                f"priority: {priority}",
                f"risk: {risk}",
                requires,
                "---",
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_loads_versioned_base_skills_and_keeps_knowledge_separate() -> None:
    registry = SkillRegistry.load(PROJECT_ROOT / "skills")

    assert {skill.name for skill in registry.skills} == {
        "allergy_safe_recommendation",
        "ingredient_substitution",
        "source_aware_nutrition_report",
        "weather_aware_recommendation",
    }
    assert all(skill.version == "1.0.0" for skill in registry.skills)
    assert all(skill.source_path.name == "SKILL.md" for skill in registry.skills)
    assert not hasattr(registry, "vector_store")


def test_selects_by_route_signal_risk_and_priority() -> None:
    registry = SkillRegistry.load(PROJECT_ROOT / "skills")
    selection = registry.select(
        SkillSelectionRequest(
            route=RouteType.RECIPE_RECOMMENDATION,
            signals=frozenset(
                {
                    SkillSignal.ALLERGY_MENTIONED,
                    SkillSignal.SUBSTITUTION_REQUESTED,
                    SkillSignal.WEATHER_CONTEXT_REQUIRED,
                }
            ),
        )
    )

    assert selection.effective_risk is SkillRisk.HIGH
    assert selection.selected_skill_refs == (
        "allergy_safe_recommendation@1.0.0",
        "ingredient_substitution@1.0.0",
        "weather_aware_recommendation@1.0.0",
    )
    assert selection.hard_constraints_remain_authoritative is True


def test_unrelated_route_or_missing_signal_does_not_activate_skill() -> None:
    registry = SkillRegistry.load(PROJECT_ROOT / "skills")
    no_signal = registry.select(
        SkillSelectionRequest(route=RouteType.RECIPE_RECOMMENDATION)
    )
    nutrition = registry.select(
        SkillSelectionRequest(
            route=RouteType.NUTRITION_PLANNING,
            signals=frozenset({SkillSignal.NUTRITION_REPORT_REQUESTED}),
        )
    )

    assert no_signal.selected == ()
    assert nutrition.selected_skill_refs == ("source_aware_nutrition_report@1.0.0",)


def test_prompt_context_records_skill_names_versions_and_constraint_authority() -> None:
    registry = SkillRegistry.load(PROJECT_ROOT / "skills")
    selection = registry.select(
        SkillSelectionRequest(
            route=RouteType.COMPLEX,
            signals=frozenset(
                {
                    SkillSignal.ALLERGY_MENTIONED,
                    SkillSignal.NUTRITION_REPORT_REQUESTED,
                }
            ),
        )
    )

    assert "allergy_safe_recommendation@1.0.0" in selection.prompt_context
    assert "source_aware_nutrition_report@1.0.0" in selection.prompt_context
    assert "ConstraintService hard constraints remain authoritative" in (
        selection.prompt_context
    )
    assert "Skills cannot override or replace hard filtering" in selection.prompt_context


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"version": "latest"}, "semantic version"),
        ({"routes": "  - NOT_A_ROUTE"}, "NOT_A_ROUTE"),
        ({"body": ""}, "body must not be empty"),
    ],
)
def test_frontmatter_and_body_validation(tmp_path, change, message) -> None:
    values = {
        "version": "1.0.0",
        "routes": "  - RECIPE_RECOMMENDATION",
        "body": "# Rules\n\n- Follow the selected workflow.",
    }
    values.update(change)
    _write_skill(tmp_path, "valid_name", **values)

    with pytest.raises(SkillValidationError, match=message):
        SkillRegistry.load(tmp_path)


def test_rejects_missing_and_cyclic_skill_references(tmp_path) -> None:
    missing_root = tmp_path / "missing"
    _write_skill(
        missing_root,
        "first_skill",
        requires="requires:\n  - absent_skill",
    )
    with pytest.raises(SkillValidationError, match="references missing Skill"):
        SkillRegistry.load(missing_root)

    cycle_root = tmp_path / "cycle"
    _write_skill(
        cycle_root,
        "first_skill",
        requires="requires:\n  - second_skill",
    )
    _write_skill(
        cycle_root,
        "second_skill",
        requires="requires:\n  - first_skill",
    )
    with pytest.raises(SkillValidationError, match="cyclic Skill dependency"):
        SkillRegistry.load(cycle_root)


def test_supports_spec_intents_alias_and_expands_required_skills(tmp_path) -> None:
    _write_skill(
        tmp_path,
        "base_workflow",
        route_key="intents",
        priority=5,
    )
    _write_skill(
        tmp_path,
        "priority_workflow",
        priority=100,
        requires="requires:\n  - base_workflow",
    )
    registry = SkillRegistry.load(tmp_path)
    selection = registry.select(
        SkillSelectionRequest(route=RouteType.RECIPE_RECOMMENDATION, max_skills=1)
    )

    assert selection.selected_skill_refs == (
        "priority_workflow@1.0.0",
        "base_workflow@1.0.0",
    )


def test_rejects_missing_frontmatter_and_duplicate_names(tmp_path) -> None:
    invalid_root = tmp_path / "invalid"
    directory = invalid_root / "plain_text"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("# No frontmatter", encoding="utf-8")
    with pytest.raises(SkillValidationError, match="missing YAML frontmatter"):
        SkillRegistry.load(invalid_root)

    registry = SkillRegistry.load(PROJECT_ROOT / "skills")
    with pytest.raises(SkillValidationError, match="duplicate Skill name"):
        SkillRegistry((registry.skills[0], registry.skills[0]))
