"""Contracts for weak feedback signals and Bad Case candidate scoring."""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from recipe_assistant.models.interaction_feedback import FeedbackRating


class FeedbackSignalSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ToneAnalysisRequest(FeedbackSignalSchema):
    current_text: str = Field(min_length=1, max_length=4000)
    recent_user_messages: tuple[str, ...] = Field(default=(), max_length=20)
    current_constraints: tuple[str, ...] = Field(default=(), max_length=30)
    recent_constraints: tuple[str, ...] = Field(default=(), max_length=100)


class ToneSignal(FeedbackSignalSchema):
    possible_frustration: float = Field(ge=0.0, le=1.0)
    possible_impatience: float = Field(ge=0.0, le=1.0)
    possible_dissatisfaction: float = Field(ge=0.0, le=1.0)
    repeated_request: bool
    repeated_constraint: bool
    requested_retry: bool
    explicit_error_reported: bool
    evidence: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)


class SignalType(str, Enum):
    POSSIBLE_FRUSTRATION = "POSSIBLE_FRUSTRATION"
    POSSIBLE_IMPATIENCE = "POSSIBLE_IMPATIENCE"
    POSSIBLE_DISSATISFACTION = "POSSIBLE_DISSATISFACTION"
    REPEATED_REQUEST = "REPEATED_REQUEST"
    REPEATED_CONSTRAINT = "REPEATED_CONSTRAINT"
    REQUESTED_RETRY = "REQUESTED_RETRY"
    TOOL_FAILURE = "TOOL_FAILURE"
    EMPTY_RETRIEVAL = "EMPTY_RETRIEVAL"
    HARD_CONSTRAINT_VIOLATION = "HARD_CONSTRAINT_VIOLATION"


class BadCaseStatus(str, Enum):
    SIGNAL = "SIGNAL"
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"
    MERGED = "MERGED"
    APPROVED = "APPROVED"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"


class BadCaseScoringConfig(FeedbackSignalSchema):
    explicit_dislike_weight: float = 0.70
    explicit_error_weight: float = 0.60
    hard_constraint_violation_weight: float = 0.80
    tool_failure_weight: float = 0.30
    empty_retrieval_weight: float = 0.25
    repeated_request_weight: float = 0.25
    repeated_constraint_weight: float = 0.25
    high_confidence_tone_weight: float = 0.20
    explicit_like_weight: float = -0.50
    candidate_threshold: float = Field(default=0.50, ge=0.0)
    minimum_weak_signal_count: int = Field(default=2, ge=2)
    tone_probability_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    tone_confidence_threshold: float = Field(default=0.60, ge=0.0, le=1.0)


class BadCaseEvaluationRequest(FeedbackSignalSchema):
    user_id: int = Field(gt=0)
    run_id: str = Field(min_length=1, max_length=64)
    session_id: int = Field(gt=0)
    normalized_request: str = Field(min_length=1, max_length=4000)
    tone_signal: ToneSignal
    explicit_rating: FeedbackRating | None = None
    explicit_error_reported: bool = False
    tool_failure: bool = False
    unrecoverable_failure: bool = False
    empty_retrieval: bool = False
    hard_constraint_violations: tuple[str, ...] = Field(default=(), max_length=50)
    trace_snapshot: dict[str, JsonValue] = Field(default_factory=dict)


class BadCaseEvaluationResult(FeedbackSignalSchema):
    status: BadCaseStatus
    score: float = Field(ge=0.0, le=1.0)
    triggers: tuple[str, ...]
    signal_ids: tuple[int, ...]
    candidate_id: int | None = None
    candidate_created: bool = False
    occurrence_count: int = Field(default=0, ge=0)
