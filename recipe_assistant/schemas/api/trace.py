"""Agent run trace API DTOs."""

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, Field

from recipe_assistant.schemas.api.common import ApiSchema


class AgentRunTraceCreate(ApiSchema):
    run_id: str = Field(min_length=1, max_length=64)
    route: str = Field(min_length=1, max_length=50)
    original_input: str
    normalized_input: str
    events: list[dict[str, Any]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("events", "events_json"),
    )
    tasks: list[dict[str, Any]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("tasks", "tasks_json"),
    )
    artifacts: list[dict[str, Any]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("artifacts", "artifacts_json"),
    )
    sources: list[dict[str, Any]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("sources", "sources_json"),
    )
    latency_ms: float | None = Field(default=None, ge=0)
    token_usage: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("token_usage", "token_usage_json"),
    )


class AgentRunTraceRead(AgentRunTraceCreate):
    id: int
    user_id: int
    session_id: int | None
    created_at: datetime
