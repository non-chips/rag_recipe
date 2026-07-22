"""Nutrition tool adapters configured with future service handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.governance import ToolPolicy, ToolRiskLevel
from recipe_assistant.tools.registry import LocalTool
from recipe_assistant.tools.schemas import (
    CalculateNutritionInput,
    CreateNutritionReportInput,
    SendReportEmailInput,
)


NutritionHandler = Callable[[BaseModel, ToolContext], Any]


def create_nutrition_tools(
    *,
    calculate: NutritionHandler | None = None,
    create_report: NutritionHandler | None = None,
    send_email: NutritionHandler | None = None,
) -> list[LocalTool]:
    """Create only adapters whose domain service handlers were injected."""

    tools: list[LocalTool] = []
    if calculate is not None:
        tools.append(
            LocalTool(
                name="calculate_recipe_nutrition",
                description="计算指定菜谱集合的营养数据。",
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
                description="将已生成的营养报告发送到已确认的收件目标。",
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
