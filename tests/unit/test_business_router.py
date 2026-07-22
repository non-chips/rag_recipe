from __future__ import annotations

import json
from pathlib import Path

from recipe_assistant.agents.router import BusinessRouter
from recipe_assistant.schemas.agent.route import (
    RouteDecision,
    RouteType,
    SimpleChatCategory,
)
from recipe_assistant.services.simple_chat import SimpleChatService


DATASET_PATH = Path(__file__).parents[1] / "datasets" / "business_router_cases.json"


def test_rule_router_matches_business_dataset() -> None:
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    assert len(cases) >= 30
    router = BusinessRouter()

    for case in cases:
        decision = router.route(case["query"])
        assert decision.route.value == case["expected_route"], case["query"]
        assert decision.requires_weather is case.get("requires_weather", False)
        assert decision.requires_meal_history is case.get(
            "requires_meal_history", False
        )
        assert decision.requires_multiple_experts is case.get(
            "requires_multiple_experts", False
        )
        assert decision.reason
        assert 0.0 <= decision.confidence <= 1.0


class _Classifier:
    def __init__(self, output) -> None:
        self.output = output
        self.calls: list[tuple[str, RouteDecision]] = []

    def classify(self, query: str, fallback: RouteDecision):
        self.calls.append((query, fallback))
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def test_high_confidence_rule_does_not_call_llm_classifier() -> None:
    classifier = _Classifier(
        {
            "route": "NUTRITION_PLANNING",
            "confidence": 0.9,
            "reason": "should not be used",
        }
    )
    router = BusinessRouter(classifier=classifier)

    decision = router.route("宫保鸡丁怎么做")

    assert decision.route is RouteType.RECIPE_KNOWLEDGE
    assert classifier.calls == []


def test_low_confidence_rule_uses_structured_llm_fallback() -> None:
    classifier = _Classifier(
        {
            "route": "RECIPE_RECOMMENDATION",
            "confidence": 0.84,
            "reason": "用户表达了开放式选择意图。",
            "requires_weather": False,
            "requires_meal_history": False,
            "requires_multiple_experts": False,
        }
    )
    router = BusinessRouter(classifier=classifier)

    decision = router.route("今晚整点清淡的")

    assert decision.route is RouteType.RECIPE_RECOMMENDATION
    assert decision.confidence == 0.84
    assert len(classifier.calls) == 1


def test_invalid_retrieval_strategy_from_llm_cannot_become_business_route() -> None:
    classifier = _Classifier(
        {
            "route": "vector_search",
            "confidence": 1.0,
            "reason": "invalid technical route",
        }
    )
    router = BusinessRouter(classifier=classifier)

    decision = router.route("帮我看看这个")

    assert decision.route is RouteType.RECIPE_KNOWLEDGE
    assert decision.confidence == 0.45


def test_classifier_failure_returns_rule_fallback() -> None:
    router = BusinessRouter(classifier=_Classifier(RuntimeError("model unavailable")))

    decision = router.route("帮我看看这个")

    assert decision.route is RouteType.RECIPE_KNOWLEDGE
    assert decision.reason == "规则信号不足，暂以菜谱知识路由兜底。"


def test_llm_complex_route_enforces_multiple_experts_flag() -> None:
    classifier = _Classifier(
        """```json
        {"route":"COMPLEX","confidence":0.9,"reason":"需要组合分析"}
        ```"""
    )
    decision = BusinessRouter(classifier=classifier).route("帮我综合判断一下")

    assert decision.route is RouteType.COMPLEX
    assert decision.requires_multiple_experts is True


def test_simple_chat_service_returns_structured_fast_path_responses() -> None:
    service = SimpleChatService()

    greeting = service.respond("你好")
    capability = service.respond("你能做什么？")
    thanks = service.respond("谢谢你")

    assert greeting.category is SimpleChatCategory.GREETING
    assert capability.category is SimpleChatCategory.CAPABILITY
    assert "菜谱" in capability.message
    assert thanks.category is SimpleChatCategory.THANKS
