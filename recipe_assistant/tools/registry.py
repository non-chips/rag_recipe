"""Role-scoped local tool registry with deny-by-default invocation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.governance import (
    ToolAccessDenied,
    ToolGovernance,
    ToolPolicy,
    UnregisteredToolError,
)
from recipe_assistant.tools.schemas import ToolInvocationResult, ToolRole
from recipe_assistant.tools.tracing import InMemoryToolTraceSink, ToolTraceMiddleware


ToolHandler = Callable[[BaseModel, ToolContext], Any]
PROTECTED_ARGUMENT_NAMES = frozenset(
    {
        "user_id",
        "session_id",
        "database_session",
        "api_key",
        "neo4j_credentials",
        "storage_path",
        "database_credentials",
    }
)


DEFAULT_ROLE_TOOL_NAMES: dict[ToolRole, tuple[str, ...]] = {
    ToolRole.COORDINATOR: (
        "ask_recipe_knowledge_expert",
        "ask_recipe_recommendation_expert",
        "ask_nutrition_planning_expert",
    ),
    ToolRole.KNOWLEDGE_EXPERT: ("search_recipe_knowledge",),
    ToolRole.RECOMMENDATION_EXPERT: (
        "search_recipe_knowledge",
        "recommend_recipes",
        "get_current_weather",
        "get_confirmed_meal_history",
        "save_meal_record",
    ),
    ToolRole.NUTRITION_EXPERT: (
        "search_recipe_knowledge",
        "get_confirmed_meal_history",
        "calculate_recipe_nutrition",
        "create_nutrition_report",
        "send_report_email",
    ),
}


@dataclass(frozen=True, slots=True)
class LocalTool:
    """A thin, typed adapter around an injected domain service method."""

    name: str
    description: str
    args_schema: type[BaseModel]
    handler: ToolHandler
    policy: ToolPolicy

    def invoke(self, arguments: Mapping[str, Any], context: ToolContext) -> Any:
        parsed = self.args_schema.model_validate(dict(arguments))
        return self.handler(parsed, context)


class ToolRegistry:
    """Register tools once and expose only the allowlist assigned to each role."""

    def __init__(
        self,
        tools: Iterable[LocalTool] = (),
        *,
        governance: ToolGovernance | None = None,
        tracing: ToolTraceMiddleware | None = None,
    ) -> None:
        self._tools: dict[str, LocalTool] = {}
        self._role_tool_names = {
            role: list(names) for role, names in DEFAULT_ROLE_TOOL_NAMES.items()
        }
        self.governance = governance or ToolGovernance()
        self.tracing = tracing or ToolTraceMiddleware(InMemoryToolTraceSink())
        for tool in tools:
            self.register(tool)

    def register(
        self,
        tool: LocalTool,
        roles: Iterable[ToolRole] | None = None,
    ) -> None:
        """Register one adapter and optionally add it to explicit role allowlists."""

        protected = PROTECTED_ARGUMENT_NAMES.intersection(tool.args_schema.model_fields)
        if protected:
            raise ValueError(
                "tool schema exposes system-injected fields: " + ", ".join(sorted(protected))
            )
        if tool.name in self._tools:
            raise ValueError(f"tool is already registered: {tool.name}")
        self._tools[tool.name] = tool
        if roles is not None:
            for role in roles:
                names = self._role_tool_names.setdefault(role, [])
                if tool.name not in names:
                    names.append(tool.name)

    def for_role(self, role: ToolRole) -> Sequence[LocalTool]:
        return tuple(
            self._tools[name]
            for name in self._role_tool_names.get(role, [])
            if name in self._tools
        )

    def for_coordinator(self) -> Sequence[LocalTool]:
        return self.for_role(ToolRole.COORDINATOR)

    def for_knowledge_expert(self) -> Sequence[LocalTool]:
        return self.for_role(ToolRole.KNOWLEDGE_EXPERT)

    def for_recommendation_expert(self) -> Sequence[LocalTool]:
        return self.for_role(ToolRole.RECOMMENDATION_EXPERT)

    def for_nutrition_expert(self) -> Sequence[LocalTool]:
        return self.for_role(ToolRole.NUTRITION_EXPERT)

    def invoke(
        self,
        *,
        role: ToolRole,
        tool_name: str,
        arguments: Mapping[str, Any],
        context: ToolContext,
        confirmed: bool = False,
        automatic_retry: bool = False,
    ) -> ToolInvocationResult:
        """Authorize, validate, execute and trace one local tool call."""

        tool = self._tools.get(tool_name)
        risk_level = tool.policy.risk_level if tool else None
        argument_dict = dict(arguments)

        def operation() -> Any:
            resolved = self._resolve(role, tool_name)
            self.governance.authorize(
                resolved.policy,
                context,
                confirmed=confirmed,
                automatic_retry=automatic_retry,
            )
            return resolved.invoke(argument_dict, context)

        return self.tracing.invoke(
            role=role,
            tool_name=tool_name,
            risk_level=risk_level,
            arguments=argument_dict,
            context=context,
            operation=operation,
        )

    def _resolve(self, role: ToolRole, tool_name: str) -> LocalTool:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise UnregisteredToolError(f"tool is not registered: {tool_name}")
        if tool_name not in self._role_tool_names.get(role, []):
            raise ToolAccessDenied(
                f"tool '{tool_name}' is not authorized for role '{role.value}'"
            )
        return tool
