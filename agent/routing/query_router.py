import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


ROUTE_STRATEGIES = {
    "graph_only",
    "vector_only",
    "bm25_keyword",
    "dense_bm25",
    "advanced_hybrid",
    "weather_hybrid",
}


@dataclass
class QueryRoutePlan:
    query: str
    query_type: str = "unknown"
    strategy: str = "advanced_hybrid"
    complexity_score: float = 0.5
    relation_density_score: float = 0.5
    needs_multi_hop: bool = False
    needs_causal_analysis: bool = False
    needs_comparison: bool = False
    include_ingredients: list[str] = field(default_factory=list)
    exclude_ingredients: list[str] = field(default_factory=list)
    tool: str | None = None
    category: str | None = None
    requires_weather: bool = False
    confidence: float = 0.5
    reasoning: str = ""
    llm_used: bool = False
    llm_error: str | None = None


class RecipeQueryRouter:
    """
    Decide which retrieval strategy should answer a recipe query.

    Strategy meaning:
    - graph_only: use Neo4j structured lookup only.
    - vector_only: use Chroma semantic retrieval over recipe text.
    - bm25_keyword: use BM25 when exact keyword matching is important.
    - dense_bm25: combine dense retrieval and BM25 for ordinary recipe text questions.
    - advanced_hybrid: use Graph + Chroma + BM25 + RRF fusion.
    - weather_hybrid: get weather first, then use advanced_hybrid.
    """

    def route(self, query: str, use_llm: bool = True) -> dict[str, Any]:
        query = query.strip()
        fallback_plan = self._rule_based_route(query)

        if not use_llm:
            return asdict(fallback_plan)

        try:
            llm_plan = self._llm_route(query=query, fallback_plan=fallback_plan)
            llm_plan.llm_used = True
            return asdict(llm_plan)
        except Exception as exc:
            fallback_plan.llm_error = str(exc)
            fallback_plan.llm_used = False
            return asdict(fallback_plan)

    def _llm_route(
        self,
        query: str,
        fallback_plan: QueryRoutePlan,
    ) -> QueryRoutePlan:
        from model.factory import chat_model

        prompt = self._build_llm_prompt(query, fallback_plan)
        response = chat_model.invoke(prompt)
        content = getattr(response, "content", response)
        payload = self._parse_json_payload(str(content))

        return self._normalize_llm_payload(
            query=query,
            payload=payload,
            fallback_plan=fallback_plan,
        )

    def _build_llm_prompt(
        self,
        query: str,
        fallback_plan: QueryRoutePlan,
    ) -> str:
        return f"""
你是一个菜谱 RAG 系统的查询路由器。请判断用户问题应该使用哪种检索策略。

当前系统能力：
1. graph_only：Neo4j 结构化查询，适合食材、工具、分类、步骤列表、图谱事实。
2. vector_only：Chroma 全文语义检索，适合某道菜做法、说明、步骤细节、长文本上下文。
3. bm25_keyword：BM25 关键词召回，适合专有名词、精确食材名、菜名、工具名匹配。
4. dense_bm25：Chroma + BM25，适合普通正文问答或关键词与语义都重要的问题。
5. advanced_hybrid：Graph + Chroma + BM25 + RRF，适合带结构化筛选、推荐理由、步骤解释、复杂条件的问题。
6. weather_hybrid：需要天气或地理位置参与推荐时使用，先查天气，再进入混合检索。

请从以下维度判断：
- complexity_score：查询复杂度，0 到 1。简单事实接近 0，多个条件/约束/生成答案接近 1。
- relation_density_score：关系密集度，0 到 1。涉及食材-菜谱-工具-分类-步骤等图关系越多越高。
- needs_multi_hop：是否需要多跳推理。
- needs_causal_analysis：是否需要因果分析或解释为什么。
- needs_comparison：是否需要对比分析。

规则参考：
- 只问“某菜需要哪些食材/工具/步骤列表/分类下有哪些菜”：graph_only。
- 只问“某菜怎么做/正文说明/用量细节”：vector_only 或 dense_bm25。
- 明确要求包含/排除食材、工具、分类，并要求推荐、理由或做法：advanced_hybrid。
- 问“为什么适合/哪个更适合/对比 A 和 B/根据多个条件推荐”：advanced_hybrid。
- 涉及天气、今天适合吃什么、热/冷/下雨等外部天气条件：weather_hybrid。

规则路由初稿：
{json.dumps(asdict(fallback_plan), ensure_ascii=False, indent=2)}

用户问题：
{query}

请只输出 JSON，不要输出 Markdown 或解释性文字。JSON schema：
{{
  "query_type": "how_to|structured_fact|recommendation|include_exclude|tool|category|comparison|weather|unknown",
  "strategy": "graph_only|vector_only|bm25_keyword|dense_bm25|advanced_hybrid|weather_hybrid",
  "complexity_score": 0.0,
  "relation_density_score": 0.0,
  "needs_multi_hop": false,
  "needs_causal_analysis": false,
  "needs_comparison": false,
  "include_ingredients": [],
  "exclude_ingredients": [],
  "tool": null,
  "category": null,
  "requires_weather": false,
  "confidence": 0.0,
  "reasoning": "一句话说明路由理由"
}}
""".strip()

    def _rule_based_route(self, query: str) -> QueryRoutePlan:
        plan = QueryRoutePlan(query=query)

        if not query:
            plan.reasoning = "空查询，使用默认混合检索。"
            return plan

        include, exclude = self._extract_ingredients(query)
        plan.include_ingredients = include
        plan.exclude_ingredients = exclude

        if self._contains_any(query, ["天气", "下雨", "降温", "炎热", "很热", "寒冷", "今天适合"]):
            plan.query_type = "weather"
            plan.strategy = "weather_hybrid"
            plan.requires_weather = True
            plan.complexity_score = 0.8
            plan.relation_density_score = 0.6

        elif self._contains_any(query, ["对比", "区别", "哪个更", "更适合", "相比"]):
            plan.query_type = "comparison"
            plan.strategy = "advanced_hybrid"
            plan.needs_comparison = True
            plan.complexity_score = 0.8
            plan.relation_density_score = 0.7

        elif self._contains_any(query, ["为什么", "原因", "适合", "不适合", "能不能"]):
            plan.query_type = "recommendation"
            plan.strategy = "advanced_hybrid"
            plan.needs_causal_analysis = True
            plan.complexity_score = 0.75
            plan.relation_density_score = 0.65

        elif self._contains_any(query, ["推荐", "有没有", "找一道", "来一道", "适合"]):
            plan.query_type = "recommendation"
            plan.strategy = "advanced_hybrid"
            plan.complexity_score = 0.7
            plan.relation_density_score = 0.65

        elif self._contains_any(query, ["包含", "含有", "不含", "不要", "排除"]):
            plan.query_type = "include_exclude"
            plan.strategy = "advanced_hybrid"
            plan.complexity_score = 0.75
            plan.relation_density_score = 0.8

        elif self._contains_any(query, ["需要哪些食材", "需要什么食材", "哪些食材", "需要哪些工具", "需要什么工具"]):
            plan.query_type = "structured_fact"
            plan.strategy = "graph_only"
            plan.complexity_score = 0.25
            plan.relation_density_score = 0.75

        elif self._contains_any(query, ["怎么做", "做法", "步骤", "制作", "用量", "几克"]):
            plan.query_type = "how_to"
            plan.strategy = "dense_bm25"
            plan.complexity_score = 0.45
            plan.relation_density_score = 0.35

        if self._contains_any(query, ["工具", "搅拌机", "烤箱", "空气炸锅", "电饭锅", "蒸锅"]):
            plan.tool = self._extract_tool(query)
            if plan.query_type in {"unknown", "recommendation"}:
                plan.query_type = "tool"
                plan.strategy = "advanced_hybrid"
                plan.relation_density_score = max(plan.relation_density_score, 0.75)

        if self._contains_any(query, ["drink", "饮品", "饮料", "茶", "咖啡", "鸡尾酒"]):
            plan.category = "drink"
            plan.relation_density_score = max(plan.relation_density_score, 0.65)

        if include or exclude:
            plan.relation_density_score = max(plan.relation_density_score, 0.8)
            if plan.query_type == "unknown":
                plan.query_type = "include_exclude" if exclude else "ingredients"
                plan.strategy = "advanced_hybrid"

        if self._contains_any(query, ["同时", "并且", "还要", "但是", "不能", "排除", "多个"]):
            plan.needs_multi_hop = True
            plan.complexity_score = max(plan.complexity_score, 0.75)

        if plan.query_type == "unknown":
            plan.strategy = "dense_bm25"
            plan.complexity_score = 0.5
            plan.relation_density_score = 0.4

        plan.confidence = self._estimate_rule_confidence(plan)
        plan.reasoning = self._rule_reasoning(plan)
        return plan

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

    def _normalize_llm_payload(
        self,
        query: str,
        payload: dict[str, Any],
        fallback_plan: QueryRoutePlan,
    ) -> QueryRoutePlan:
        strategy = str(payload.get("strategy") or fallback_plan.strategy)
        if strategy not in ROUTE_STRATEGIES:
            strategy = fallback_plan.strategy

        plan = QueryRoutePlan(
            query=query,
            query_type=str(payload.get("query_type") or fallback_plan.query_type),
            strategy=strategy,
            complexity_score=self._clamp_float(
                payload.get("complexity_score"),
                fallback_plan.complexity_score,
            ),
            relation_density_score=self._clamp_float(
                payload.get("relation_density_score"),
                fallback_plan.relation_density_score,
            ),
            needs_multi_hop=self._to_bool(payload.get("needs_multi_hop")),
            needs_causal_analysis=self._to_bool(payload.get("needs_causal_analysis")),
            needs_comparison=self._to_bool(payload.get("needs_comparison")),
            include_ingredients=self._to_string_list(
                payload.get("include_ingredients"),
                fallback_plan.include_ingredients,
            ),
            exclude_ingredients=self._to_string_list(
                payload.get("exclude_ingredients"),
                fallback_plan.exclude_ingredients,
            ),
            tool=self._to_optional_string(payload.get("tool")) or fallback_plan.tool,
            category=self._to_optional_string(payload.get("category")) or fallback_plan.category,
            requires_weather=self._to_bool(payload.get("requires_weather")),
            confidence=self._clamp_float(payload.get("confidence"), fallback_plan.confidence),
            reasoning=str(payload.get("reasoning") or fallback_plan.reasoning),
        )

        if plan.requires_weather:
            plan.strategy = "weather_hybrid"

        return plan

    def _extract_tool(self, query: str) -> str | None:
        tools = [
            "搅拌机",
            "烤箱",
            "空气炸锅",
            "电饭锅",
            "电饭煲",
            "炒锅",
            "蒸锅",
            "微波炉",
        ]

        for tool in tools:
            if tool in query:
                return tool

        return None

    def _extract_ingredients(self, query: str) -> tuple[list[str], list[str]]:
        known_ingredients = [
            "耙耙柑",
            "茉莉绿茶",
            "冰块",
            "蔗糖糖浆",
            "豆腐",
            "牛肉",
            "鸡肉",
            "土豆",
            "鸡蛋",
            "番茄",
            "西红柿",
            "虾",
            "米饭",
            "面条",
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
        if plan.strategy == "weather_hybrid":
            return "查询涉及天气条件，需要先获取天气再进行混合检索。"
        if plan.strategy == "graph_only":
            return "查询主要是结构化图谱事实，适合 Neo4j 查询。"
        if plan.strategy == "advanced_hybrid":
            return "查询包含筛选、推荐、解释或多条件约束，适合三路混合检索。"
        if plan.strategy == "dense_bm25":
            return "查询偏正文做法或语义问答，适合语义检索结合关键词召回。"
        if plan.strategy == "bm25_keyword":
            return "查询偏精确关键词匹配，适合 BM25。"
        return "无法明确分类，使用默认混合检索。"

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

        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    def _to_optional_string(self, value: Any) -> str | None:
        if value is None:
            return None

        text = str(value).strip()
        if not text or text.lower() == "null":
            return None

        return text
