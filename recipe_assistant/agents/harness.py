"""Single-turn harness using SIMPLE fast path or a legacy executor adapter."""

from __future__ import annotations

import re
from time import perf_counter
from typing import Any, Protocol

from recipe_assistant.agents.result import (
    AgentRunResult,
    HarnessOutcome,
    RunContext,
    RunStatus,
)
from recipe_assistant.agents.router import BusinessRouter
from recipe_assistant.schemas.agent.route import RouteType
from recipe_assistant.services.simple_chat import SimpleChatService


class AgentExecutor(Protocol):
    def execute(self, query: str, thread_id: str) -> str:
        """Return one complete user-facing answer."""


class LegacyReactAgentAdapter:
    """Aggregate an existing ReactAgent stream and remove internal reasoning."""

    _THOUGHT_MARKER = "【思考过程】"

    def __init__(self, legacy_agent: Any) -> None:
        self.legacy_agent = legacy_agent

    def execute(self, query: str, thread_id: str) -> str:
        chunks = self.legacy_agent.execute_stream(query=query, thread_id=thread_id)
        combined = "".join(str(chunk) for chunk in chunks if chunk is not None)
        return self._final_answer_only(combined)

    @classmethod
    def _final_answer_only(cls, combined: str) -> str:
        text = combined.strip()
        if cls._THOUGHT_MARKER in text:
            text = text.rsplit(cls._THOUGHT_MARKER, maxsplit=1)[-1].strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if not text:
            raise RuntimeError("legacy executor returned no final answer")
        return text


class RecipeAgentHarness:
    """Route and execute exactly one normalized user request."""

    def __init__(
        self,
        router: BusinessRouter,
        simple_chat: SimpleChatService,
        executor: AgentExecutor,
    ) -> None:
        self.router = router
        self.simple_chat = simple_chat
        self.executor = executor

    @staticmethod
    def normalize_input(text: str) -> str:
        return " ".join((text or "").strip().split())

    def run(self, context: RunContext) -> HarnessOutcome:
        started_at = perf_counter()
        route_decision = self.router.route(context.normalized_input)
        events: list[dict[str, Any]] = [
            {
                "type": "route",
                "route": route_decision.route.value,
                "confidence": route_decision.confidence,
                "reason": route_decision.reason,
            }
        ]

        try:
            if route_decision.route is RouteType.SIMPLE:
                response = self.simple_chat.respond(context.normalized_input)
                final_text = response.message
                used_legacy_executor = False
                events.append({"type": "simple_chat", "category": response.category.value})
            else:
                final_text = self.executor.execute(
                    context.normalized_input,
                    context.session_public_id,
                )
                used_legacy_executor = True
                events.append({"type": "legacy_executor", "status": "succeeded"})

            result = AgentRunResult(
                status=RunStatus.SUCCEEDED,
                final_text=final_text,
                events=events,
                used_legacy_executor=used_legacy_executor,
            )
        except Exception as exc:
            events.append(
                {
                    "type": "execution_error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            result = AgentRunResult(
                status=RunStatus.FAILED,
                final_text="抱歉，本次请求暂时无法完成，请稍后重试。",
                events=events,
                used_legacy_executor=route_decision.route is not RouteType.SIMPLE,
                error=str(exc),
            )

        return HarnessOutcome(
            context=context,
            route_decision=route_decision,
            result=result,
            latency_ms=(perf_counter() - started_at) * 1000,
        )
