from __future__ import annotations

from datetime import timezone

from recipe_assistant.agents.harness import (
    LegacyReactAgentAdapter,
    RecipeAgentHarness,
)
from recipe_assistant.agents.result import (
    ProfileSnapshot,
    RunContext,
    RunStatus,
)
from recipe_assistant.agents.router import BusinessRouter
from recipe_assistant.schemas.agent.route import RouteType
from recipe_assistant.services.simple_chat import SimpleChatService


class _Executor:
    def __init__(self, response: str = "旧执行器最终回答", *, fail: bool = False) -> None:
        self.response = response
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def execute(self, query: str, thread_id: str) -> str:
        self.calls.append((query, thread_id))
        if self.fail:
            raise RuntimeError("legacy unavailable")
        return self.response


def _context(query: str) -> RunContext:
    return RunContext(
        user_id=1,
        session_id=2,
        session_public_id="session-public",
        original_input=query,
        normalized_input=RecipeAgentHarness.normalize_input(query),
        profile=ProfileSnapshot(),
    )


def test_simple_route_bypasses_legacy_executor() -> None:
    executor = _Executor()
    harness = RecipeAgentHarness(BusinessRouter(), SimpleChatService(), executor)

    outcome = harness.run(_context("你好"))

    assert outcome.route_decision.route is RouteType.SIMPLE
    assert outcome.result.status is RunStatus.SUCCEEDED
    assert outcome.result.used_legacy_executor is False
    assert executor.calls == []
    assert outcome.context.started_at.utcoffset() == timezone.utc.utcoffset(None)


def test_non_simple_route_uses_one_complete_legacy_answer() -> None:
    executor = _Executor("宫保鸡丁的最终做法")
    harness = RecipeAgentHarness(BusinessRouter(), SimpleChatService(), executor)

    outcome = harness.run(_context("  宫保鸡丁   怎么做  "))

    assert outcome.route_decision.route is RouteType.RECIPE_KNOWLEDGE
    assert outcome.result.final_text == "宫保鸡丁的最终做法"
    assert outcome.result.used_legacy_executor is True
    assert executor.calls == [("宫保鸡丁 怎么做", "session-public")]


class _LegacyStreamAgent:
    def execute_stream(self, query: str, thread_id: str):
        del query, thread_id
        yield "【思考过程】\n"
        yield "这是内部推理，不应返回给用户。"
        yield "\n\n【思考过程】\n"
        yield "这是最终回答。"


def test_legacy_adapter_does_not_expose_reasoning_chunks() -> None:
    adapter = LegacyReactAgentAdapter(_LegacyStreamAgent())

    result = adapter.execute("问题", "thread")

    assert result == "这是最终回答。"
    assert "内部推理" not in result


def test_executor_failure_becomes_structured_outcome() -> None:
    harness = RecipeAgentHarness(
        BusinessRouter(),
        SimpleChatService(),
        _Executor(fail=True),
    )

    outcome = harness.run(_context("红烧肉怎么做"))

    assert outcome.result.status is RunStatus.FAILED
    assert outcome.result.error == "legacy unavailable"
    assert outcome.result.final_text == "抱歉，本次请求暂时无法完成，请稍后重试。"
    assert outcome.result.events[-1]["type"] == "execution_error"
