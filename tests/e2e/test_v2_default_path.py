from __future__ import annotations

import sys

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from recipe_assistant.agents.events import AgentArtifact, ArtifactKind
from recipe_assistant.agents.factory import (
    MultiExpertHarness,
    build_runtime_harness,
    observe_harness,
)
from recipe_assistant.agents.result import ProfileSnapshot, RunContext
from recipe_assistant.api.dependencies import ApiContainer
from recipe_assistant.core.config import Settings
from recipe_assistant.core.database import create_session_factory


class _Status:
    value = "SUCCEEDED"


class _Board:
    def __init__(self, artifact: AgentArtifact) -> None:
        self.artifacts = (artifact,)

    @staticmethod
    def trace_events() -> list[dict]:
        return []


class _Outcome:
    def __init__(self, artifact: AgentArtifact) -> None:
        self.final_artifact = artifact
        self.blackboard = _Board(artifact)
        self.status = _Status()


class _ReplayRuntime:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, context, decision):
        del decision
        self.calls += 1
        return _Outcome(
            AgentArtifact(
                id=f"{context.run_id}:replay",
                owner="replay_v2",
                kind=ArtifactKind.RESPONSE_PLAN,
                payload={"message": "V2 replay response"},
                confidence=1.0,
                task_id="replay.response",
            )
        )


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        agent_runtime_mode="v2",
        legacy_fallback_enabled=False,
        chat_enabled=False,
        embedding_enabled=False,
        chroma_enabled=False,
        bm25_enabled=False,
        neo4j_enabled=False,
        weather_enabled=False,
    )


def _contexts() -> list[RunContext]:
    queries = [
        "你好",
        "宫保鸡丁怎么做？",
        "推荐一道晚饭",
        "根据北京天气推荐晚饭",
        "总结我上周的饮食",
        "根据上周营养情况推荐今晚菜谱",
    ]
    return [
        RunContext(
            run_id=f"replay-{index:03d}",
            user_id=1,
            session_id=1,
            session_public_id="replay-session",
            original_input=query,
            normalized_input=query,
            profile=ProfileSnapshot(),
        )
        for index, query in enumerate(queries * 20)
    ]


def test_default_container_selects_v2_without_importing_legacy_agent() -> None:
    legacy_was_loaded = "agent.react_agent" in sys.modules
    container = ApiContainer.build_default(_settings())
    try:
        harness = container.chat_runner.harness
        assert isinstance(harness, MultiExpertHarness)
        assert harness.mode == "v2"
        assert ("agent.react_agent" in sys.modules) is legacy_was_loaded
    finally:
        container.engine.dispose()


def test_default_v2_mode_passes_120_artificial_replays() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = create_session_factory(engine)
    runtime = _ReplayRuntime()
    harness = build_runtime_harness(
        _settings(),
        factory,
        runtime_provider=lambda: runtime,
    )

    report = observe_harness(harness, _contexts())
    engine.dispose()

    assert report["runtime_mode"] == "v2"
    assert report["total"] == 120
    assert report["passed"] == 120
    assert report["failed"] == 0
    assert report["legacy_primary_responses"] == 0
    assert runtime.calls == 100
    assert report["routes"] == {
        "COMPLEX": 20,
        "NUTRITION_PLANNING": 20,
        "RECIPE_KNOWLEDGE": 20,
        "RECIPE_RECOMMENDATION": 40,
        "SIMPLE": 20,
    }


def test_real_v2_assembly_degrades_without_retrieval_and_never_calls_legacy() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    harness = build_runtime_harness(
        _settings(),
        create_session_factory(engine),
    )

    outcome = harness.run(_contexts()[1])
    engine.dispose()

    assert outcome.result.status.value == "SUCCEEDED"
    assert outcome.result.used_legacy_executor is False
    assert "没有找到足够信息" in outcome.result.final_text
