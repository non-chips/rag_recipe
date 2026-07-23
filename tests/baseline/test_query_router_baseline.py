from recipe_assistant.agents.router import BusinessRouter
from recipe_assistant.schemas.agent.route import RouteType


def test_business_router_selects_knowledge_for_how_to_question() -> None:
    result = BusinessRouter().route("白灼虾怎么做？")
    assert result.route is RouteType.RECIPE_KNOWLEDGE


def test_business_router_selects_recommendation_for_dinner_request() -> None:
    result = BusinessRouter().route("推荐一道适合晚饭的菜")
    assert result.route is RouteType.RECIPE_RECOMMENDATION


def test_business_router_selects_complex_for_multi_domain_request() -> None:
    result = BusinessRouter().route("根据上周营养情况推荐今晚菜谱")
    assert result.route is RouteType.COMPLEX
