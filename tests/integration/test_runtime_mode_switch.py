from __future__ import annotations

from threading import Event

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from recipe_assistant.agents.events import AgentArtifact, ArtifactKind
from recipe_assistant.agents.factory import build_runtime_harness
from recipe_assistant.agents.result import ProfileSnapshot, RunContext, RunStatus
from recipe_assistant.core.config import Settings
from recipe_assistant.core.database import create_session_factory


class _Status:
    value = "SUCCEEDED"


class _Board:
    def __init__(self, artifact: AgentArtifact) -> None:
        self.artifacts = (artifact,)

    @staticmethod
    def trace_events() -> list[dict]:
        return [{"type": "task_completed", "actor": "fake_v2"}]


class _Outcome:
    def __init__(self, artifact: AgentArtifact) -> None:
        self.final_artifact = artifact
        self.blackboard = _Board(artifact)
        self.status = _Status()


class _Runtime:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def run(self, context, decision):
        del decision
        self.calls += 1
        if self.fail:
            raise RuntimeError("v2 failed")
        return _Outcome(
            AgentArtifact(
                id=f"{context.run_id}:final",
                owner="fake_v2",
                kind=ArtifactKind.RESPONSE_PLAN,
                payload={
                    "message": "请依据证据回答。",
                    "evidence": [
                        {
                            "recipe_id": "recipe-1",
                            "recipe_name": "测试菜",
                            "content": "V2 主响应",
                            "source_path": "recipes/test.md",
                            "retrieval_sources": ["fixture"],
                        }
                    ],
                },
                confidence=1.0,
                task_id="fake.response",
            )
        )


class _Legacy:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, query: str, thread_id: str) -> str:
        del query, thread_id
        self.calls += 1
        return "legacy response"


def _factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine, create_session_factory(engine)


def _settings(mode: str, *, fallback: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        agent_runtime_mode=mode,
        legacy_fallback_enabled=fallback,
        chat_enabled=False,
        embedding_enabled=False,
        chroma_enabled=False,
        bm25_enabled=False,
        neo4j_enabled=False,
        weather_enabled=False,
    )


def _context(run_id: str = "runtime-mode") -> RunContext:
    return RunContext(
        run_id=run_id,
        user_id=1,
        session_id=1,
        session_public_id="runtime-session",
        original_input="宫保鸡丁怎么做？",
        normalized_input="宫保鸡丁怎么做？",
        profile=ProfileSnapshot(),
    )


def _harness(mode: str, runtime: _Runtime, legacy: _Legacy, **kwargs):
    engine, factory = _factory()
    harness = build_runtime_harness(
        _settings(mode, fallback=kwargs.pop("fallback", False)),
        factory,
        legacy,
        runtime_provider=lambda: runtime,
        **kwargs,
    )
    return engine, harness


def test_v2_is_default_and_does_not_call_legacy() -> None:
    settings = Settings(_env_file=None)
    assert settings.agent_runtime_mode == "v2"
    assert settings.legacy_fallback_enabled is False

    runtime = _Runtime()
    legacy = _Legacy()
    engine, harness = _harness("v2", runtime, legacy)
    outcome = harness.run(_context())
    engine.dispose()

    assert outcome.result.status is RunStatus.SUCCEEDED
    assert outcome.result.final_text == "测试菜：V2 主响应"
    assert outcome.result.used_legacy_executor is False
    assert runtime.calls == 1
    assert legacy.calls == 0


def test_legacy_mode_is_explicit_developer_regression_path() -> None:
    runtime = _Runtime()
    legacy = _Legacy()
    engine, harness = _harness("legacy", runtime, legacy)
    outcome = harness.run(_context())
    engine.dispose()

    assert outcome.result.final_text == "legacy response"
    assert outcome.result.used_legacy_executor is True
    assert runtime.calls == 0
    assert legacy.calls == 1


def test_shadow_returns_v2_and_records_legacy_out_of_band() -> None:
    runtime = _Runtime()
    legacy = _Legacy()
    recorded = []
    finished = Event()

    def sink(record):
        recorded.append(record)
        finished.set()

    engine, harness = _harness("shadow", runtime, legacy, shadow_sink=sink)
    outcome = harness.run(_context("shadow-run"))

    assert outcome.result.final_text == "测试菜：V2 主响应"
    assert outcome.result.used_legacy_executor is False
    assert finished.wait(2)
    engine.dispose()
    assert recorded[0]["run_id"] == "shadow-run"
    assert recorded[0]["status"] == "succeeded"
    assert legacy.calls == 1


def test_v2_failure_never_uses_legacy_unless_explicitly_enabled() -> None:
    runtime = _Runtime(fail=True)
    legacy = _Legacy()
    engine, harness = _harness("v2", runtime, legacy)
    failed = harness.run(_context())
    engine.dispose()

    assert failed.result.status is RunStatus.FAILED
    assert legacy.calls == 0

    runtime = _Runtime(fail=True)
    legacy = _Legacy()
    engine, harness = _harness("v2", runtime, legacy, fallback=True)
    recovered = harness.run(_context())
    engine.dispose()
    assert recovered.result.status is RunStatus.SUCCEEDED
    assert recovered.result.final_text == "legacy response"
    assert recovered.result.used_legacy_executor is True


@pytest.mark.parametrize("mode", ["legacy", "shadow"])
def test_production_rejects_legacy_modes(mode: str) -> None:
    with pytest.raises(ValueError, match="development/test only"):
        Settings(_env_file=None, app_env="production", agent_runtime_mode=mode)


def test_production_rejects_legacy_fallback() -> None:
    with pytest.raises(ValueError, match="fallback"):
        Settings(
            _env_file=None,
            app_env="production",
            legacy_fallback_enabled=True,
        )
