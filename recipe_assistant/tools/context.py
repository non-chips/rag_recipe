"""System-injected context for local tool calls."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Trusted identity and authorization data never exposed to the LLM schema."""

    run_id: str
    user_id: int
    session_id: str
    route: str
    permissions: frozenset[str] = frozenset()
