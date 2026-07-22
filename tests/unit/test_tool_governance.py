from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError
import pytest

from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.governance import (
    ToolAccessDenied,
    ToolPolicy,
    ToolRiskLevel,
    UnregisteredToolError,
)
from recipe_assistant.tools.registry import LocalTool, ToolRegistry
from recipe_assistant.tools.schemas import ToolArguments, ToolRole, ToolTraceStatus
from recipe_assistant.tools.tracing import InMemoryToolTraceSink, ToolTraceMiddleware


class _ValueInput(ToolArguments):
    value: str = Field(min_length=1)


def _context(*permissions: str) -> ToolContext:
    return ToolContext(
        run_id="run-governance",
        user_id=7,
        session_id="session-governance",
        route="recommendation",
        permissions=frozenset(permissions),
    )


def _registry(tool: LocalTool | None = None):
    sink = InMemoryToolTraceSink()
    registry = ToolRegistry(
        [tool] if tool else [],
        tracing=ToolTraceMiddleware(sink),
    )
    return registry, sink


def _tool(name: str, policy: ToolPolicy, *, fail: bool = False) -> LocalTool:
    def handler(arguments: BaseModel, _context: ToolContext) -> str:
        if fail:
            raise RuntimeError("service failed")
        return str(arguments.model_dump()["value"])

    return LocalTool(
        name=name,
        description=name,
        args_schema=_ValueInput,
        handler=handler,
        policy=policy,
    )


def test_unregistered_tool_is_denied_and_traced() -> None:
    registry, sink = _registry()

    with pytest.raises(UnregisteredToolError):
        registry.invoke(
            role=ToolRole.KNOWLEDGE_EXPERT,
            tool_name="unknown_tool",
            arguments={"value": "x"},
            context=_context(),
        )

    assert sink.traces[0].status is ToolTraceStatus.DENIED
    assert sink.traces[0].tool_name == "unknown_tool"


def test_role_and_permission_are_both_required() -> None:
    tool = _tool(
        "get_confirmed_meal_history",
        ToolPolicy(
            ToolRiskLevel.USER_DATA_READ,
            required_permissions=frozenset({"user_data:read"}),
        ),
    )
    registry, sink = _registry(tool)

    with pytest.raises(ToolAccessDenied, match="not authorized"):
        registry.invoke(
            role=ToolRole.KNOWLEDGE_EXPERT,
            tool_name=tool.name,
            arguments={"value": "7 days"},
            context=_context("user_data:read"),
        )
    with pytest.raises(ToolAccessDenied, match="missing tool permissions"):
        registry.invoke(
            role=ToolRole.RECOMMENDATION_EXPERT,
            tool_name=tool.name,
            arguments={"value": "7 days"},
            context=_context(),
        )

    assert [trace.status for trace in sink.traces] == [
        ToolTraceStatus.DENIED,
        ToolTraceStatus.DENIED,
    ]


def test_user_data_write_requires_system_confirmation() -> None:
    tool = _tool(
        "save_meal_record",
        ToolPolicy(
            ToolRiskLevel.USER_DATA_WRITE,
            required_permissions=frozenset({"user_data:write"}),
            requires_confirmation=True,
        ),
    )
    registry, sink = _registry(tool)

    with pytest.raises(ToolAccessDenied, match="confirmation"):
        registry.invoke(
            role=ToolRole.RECOMMENDATION_EXPERT,
            tool_name=tool.name,
            arguments={"value": "recipe-1"},
            context=_context("user_data:write"),
        )
    result = registry.invoke(
        role=ToolRole.RECOMMENDATION_EXPERT,
        tool_name=tool.name,
        arguments={"value": "recipe-1"},
        context=_context("user_data:write"),
        confirmed=True,
    )

    assert result.output == "recipe-1"
    assert sink.traces[-1].status is ToolTraceStatus.SUCCEEDED
    assert sink.traces[-1].argument_names == ["value"]


def test_external_side_effect_forbids_automatic_retry() -> None:
    tool = _tool(
        "send_report_email",
        ToolPolicy(
            ToolRiskLevel.EXTERNAL_SIDE_EFFECT,
            required_permissions=frozenset({"external:send"}),
            requires_confirmation=True,
            allow_automatic_retry=False,
        ),
    )
    registry, sink = _registry(tool)

    with pytest.raises(ToolAccessDenied, match="automatic retry"):
        registry.invoke(
            role=ToolRole.NUTRITION_EXPERT,
            tool_name=tool.name,
            arguments={"value": "report-1"},
            context=_context("external:send"),
            confirmed=True,
            automatic_retry=True,
        )

    assert sink.traces[0].risk_level is ToolRiskLevel.EXTERNAL_SIDE_EFFECT
    assert sink.traces[0].status is ToolTraceStatus.DENIED


def test_validation_and_service_failures_are_traced() -> None:
    tool = _tool("search_recipe_knowledge", ToolPolicy(ToolRiskLevel.READ_ONLY))
    registry, sink = _registry(tool)

    with pytest.raises(ValidationError):
        registry.invoke(
            role=ToolRole.KNOWLEDGE_EXPERT,
            tool_name=tool.name,
            arguments={"value": ""},
            context=_context(),
        )

    failing = _tool(
        "search_recipe_knowledge",
        ToolPolicy(ToolRiskLevel.READ_ONLY),
        fail=True,
    )
    failing_registry, failing_sink = _registry(failing)
    with pytest.raises(RuntimeError, match="service failed"):
        failing_registry.invoke(
            role=ToolRole.KNOWLEDGE_EXPERT,
            tool_name=failing.name,
            arguments={"value": "query"},
            context=_context(),
        )

    assert sink.traces[0].status is ToolTraceStatus.FAILED
    assert failing_sink.traces[0].status is ToolTraceStatus.FAILED
