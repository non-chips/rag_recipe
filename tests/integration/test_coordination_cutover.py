from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from recipe_assistant.agents.coordinator import (
    CollaborativeRecipeCoordinator,
    RecipeCoordinator,
)
from recipe_assistant.agents.factory import build_multi_expert_runtime
from recipe_assistant.core.config import Settings
from recipe_assistant.core.database import create_session_factory
from scripts.compare_coordination_modes import (
    CoordinationModeEvaluator,
    write_reports,
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        chat_enabled=False,
        embedding_enabled=False,
        chroma_enabled=False,
        bm25_enabled=False,
        neo4j_enabled=False,
        weather_enabled=False,
    )


def test_collaborative_is_default_and_fixed_remains_explicit_rollback() -> None:
    settings = _settings()
    assert settings.agent_coordination_mode == "collaborative"

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    collaborative = build_multi_expert_runtime(
        settings,
        factory,
        coordination_mode=settings.agent_coordination_mode,
    )
    fixed = build_multi_expert_runtime(
        settings,
        factory,
        coordination_mode="fixed",
    )

    assert isinstance(
        collaborative.coordinator,
        CollaborativeRecipeCoordinator,
    )
    assert collaborative.coordination_mode == "collaborative"
    assert isinstance(fixed.coordinator, RecipeCoordinator)
    assert not isinstance(fixed.coordinator, CollaborativeRecipeCoordinator)
    assert fixed.coordination_mode == "fixed"
    engine.dispose()


def test_cutover_report_is_reproducible_and_all_gates_pass(tmp_path) -> None:
    report = CoordinationModeEvaluator().run()
    write_reports(report, tmp_path)

    assert report["cutover_approved"] is True
    assert all(report["gates"].values())
    assert (
        report["modes"]["collaborative"]["metrics"]["case_pass_rate"]
        == 1.0
    )
    assert (
        report["modes"]["collaborative"]["metrics"][
            "hard_constraint_violations"
        ]
        == 0
    )
    assert report["comparison"]["collaborative_to_fixed_p95_ratio"] <= 1.25
    collaborative_cases = report["modes"]["collaborative"]["cases"]
    assert all(case["passed"] for case in collaborative_cases)
    assert {case["category"] for case in collaborative_cases} == {
        "qa",
        "no_evidence",
        "recommendation",
        "allergen",
        "weather",
        "tool_degradation",
        "food_safety",
        "nutrition",
    }
    written = json.loads(
        (tmp_path / "coordination_cutover_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert written["schema_version"] == "coordination-cutover-v1"
    assert (tmp_path / "coordination_cutover_report.md").exists()
