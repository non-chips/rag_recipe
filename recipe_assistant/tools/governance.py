"""Risk classification and deny-by-default tool authorization."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from recipe_assistant.tools.context import ToolContext


class ToolRiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    USER_DATA_READ = "USER_DATA_READ"
    USER_DATA_WRITE = "USER_DATA_WRITE"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"


class ToolAccessDenied(PermissionError):
    """Raised when a tool call is not registered or authorized."""


class UnregisteredToolError(ToolAccessDenied):
    """Raised when a requested tool has no local registration."""


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """Authorization requirements attached to one tool adapter."""

    risk_level: ToolRiskLevel
    required_permissions: frozenset[str] = frozenset()
    requires_confirmation: bool = False
    allow_automatic_retry: bool = True

    def __post_init__(self) -> None:
        if (
            self.risk_level is ToolRiskLevel.EXTERNAL_SIDE_EFFECT
            and self.allow_automatic_retry
        ):
            raise ValueError("external side-effect tools cannot allow automatic retry")


class ToolGovernance:
    """Authorize a tool policy from trusted context and system call flags."""

    def authorize(
        self,
        policy: ToolPolicy,
        context: ToolContext,
        *,
        confirmed: bool = False,
        automatic_retry: bool = False,
    ) -> None:
        missing = policy.required_permissions - context.permissions
        if missing:
            raise ToolAccessDenied(
                "missing tool permissions: " + ", ".join(sorted(missing))
            )
        if policy.requires_confirmation and not confirmed:
            raise ToolAccessDenied("tool call requires explicit user confirmation")
        if automatic_retry and not policy.allow_automatic_retry:
            raise ToolAccessDenied("automatic retry is forbidden for this tool")
