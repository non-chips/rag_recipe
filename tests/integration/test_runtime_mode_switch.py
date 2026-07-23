from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from recipe_assistant.agents.factory import build_runtime_harness
from recipe_assistant.agents.result import ProfileSnapshot, RunContext, RunStatus
from recipe_assistant.core.config import Settings
from recipe_assistant.core.database import create_session_factory


class _Runtime:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def run(self, context, decision):
        del context, decision
        if self.fail:
            raise RuntimeError("v2 failed")


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


def _context() -> RunContext:
    return RunContext(
        run_id="runtime-mode",
        user_id=1,
        session_id=1,
        session_public_id="runtime-session",
        original_input="宫保鸡丁怎么做？",
        normalized_input="宫保鸡丁怎么做？",
        profile=ProfileSnapshot(),
    )


def test_v2_is_the_only_runtime_mode() -> None:
    settings = Settings(_env_file=None)
    assert settings.agent_runtime_mode == "v2"
    assert settings.legacy_fallback_enabled is False


def test_development_rejects_legacy_mode() -> None:
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            app_env="development",
            agent_runtime_mode="legacy",
        )


def test_development_rejects_shadow_mode() -> None:
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            app_env="development",
            agent_runtime_mode="shadow",
        )


def test_development_rejects_legacy_fallback() -> None:
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            app_env="development",
            legacy_fallback_enabled=True,
        )


@pytest.mark.parametrize("mode", ["legacy", "shadow"])
def test_production_rejects_non_v2_mode(mode: str) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="production", agent_runtime_mode=mode)


def test_production_rejects_legacy_fallback() -> None:
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            app_env="production",
            legacy_fallback_enabled=True,
        )


def test_v2_failure_returns_failure_without_fallback() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    harness = build_runtime_harness(
        _settings(),
        create_session_factory(engine),
        runtime_provider=lambda: _Runtime(fail=True),
    )
    outcome = harness.run(_context())
    engine.dispose()

    assert outcome.result.status is RunStatus.FAILED
    assert outcome.result.used_legacy_executor is False
    assert not any(event["type"].startswith("legacy") for event in outcome.result.events)
