"""Recommendation and weather service adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from recipe_assistant.services.recommendation import RecommendationService
from recipe_assistant.services.weather import WeatherService
from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.governance import ToolPolicy, ToolRiskLevel
from recipe_assistant.tools.registry import LocalTool
from recipe_assistant.tools.schemas import (
    CurrentWeatherInput,
    MealHistoryInput,
    RecommendRecipesInput,
    SaveMealRecordInput,
)


RecommendationHandler = Callable[[BaseModel, ToolContext], Any]


def create_recommendation_tools(
    *,
    recommend: RecommendationHandler | None = None,
    weather: RecommendationHandler | None = None,
    meal_history: RecommendationHandler | None = None,
    save_meal: RecommendationHandler | None = None,
) -> list[LocalTool]:
    """Create only adapters whose domain service handlers were injected."""

    tools: list[LocalTool] = []
    if recommend is not None:
        tools.append(
            LocalTool(
                name="recommend_recipes",
                description="从检索结果召回菜谱候选，不生成知识库外菜谱。",
                args_schema=RecommendRecipesInput,
                handler=recommend,
                policy=ToolPolicy(
                    risk_level=ToolRiskLevel.USER_DATA_READ,
                    required_permissions=frozenset({"user_data:read"}),
                ),
            )
        )
    if weather is not None:
        tools.append(
            LocalTool(
                name="get_current_weather",
                description="获取指定城市的当前天气；失败时返回明确降级结果。",
                args_schema=CurrentWeatherInput,
                handler=weather,
                policy=ToolPolicy(risk_level=ToolRiskLevel.READ_ONLY),
            )
        )
    if meal_history is not None:
        tools.append(
            LocalTool(
                name="get_confirmed_meal_history",
                description="读取用户已经确认的饮食记录。",
                args_schema=MealHistoryInput,
                handler=meal_history,
                policy=ToolPolicy(
                    risk_level=ToolRiskLevel.USER_DATA_READ,
                    required_permissions=frozenset({"user_data:read"}),
                ),
            )
        )
    if save_meal is not None:
        tools.append(
            LocalTool(
                name="save_meal_record",
                description="在用户明确确认后保存饮食记录。",
                args_schema=SaveMealRecordInput,
                handler=save_meal,
                policy=ToolPolicy(
                    risk_level=ToolRiskLevel.USER_DATA_WRITE,
                    required_permissions=frozenset({"user_data:write"}),
                    requires_confirmation=True,
                ),
            )
        )
    return tools


def create_recommendation_service_tools(
    recommendation_service: RecommendationService,
    weather_service: WeatherService | None = None,
) -> list[LocalTool]:
    """Adapt typed services to the existing role-scoped tool contracts."""

    def recommend(arguments: BaseModel, context: ToolContext) -> dict[str, Any]:
        del context
        parsed = RecommendRecipesInput.model_validate(arguments)
        return recommendation_service.recall(
            parsed.query,
            top_k=parsed.top_k,
        ).model_dump(mode="json")

    def weather(arguments: BaseModel, context: ToolContext) -> dict[str, Any]:
        del context
        parsed = CurrentWeatherInput.model_validate(arguments)
        assert weather_service is not None
        return weather_service.get_current(parsed.city).model_dump(mode="json")

    return create_recommendation_tools(
        recommend=recommend,
        weather=weather if weather_service is not None else None,
    )
