"""Trace middleware for every local tool invocation attempt."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.governance import ToolAccessDenied, ToolRiskLevel
from recipe_assistant.tools.schemas import (
    ToolCallTrace,
    ToolInvocationResult,
    ToolRole,
    ToolTraceStatus,
)


class ToolTraceSink(Protocol):
    def record(self, trace: ToolCallTrace) -> None:
        """Persist or forward one completed audit trace."""


class InMemoryToolTraceSink:
    """Test and local-development trace sink."""

    def __init__(self) -> None:
        self.traces: list[ToolCallTrace] = []

    def record(self, trace: ToolCallTrace) -> None:
        self.traces.append(trace)


class ToolTraceMiddleware:
    """Wrap authorization, validation and execution in one audit record."""

    def __init__(self, sink: ToolTraceSink) -> None:
        self.sink = sink

    def invoke(
        self,
        *,
        role: ToolRole,
        tool_name: str,
        risk_level: ToolRiskLevel | None,
        arguments: dict[str, Any],
        context: ToolContext,
        operation: Callable[[], Any],
    ) -> ToolInvocationResult:
        trace_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        started_clock = perf_counter()
        status = ToolTraceStatus.SUCCEEDED
        error: Exception | None = None

        try:
            output = operation()
        except ToolAccessDenied as exc:
            status = ToolTraceStatus.DENIED
            error = exc
            raise
        except Exception as exc:
            status = ToolTraceStatus.FAILED
            error = exc
            raise
        finally:
            finished_at = datetime.now(timezone.utc)
            self.sink.record(
                ToolCallTrace(
                    trace_id=trace_id,
                    run_id=context.run_id,
                    user_id=context.user_id,
                    session_id=context.session_id,
                    role=role,
                    tool_name=tool_name,
                    risk_level=risk_level,
                    status=status,
                    argument_names=sorted(arguments),
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=(perf_counter() - started_clock) * 1000,
                    error_type=type(error).__name__ if error else None,
                    error_message=str(error) if error else None,
                )
            )

        return ToolInvocationResult(trace_id=trace_id, output=output)
