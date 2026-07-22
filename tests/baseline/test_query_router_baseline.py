from agent.routing.query_router import RecipeQueryRouter


def test_rule_router_selects_graph_for_structured_fact() -> None:
    result = RecipeQueryRouter().route(
        "西红柿鸡蛋汤需要哪些食材？",
        mode="rule",
    )

    assert result["retrieval_method"] == "graph_search"
    assert result["query_type"] == "structured_fact"
    assert result["llm_used"] is False


def test_rule_router_selects_vector_for_how_to_question() -> None:
    result = RecipeQueryRouter().route("白灼虾怎么做？", mode="rule")

    assert result["retrieval_method"] == "vector_search"
    assert result["query_type"] == "how_to"


def test_rule_router_selects_hybrid_for_comparison() -> None:
    result = RecipeQueryRouter().route(
        "对比西红柿鸡蛋汤和紫菜蛋花汤哪个更适合晚餐",
        mode="rule",
    )

    assert result["retrieval_method"] == "hybrid_search"
    assert result["needs_comparison"] is True
    assert result["inference_need"] == "comparison"
