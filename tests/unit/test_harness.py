from __future__ import annotations

from datetime import timezone

from recipe_assistant.agents.events import AgentArtifact, ArtifactKind
from recipe_assistant.agents.factory import MultiExpertHarness
from recipe_assistant.agents.result import ProfileSnapshot, RunContext, RunStatus
from recipe_assistant.schemas.agent.route import RouteType


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


class _Runtime:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def run(self, context, decision):
        del decision
        self.calls += 1
        if self.fail:
            raise RuntimeError("v2 unavailable")
        artifact = AgentArtifact(
            id=f"{context.run_id}:response",
            owner="test_v2",
            kind=ArtifactKind.RESPONSE_PLAN,
            payload={"message": "V2 最终回答"},
            confidence=1.0,
            task_id="test.response",
        )
        return _Outcome(artifact)


def _context(query: str) -> RunContext:
    return RunContext(
        user_id=1,
        session_id=2,
        session_public_id="session-public",
        original_input=query,
        normalized_input=MultiExpertHarness.normalize_input(query),
        profile=ProfileSnapshot(),
    )


def test_simple_route_bypasses_multi_expert_runtime() -> None:
    runtime = _Runtime()
    harness = MultiExpertHarness(runtime_provider=lambda: runtime)
    outcome = harness.run(_context("你好"))

    assert outcome.route_decision.route is RouteType.SIMPLE
    assert outcome.result.status is RunStatus.SUCCEEDED
    assert outcome.result.used_legacy_executor is False
    assert runtime.calls == 0
    assert outcome.context.started_at.utcoffset() == timezone.utc.utcoffset(None)


def test_non_simple_route_returns_v2_artifact_answer() -> None:
    runtime = _Runtime()
    harness = MultiExpertHarness(runtime_provider=lambda: runtime)
    outcome = harness.run(_context("  宫保鸡丁   怎么做？ "))

    assert outcome.route_decision.route is RouteType.RECIPE_KNOWLEDGE
    assert outcome.result.final_text == "V2 最终回答"
    assert outcome.result.used_legacy_executor is False
    assert runtime.calls == 1


def test_input_normalization_is_stable() -> None:
    assert MultiExpertHarness.normalize_input("  清蒸鱼   怎么做  ") == "清蒸鱼 怎么做"


def test_runtime_failure_becomes_structured_outcome_without_fallback() -> None:
    harness = MultiExpertHarness(runtime_provider=lambda: _Runtime(fail=True))
    outcome = harness.run(_context("红烧肉怎么做？"))

    assert outcome.result.status is RunStatus.FAILED
    assert outcome.result.error == "v2 unavailable"
    assert outcome.result.used_legacy_executor is False
    assert outcome.result.events[-1]["type"] == "execution_error"
