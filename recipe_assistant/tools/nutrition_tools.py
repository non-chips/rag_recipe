"""Nutrition service adapters with existing role governance."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from recipe_assistant.schemas.nutrition import ConfirmedMealHistory
from recipe_assistant.services.meal_history import MealHistoryService
from recipe_assistant.services.nutrition import NutritionService
from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.governance import ToolPolicy, ToolRiskLevel
from recipe_assistant.tools.registry import LocalTool
from recipe_assistant.tools.schemas import (
    CalculateNutritionInput,
    CreateNutritionReportInput,
    MealHistoryInput,
    SendReportEmailInput,
)


NutritionHandler = Callable[[BaseModel, ToolContext], Any]


def create_nutrition_tools(
    *,
    meal_history: NutritionHandler | None = None,
    calculate: NutritionHandler | None = None,
    create_report: NutritionHandler | None = None,
    send_email: NutritionHandler | None = None,
) -> list[LocalTool]:
    """Create only adapters whose domain service handlers were injected."""

    tools: list[LocalTool] = []
    if meal_history is not None:
        tools.append(
            LocalTool(
                name="get_confirmed_meal_history",
                description="读取已确认的 CONSUME 记录及配置允许的 COOK 记录。",
                args_schema=MealHistoryInput,
                handler=meal_history,
                policy=ToolPolicy(
                    risk_level=ToolRiskLevel.USER_DATA_READ,
                    required_permissions=frozenset({"user_data:read"}),
                ),
            )
        )
    if calculate is not None:
        tools.append(
            LocalTool(
                name="calculate_recipe_nutrition",
                description="按确认餐次、份量、来源和覆盖率汇总营养数据。",
                args_schema=CalculateNutritionInput,
                handler=calculate,
                policy=ToolPolicy(risk_level=ToolRiskLevel.READ_ONLY),
            )
        )
    if create_report is not None:
        tools.append(
            LocalTool(
                name="create_nutrition_report",
                description="在用户确认后保存营养报告。",
                args_schema=CreateNutritionReportInput,
                handler=create_report,
                policy=ToolPolicy(
                    risk_level=ToolRiskLevel.USER_DATA_WRITE,
                    required_permissions=frozenset({"user_data:write"}),
                    requires_confirmation=True,
                ),
            )
        )
    if send_email is not None:
        tools.append(
            LocalTool(
                name="send_report_email",
                description="将报告发送到用户已经确认的收件目标。",
                args_schema=SendReportEmailInput,
                handler=send_email,
                policy=ToolPolicy(
                    risk_level=ToolRiskLevel.EXTERNAL_SIDE_EFFECT,
                    required_permissions=frozenset({"external:send"}),
                    requires_confirmation=True,
                    allow_automatic_retry=False,
                ),
            )
        )
    return tools


def create_nutrition_service_tools(
    meal_history_service: MealHistoryService,
    nutrition_service: NutritionService,
) -> list[LocalTool]:
    """Adapt history and calculation services without exposing user identity."""

    def meal_history(arguments: BaseModel, context: ToolContext) -> dict[str, Any]:
        parsed = MealHistoryInput.model_validate(arguments)
        return meal_history_service.load_confirmed(
            context.user_id,
            days=parsed.days,
        ).model_dump(mode="json")

    def calculate(arguments: BaseModel, context: ToolContext) -> dict[str, Any]:
        parsed = CalculateNutritionInput.model_validate(arguments)
        history = meal_history_service.load_confirmed(context.user_id, days=7)
        requested = set(parsed.recipe_ids)
        filtered = ConfirmedMealHistory(
            user_id=history.user_id,
            records=tuple(
                record for record in history.records if record.recipe_id in requested
            ),
            included_event_types=history.included_event_types,
            start_at=history.start_at,
            end_at=history.end_at,
        )
        return nutrition_service.summarize(filtered).model_dump(mode="json")

    return create_nutrition_tools(meal_history=meal_history, calculate=calculate)
