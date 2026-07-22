import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


RETRIEVAL_METHODS = {
    "graph_search",
    "vector_search",
    "hybrid_search",
}


@dataclass
class QueryRoutePlan:
    query: str
    query_type: str = "unknown"
    retrieval_method: str = "hybrid_search"
    complexity_score: float = 0.5
    relation_density_score: float = 0.5
    needs_causal_analysis: bool = False
    needs_comparison: bool = False
    inference_need: str = "none"
    include_ingredients: list[str] = field(default_factory=list)
    exclude_ingredients: list[str] = field(default_factory=list)
    tool: str | None = None
    category: str | None = None
    requires_weather: bool = False
    confidence: float = 0.5
    reasoning: str = ""
    llm_used: bool = False
    llm_error: str | None = None

    @property
    def strategy(self) -> str:
        return self.retrieval_method


class RecipeQueryRouter:
    """
    Mandatory query analysis node for choosing one of three retrieval methods:

    - graph_search: Neo4j structured retrieval.
    - vector_search: Chroma-based ordinary RAG retrieval.
    - hybrid_search: Graph + Chroma + BM25 + RRF retrieval.
    """

    def route(self, query: str, mode: str = "auto") -> dict[str, Any]:
        query = query.strip()
        fallback_plan = self._rule_based_route(query)

        if mode == "rule":
            return self._to_dict(fallback_plan)

        try:
            llm_plan = self._llm_route(query=query, fallback_plan=fallback_plan)
            llm_plan.llm_used = True
            return self._to_dict(llm_plan)
        except Exception as exc:
            fallback_plan.llm_error = str(exc)
            fallback_plan.llm_used = False
            return self._to_dict(fallback_plan)

    def _llm_route(
        self,
        query: str,
        fallback_plan: QueryRoutePlan,
    ) -> QueryRoutePlan:
        from model.factory import chat_model

        response = chat_model.invoke(self._build_llm_prompt(query, fallback_plan))
        content = getattr(response, "content", response)
        payload = self._parse_json_payload(str(content))
        return self._normalize_llm_payload(query, payload, fallback_plan)

    def _build_llm_prompt(
        self,
        query: str,
        fallback_plan: QueryRoutePlan,
    ) -> str:
        return f"""
你是一个菜谱 RAG 系统的查询路由器。请先分析用户问题，再从三种检索方法中选择一种。

可选检索方法：
1. graph_search：Neo4j 图谱结构化检索。适合查询确定的结构化事实，例如某道菜的食材、工具、步骤列表，或按食材/工具/分类筛选菜谱。
2. vector_search：普通 RAG 向量检索。适合查询某道菜的具体做法、正文说明、用量细节、制作步骤等文本上下文。
3. hybrid_search：混合检索。适合推荐、复杂筛选、多条件约束、对比分析、因果解释、多跳推理，或同时需要图谱结构和文本上下文的问题。

请从三个维度判断：
- complexity_score：查询复杂度，0 到 1。简单事实接近 0，多条件、推荐、对比、解释接近 1。
- relation_density_score：关系密集度，0 到 1。涉及菜谱-食材-工具-分类-步骤等图关系越多越高。
- inference_need：推理需求，只能取 none、multi_hop、causal、comparison、mixed。

规则兜底参考：
{json.dumps(self._to_dict(fallback_plan), ensure_ascii=False, indent=2)}

用户问题：
{query}

请只输出 JSON，不要输出 Markdown。JSON schema：
{{
  "query_type": "how_to|structured_fact|recommendation|include_exclude|tool|category|comparison|weather|unknown",
  "retrieval_method": "graph_search|vector_search|hybrid_search",
  "complexity_score": 0.0,
  "relation_density_score": 0.0,
  "needs_causal_analysis": false,
  "needs_comparison": false,
  "inference_need": "none|multi_hop|causal|comparison|mixed",
  "include_ingredients": [],
  "exclude_ingredients": [],
  "tool": null,
  "category": null,
  "requires_weather": false,
  "confidence": 0.0,
  "reasoning": "一句话说明为什么选择该检索方法"
}}
""".strip()

    def _rule_based_route(self, query: str) -> QueryRoutePlan:
        plan = QueryRoutePlan(query=query)
        include, exclude = self._extract_ingredients(query)
        plan.include_ingredients = include
        plan.exclude_ingredients = exclude

        if not query:
            plan.reasoning = "空查询，默认使用混合检索。"
            return plan

        if self._contains_any(query, ["天气", "下雨", "降温", "炎热", "很热", "寒冷", "今天适合"]):
            plan.query_type = "weather"
            plan.retrieval_method = "hybrid_search"
            plan.requires_weather = True
            plan.complexity_score = 0.8
            plan.relation_density_score = 0.6
            plan.inference_need = "mixed"

        elif self._contains_any(query, ["对比", "区别", "哪个更", "更适合", "相比"]):
            plan.query_type = "comparison"
            plan.retrieval_method = "hybrid_search"
            plan.complexity_score = 0.85
            plan.relation_density_score = 0.75
            plan.needs_comparison = True
            plan.inference_need = "comparison"

        elif self._contains_any(query, ["为什么", "原因", "适合", "不适合", "能不能"]):
            plan.query_type = "recommendation"
            plan.retrieval_method = "hybrid_search"
            plan.complexity_score = 0.75
            plan.relation_density_score = 0.65
            plan.needs_causal_analysis = True
            plan.inference_need = "causal"

        elif self._contains_any(query, ["推荐", "有没有", "找一道", "来一道"]):
            plan.query_type = "recommendation"
            plan.retrieval_method = "hybrid_search"
            plan.complexity_score = 0.7
            plan.relation_density_score = 0.65
            plan.inference_need = "multi_hop"

        elif self._contains_any(query, ["包含", "含有", "不含", "不要", "排除"]):
            plan.query_type = "include_exclude"
            plan.retrieval_method = "hybrid_search"
            plan.complexity_score = 0.75
            plan.relation_density_score = 0.8
            plan.inference_need = "multi_hop"

        elif self._contains_any(query, ["需要哪些食材", "需要什么食材", "哪些食材", "需要哪些工具", "需要什么工具", "有哪些步骤"]):
            plan.query_type = "structured_fact"
            plan.retrieval_method = "graph_search"
            plan.complexity_score = 0.25
            plan.relation_density_score = 0.8
            plan.inference_need = "none"

        elif self._contains_any(query, ["怎么做", "做法", "制作", "用量", "几克"]):
            plan.query_type = "how_to"
            plan.retrieval_method = "vector_search"
            plan.complexity_score = 0.45
            plan.relation_density_score = 0.35
            plan.inference_need = "none"

        if self._contains_any(query, ["工具", "搅拌机", "烤箱", "空气炸锅", "电饭锅", "电饭煲", "蒸锅", "微波炉"]):
            plan.tool = self._extract_tool(query)
            plan.relation_density_score = max(plan.relation_density_score, 0.75)
            if plan.query_type == "unknown":
                plan.query_type = "tool"
                plan.retrieval_method = "graph_search"

        if self._contains_any(query, ["drink", "饮品", "饮料", "茶", "咖啡", "鸡尾酒"]):
            plan.category = "drink"
            plan.relation_density_score = max(plan.relation_density_score, 0.65)

        if include or exclude:
            plan.relation_density_score = max(plan.relation_density_score, 0.8)
            if plan.query_type == "unknown":
                plan.query_type = "ingredients"
                plan.retrieval_method = "hybrid_search"

        if self._contains_any(query, ["同时", "并且", "还要", "但是", "不能", "多个"]):
            plan.complexity_score = max(plan.complexity_score, 0.75)
            plan.inference_need = "mixed" if plan.needs_causal_analysis or plan.needs_comparison else "multi_hop"
            plan.retrieval_method = "hybrid_search"

        if plan.query_type == "unknown":
            plan.retrieval_method = "vector_search"
            plan.complexity_score = 0.5
            plan.relation_density_score = 0.4

        plan.confidence = self._estimate_rule_confidence(plan)
        plan.reasoning = self._rule_reasoning(plan)
        return plan

    def _normalize_llm_payload(
        self,
        query: str,
        payload: dict[str, Any],
        fallback_plan: QueryRoutePlan,
    ) -> QueryRoutePlan:
        method = str(payload.get("retrieval_method") or payload.get("strategy") or fallback_plan.retrieval_method)
        if method not in RETRIEVAL_METHODS:
            method = fallback_plan.retrieval_method

        plan = QueryRoutePlan(
            query=query,
            query_type=str(payload.get("query_type") or fallback_plan.query_type),
            retrieval_method=method,
            complexity_score=self._clamp_float(payload.get("complexity_score"), fallback_plan.complexity_score),
            relation_density_score=self._clamp_float(payload.get("relation_density_score"), fallback_plan.relation_density_score),
            needs_causal_analysis=self._to_bool(payload.get("needs_causal_analysis")),
            needs_comparison=self._to_bool(payload.get("needs_comparison")),
            inference_need=str(payload.get("inference_need") or fallback_plan.inference_need),
            include_ingredients=self._to_string_list(payload.get("include_ingredients"), fallback_plan.include_ingredients),
            exclude_ingredients=self._to_string_list(payload.get("exclude_ingredients"), fallback_plan.exclude_ingredients),
            tool=self._to_optional_string(payload.get("tool")) or fallback_plan.tool,
            category=self._to_optional_string(payload.get("category")) or fallback_plan.category,
            requires_weather=self._to_bool(payload.get("requires_weather")),
            confidence=self._clamp_float(payload.get("confidence"), fallback_plan.confidence),
            reasoning=str(payload.get("reasoning") or fallback_plan.reasoning),
        )

        if plan.inference_need not in {"none", "multi_hop", "causal", "comparison", "mixed"}:
            plan.inference_need = fallback_plan.inference_need

        if plan.requires_weather:
            plan.retrieval_method = "hybrid_search"

        return plan

    def _to_dict(self, plan: QueryRoutePlan) -> dict[str, Any]:
        payload = asdict(plan)
        payload["strategy"] = plan.retrieval_method
        return payload

    def _parse_json_payload(self, content: str) -> dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content, flags=re.IGNORECASE).strip()
            content = re.sub(r"```$", "", content).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def _extract_tool(self, query: str) -> str | None:
        for tool in ["搅拌机", "烤箱", "空气炸锅", "电饭锅", "电饭煲", "炒锅", "蒸锅", "微波炉"]:
            if tool in query:
                return tool
        return None

    def _extract_ingredients(self, query: str) -> tuple[list[str], list[str]]:
        known_ingredients = [
            "耙耙柑", "茉莉绿茶", "冰块", "蔗糖糖浆", "豆腐", "牛肉", "鸡肉",
            "土豆", "鸡蛋", "番茄", "西红柿", "虾", "米饭", "面条",
        ]
        include = []
        exclude = []
        for ingredient in known_ingredients:
            if ingredient not in query:
                continue
            before = query[max(0, query.find(ingredient) - 5):query.find(ingredient)]
            if self._contains_any(before, ["不含", "不要", "排除", "不能", "无"]):
                exclude.append(ingredient)
            else:
                include.append(ingredient)
        return include, exclude

    def _contains_any(self, text: str, words: list[str]) -> bool:
        return any(word in text for word in words)

    def _estimate_rule_confidence(self, plan: QueryRoutePlan) -> float:
        confidence = 0.45
        if plan.query_type != "unknown":
            confidence += 0.2
        if plan.include_ingredients or plan.exclude_ingredients:
            confidence += 0.15
        if plan.tool or plan.category:
            confidence += 0.1
        if plan.requires_weather:
            confidence += 0.1
        return min(confidence, 0.9)

    def _rule_reasoning(self, plan: QueryRoutePlan) -> str:
        if plan.retrieval_method == "graph_search":
            return "问题主要涉及结构化事实，使用图谱检索更合适。"
        if plan.retrieval_method == "vector_search":
            return "问题主要涉及菜谱正文和做法细节，使用普通 RAG 检索更合适。"
        return "问题包含筛选、推荐、解释、对比或多条件约束，使用混合检索更合适。"

    def _clamp_float(self, value: Any, default: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        return max(0.0, min(1.0, number))

    def _to_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "y"}
        return bool(value)

    def _to_string_list(self, value: Any, default: list[str]) -> list[str]:
        if not isinstance(value, list):
            return default
        return [str(item).strip() for item in value if str(item).strip()]

    def _to_optional_string(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() == "null":
            return None
        return text
