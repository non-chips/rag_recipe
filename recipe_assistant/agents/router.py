"""Rule-first business router with an injectable structured LLM fallback."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Protocol

from recipe_assistant.schemas.agent.route import RouteDecision, RouteType


class StructuredRouteClassifier(Protocol):
    """Adapter implemented by a structured-output LLM boundary."""

    def classify(
        self,
        query: str,
        rule_fallback: RouteDecision,
    ) -> RouteDecision | Mapping[str, Any] | str:
        """Return data validating against RouteDecision."""


class BusinessRouter:
    """Choose a business domain without selecting retrieval infrastructure."""

    _SIMPLE_EXACT = {
        "你好",
        "您好",
        "嗨",
        "hi",
        "hello",
        "谢谢",
        "感谢",
        "再见",
        "拜拜",
        "早上好",
        "晚上好",
        "你能做什么",
        "你是谁",
    }
    _WEATHER_TERMS = ("天气", "下雨", "降温", "炎热", "寒冷", "气温")
    _MEAL_HISTORY_TERMS = (
        "上周的饮食",
        "本周的饮食",
        "本月饮食",
        "最近饮食",
        "饮食记录",
        "饮食历史",
        "营养情况",
        "吃过什么",
        "我上周吃",
    )
    _NUTRITION_TERMS = (
        "营养",
        "热量",
        "卡路里",
        "蛋白质",
        "脂肪",
        "碳水",
        "膳食纤维",
        "营养报告",
        "饮食总结",
    )
    _RECOMMENDATION_TERMS = (
        "推荐",
        "能做什么",
        "可以做什么",
        "吃什么",
        "来一道",
        "找一道",
        "适合吃",
        "适合晚饭",
        "适合午饭",
        "我有",
        "不要辣",
        "低脂菜",
    )
    _KNOWLEDGE_TERMS = (
        "怎么做",
        "做法",
        "需要什么食材",
        "需要哪些食材",
        "有哪些食材",
        "需要什么工具",
        "需要哪些工具",
        "有哪些步骤",
        "制作步骤",
        "用量",
        "几克",
        "炖多久",
        "煮多久",
        "烤多久",
    )
    _COMPARISON_TERMS = ("比较", "对比", "哪个更", "有什么区别", "相比")

    def __init__(
        self,
        classifier: StructuredRouteClassifier | None = None,
        *,
        rule_confidence_threshold: float = 0.8,
    ) -> None:
        if not 0.0 <= rule_confidence_threshold <= 1.0:
            raise ValueError("rule_confidence_threshold must be between 0 and 1")
        self.classifier = classifier
        self.rule_confidence_threshold = rule_confidence_threshold

    def route(self, query: str) -> RouteDecision:
        """Use L1 rules first and invoke L2 only for a low-confidence decision."""

        normalized_query = (query or "").strip()
        rule_decision = self._rule_route(normalized_query)
        if (
            rule_decision.confidence >= self.rule_confidence_threshold
            or self.classifier is None
        ):
            return rule_decision

        try:
            raw_decision = self.classifier.classify(normalized_query, rule_decision)
            decision = self._validate_classifier_output(raw_decision)
        except Exception:
            return rule_decision

        return decision.model_copy(
            update={
                "requires_weather": (
                    decision.requires_weather or rule_decision.requires_weather
                ),
                "requires_meal_history": (
                    decision.requires_meal_history
                    or rule_decision.requires_meal_history
                ),
                "requires_multiple_experts": (
                    decision.route is RouteType.COMPLEX
                    or decision.requires_multiple_experts
                ),
            }
        )

    def _rule_route(self, query: str) -> RouteDecision:
        requires_weather = self._contains_any(query, self._WEATHER_TERMS)
        requires_meal_history = self._contains_any(query, self._MEAL_HISTORY_TERMS)
        has_nutrition = self._contains_any(query, self._NUTRITION_TERMS)
        has_recommendation = self._contains_any(query, self._RECOMMENDATION_TERMS)
        has_knowledge = self._contains_any(query, self._KNOWLEDGE_TERMS)
        has_comparison = self._contains_any(query, self._COMPARISON_TERMS)

        if not query:
            return self._decision(RouteType.SIMPLE, 0.99, "空输入使用简单聊天快速路径。")

        simple_key = re.sub(r"[\s，,。.!！?？~～]", "", query).lower()
        if simple_key in self._SIMPLE_EXACT:
            return self._decision(RouteType.SIMPLE, 0.98, "命中问候或能力说明规则。")

        if (
            (has_nutrition and (has_recommendation or has_knowledge or has_comparison))
            or (requires_meal_history and has_recommendation)
            or (has_comparison and has_nutrition)
        ):
            return self._decision(
                RouteType.COMPLEX,
                0.94,
                "问题同时涉及多个业务领域，需要多专家协作。",
                requires_weather=requires_weather,
                requires_meal_history=requires_meal_history,
                requires_multiple_experts=True,
            )

        if has_comparison:
            return self._decision(
                RouteType.COMPLEX,
                0.88,
                "跨菜谱比较需要组合多个知识维度。",
                requires_weather=requires_weather,
                requires_meal_history=requires_meal_history,
                requires_multiple_experts=True,
            )

        if has_nutrition or requires_meal_history:
            return self._decision(
                RouteType.NUTRITION_PLANNING,
                0.92,
                "命中营养分析、报告或饮食历史规则。",
                requires_meal_history=requires_meal_history,
            )

        if has_recommendation or requires_weather:
            return self._decision(
                RouteType.RECIPE_RECOMMENDATION,
                0.91,
                "命中菜谱推荐或天气辅助推荐规则。",
                requires_weather=requires_weather,
                requires_meal_history=requires_meal_history,
            )

        if has_knowledge:
            return self._decision(
                RouteType.RECIPE_KNOWLEDGE,
                0.93,
                "命中菜谱做法或结构化知识规则。",
            )

        return self._decision(
            RouteType.RECIPE_KNOWLEDGE,
            0.45,
            "规则信号不足，暂以菜谱知识路由兜底。",
            requires_weather=requires_weather,
            requires_meal_history=requires_meal_history,
        )

    @staticmethod
    def _decision(
        route: RouteType,
        confidence: float,
        reason: str,
        *,
        requires_weather: bool = False,
        requires_meal_history: bool = False,
        requires_multiple_experts: bool = False,
    ) -> RouteDecision:
        return RouteDecision(
            route=route,
            confidence=confidence,
            reason=reason,
            requires_weather=requires_weather,
            requires_meal_history=requires_meal_history,
            requires_multiple_experts=requires_multiple_experts,
        )

    @staticmethod
    def _contains_any(query: str, terms: tuple[str, ...]) -> bool:
        lowered = query.lower()
        return any(term.lower() in lowered for term in terms)

    @staticmethod
    def _validate_classifier_output(raw: Any) -> RouteDecision:
        if isinstance(raw, RouteDecision):
            return raw
        if isinstance(raw, Mapping):
            return RouteDecision.model_validate(dict(raw))
        content = getattr(raw, "content", raw)
        if not isinstance(content, str):
            raise TypeError("structured route classifier returned unsupported data")
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()
        return RouteDecision.model_validate(json.loads(text))
