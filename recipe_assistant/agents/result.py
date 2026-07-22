"""Structured schemas for one chat request lifecycle."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from recipe_assistant.core.database import utc_now
from recipe_assistant.models import MessageRole
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType


class RunStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class MemoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: MessageRole
    content: str
    created_at: datetime


class ProfileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_cuisines: list[str] = Field(default_factory=list)
    disliked_ingredients: list[str] = Field(default_factory=list)
    allergens: list[str] = Field(default_factory=list)
    available_appliances: list[str] = Field(default_factory=list)
    default_servings: int | None = None
    skill_level: str | None = None
    planning_goal: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: int = Field(gt=0)
    message: str
    session_public_id: str | None = None


class RunContext(BaseModel):
    """System-created context passed to the single-turn harness."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    user_id: int
    session_id: int
    session_public_id: str
    original_input: str
    normalized_input: str
    profile: ProfileSnapshot
    history: list[MemoryMessage] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utc_now)


class AgentRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RunStatus
    final_text: str = Field(min_length=1)
    events: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    token_usage: dict[str, Any] = Field(default_factory=dict)
    used_legacy_executor: bool = False
    error: str | None = None


class HarnessOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: RunContext
    route_decision: RouteDecision
    result: AgentRunResult
    latency_ms: float = Field(ge=0.0)


class ChatServiceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    session_public_id: str
    user_message_id: int
    assistant_message_id: int
    route: RouteType
    content: str
    outcome: HarnessOutcome
