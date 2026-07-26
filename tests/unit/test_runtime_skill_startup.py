from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from recipe_assistant.agents.coordinator import (
    CollaborativeRecipeCoordinator,
    RecipeCoordinator,
)
from recipe_assistant.agents.events import ExpertCapability
from recipe_assistant.agents.factory import (
    SkillRuntimeConfigurationError,
    build_multi_expert_runtime,
    build_runtime_harness,
)
from recipe_assistant.agents.registry import ExpertNotFoundError
from recipe_assistant.agents.skills import SkillContextAgent
from recipe_assistant.core.config import Settings
from recipe_assistant.core.database import create_session_factory
from recipe_assistant.services.skills import SkillRegistry, SkillValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    yield factory
    engine.dispose()


def _write_skill(root: Path, name: str, *, body: str = "# Rules") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    path = directory / "SKILL.md"
    path.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                'version: "1.0.0"',
                "description: Runtime startup test Skill.",
                "routes:",
                "  - RECIPE_RECOMMENDATION",
                "signals: []",
                "priority: 10",
                "risk: LOW",
                "requires: []",
                "---",
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_runtime_skill_registry_loads_once_before_first_request(
    monkeypatch,
    session_factory,
) -> None:
    calls: list[Path] = []
    original_load = SkillRegistry.load.__func__

    def counting_load(cls, root):
        calls.append(Path(root))
        return original_load(cls, root)

    monkeypatch.setattr(SkillRegistry, "load", classmethod(counting_load))

    harness = build_runtime_harness(_settings(), session_factory)

    assert calls == [(PROJECT_ROOT / "skills").resolve()]
    runtime = harness.runtime_provider()
    assert calls == [(PROJECT_ROOT / "skills").resolve()]
    assert isinstance(runtime.coordinator, CollaborativeRecipeCoordinator)


def test_runtime_registers_all_business_skills_on_independent_agent(
    session_factory,
) -> None:
    registry = SkillRegistry.load(PROJECT_ROOT / "skills")

    runtime = build_multi_expert_runtime(
        _settings(),
        session_factory,
        skill_registry=registry,
    )

    agent = runtime.coordinator.registry.resolve(ExpertCapability.SKILL_SELECTION)
    assert isinstance(agent, SkillContextAgent)
    assert agent.registry is registry
    assert {skill.name for skill in agent.registry.skills} == {
        "allergy_safe_recommendation",
        "ingredient_substitution",
        "source_aware_nutrition_report",
        "weather_aware_recommendation",
    }
    assert agent.name != "multi_expert_runtime_dispatcher"


@pytest.mark.parametrize(
    ("layout", "reason"),
    [
        ("empty", "contains no"),
        ("missing_frontmatter", "missing YAML frontmatter"),
        ("invalid_frontmatter", "invalid YAML frontmatter"),
        ("empty_body", "body must not be empty"),
    ],
)
def test_runtime_skill_invalid_directories_fail_during_assembly(
    tmp_path,
    session_factory,
    layout: str,
    reason: str,
) -> None:
    skill_root = tmp_path / "skills"
    skill_root.mkdir()
    if layout == "missing_frontmatter":
        path = skill_root / "invalid_skill" / "SKILL.md"
        path.parent.mkdir()
        path.write_text("# no frontmatter", encoding="utf-8")
    elif layout == "invalid_frontmatter":
        path = skill_root / "invalid_skill" / "SKILL.md"
        path.parent.mkdir()
        path.write_text("---\nname: [\n---\n# Rules", encoding="utf-8")
    elif layout == "empty_body":
        _write_skill(skill_root, "empty_skill", body="")

    with pytest.raises(SkillRuntimeConfigurationError) as raised:
        build_runtime_harness(
            _settings(),
            session_factory,
            skill_directory=skill_root,
        )

    message = str(raised.value)
    assert str(skill_root.resolve()) in message
    assert reason in message
    assert "# Rules" not in message


def test_runtime_skill_duplicate_name_failure_is_not_silenced(
    monkeypatch,
    session_factory,
    tmp_path,
) -> None:
    skill_root = tmp_path / "skills"
    skill_root.mkdir()

    def duplicate_failure(cls, root):
        del cls, root
        raise SkillValidationError("duplicate Skill name: duplicate_skill")

    monkeypatch.setattr(SkillRegistry, "load", classmethod(duplicate_failure))

    with pytest.raises(
        SkillRuntimeConfigurationError,
        match="duplicate Skill name: duplicate_skill",
    ):
        build_runtime_harness(
            _settings(),
            session_factory,
            skill_directory=skill_root,
        )


def test_runtime_skill_lock_file_does_not_affect_registry(
    tmp_path,
    session_factory,
) -> None:
    skill_root = tmp_path / "skills"
    _write_skill(skill_root, "runtime_skill")
    (tmp_path / "skills-lock.json").write_text(
        '{"skills": [{"name": "not_a_business_skill"}]}',
        encoding="utf-8",
    )

    runtime = build_multi_expert_runtime(
        _settings(),
        session_factory,
        skill_directory=skill_root,
    )

    agent = runtime.coordinator.registry.resolve(ExpertCapability.SKILL_SELECTION)
    assert isinstance(agent, SkillContextAgent)
    assert tuple(skill.name for skill in agent.registry.skills) == ("runtime_skill",)


def test_runtime_skill_fake_registry_and_runtime_injection_skip_file_loading(
    monkeypatch,
    session_factory,
) -> None:
    def unexpected_load(cls, root):
        del cls, root
        raise AssertionError("filesystem registry must not be loaded")

    monkeypatch.setattr(SkillRegistry, "load", classmethod(unexpected_load))
    fake_registry = SkillRegistry(())
    runtime = build_multi_expert_runtime(
        _settings(),
        session_factory,
        skill_registry=fake_registry,
    )
    agent = runtime.coordinator.registry.resolve(ExpertCapability.SKILL_SELECTION)
    assert isinstance(agent, SkillContextAgent)
    assert agent.registry is fake_registry

    fake_runtime = lambda: runtime
    harness = build_runtime_harness(
        _settings(),
        session_factory,
        runtime_provider=fake_runtime,
    )
    assert harness.runtime_provider is fake_runtime


def test_fixed_runtime_does_not_require_or_register_business_skills(
    session_factory,
    tmp_path,
) -> None:
    missing = tmp_path / "missing-skills"

    runtime = build_multi_expert_runtime(
        _settings(),
        session_factory,
        coordination_mode="fixed",
        skill_directory=missing,
    )

    assert isinstance(runtime.coordinator, RecipeCoordinator)
    assert not isinstance(runtime.coordinator, CollaborativeRecipeCoordinator)
    with pytest.raises(ExpertNotFoundError):
        runtime.coordinator.registry.resolve(ExpertCapability.SKILL_SELECTION)
