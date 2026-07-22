"""Admin-only DTOs for Bad Case review and regression gates."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class AdminSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


class BadCaseCategory(str, Enum):
    ROUTING_ERROR = "ROUTING_ERROR"
    INTENT_EXTRACTION_ERROR = "INTENT_EXTRACTION_ERROR"
    RETRIEVAL_MISS = "RETRIEVAL_MISS"
    RETRIEVAL_IRRELEVANT = "RETRIEVAL_IRRELEVANT"
    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
    HALLUCINATION = "HALLUCINATION"
    CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"
    RECOMMENDATION_MISMATCH = "RECOMMENDATION_MISMATCH"
    NUTRITION_DATA_ISSUE = "NUTRITION_DATA_ISSUE"
    MEMORY_ERROR = "MEMORY_ERROR"
    TOOL_FAILURE = "TOOL_FAILURE"
    LATENCY = "LATENCY"
    STYLE_MISMATCH = "STYLE_MISMATCH"
    FRONTEND_OR_NETWORK = "FRONTEND_OR_NETWORK"
    OTHER = "OTHER"


class BadCaseSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReviewAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    MERGE = "MERGE"
    RESOLVE = "RESOLVE"
    VERIFY = "VERIFY"
    CONFIRM_REGRESSION_DRAFT = "CONFIRM_REGRESSION_DRAFT"


class RootCauseContext(AdminSchema):
    candidate_id: int = Field(gt=0)
    triggers: tuple[str, ...] = ()
    route: str = ""
    original_input: str = ""
    assistant_answer: str = ""
    events: tuple[dict[str, JsonValue], ...] = ()
    sources: tuple[dict[str, JsonValue], ...] = ()
    latency_ms: float | None = Field(default=None, ge=0.0)
    hard_constraint_violations: tuple[str, ...] = ()
    explicit_feedback: dict[str, JsonValue] = Field(default_factory=dict)
    implicit_signal_types: tuple[str, ...] = ()
    versions: dict[str, JsonValue] = Field(default_factory=dict)


class RootCauseSuggestion(AdminSchema):
    possible_category: BadCaseCategory
    confidence: float = Field(ge=0.0, le=1.0)
    affected_component: str | None = None
    evidence: tuple[str, ...] = ()
    suggested_inspection_points: tuple[str, ...] = ()
    explanation: str


class ApproveBadCaseRequest(AdminSchema):
    final_category: BadCaseCategory
    final_root_cause: str = Field(min_length=3, max_length=4000)
    review_note: str = Field(min_length=3, max_length=2000)
    severity: BadCaseSeverity = BadCaseSeverity.MEDIUM
    assignee: str | None = Field(default=None, max_length=100)


class RejectBadCaseRequest(AdminSchema):
    review_note: str = Field(min_length=3, max_length=2000)


class MergeBadCaseRequest(AdminSchema):
    target_bad_case_id: int = Field(gt=0)
    review_note: str = Field(min_length=3, max_length=2000)


class ConfirmRegressionDraftRequest(AdminSchema):
    expected_output: str = Field(min_length=3, max_length=8000)
    expected_constraints: tuple[str, ...] = Field(default=(), max_length=100)
    review_note: str = Field(min_length=3, max_length=2000)


class ResolveBadCaseRequest(AdminSchema):
    fix_reference: str = Field(min_length=3, max_length=500)
    review_note: str = Field(min_length=3, max_length=2000)
    evaluation_passed: bool
    evaluation_evidence: tuple[str, ...] = Field(min_length=1, max_length=100)
    metrics: dict[str, float] = Field(default_factory=dict)
    issue_reference: str | None = Field(default=None, max_length=500)
    regression_test_reference: str | None = Field(default=None, max_length=500)


class VerifyBadCaseRequest(AdminSchema):
    verification_passed: bool
    review_note: str = Field(min_length=3, max_length=2000)
    verification_evidence: tuple[str, ...] = Field(min_length=1, max_length=100)
    metrics: dict[str, float] = Field(default_factory=dict)


class BadCaseReviewResponse(AdminSchema):
    id: int
    bad_case_id: int
    reviewer_id: str
    action: ReviewAction
    from_status: str
    to_status: str
    automatic_category: BadCaseCategory | None
    automatic_suggestion: dict[str, JsonValue]
    final_category: BadCaseCategory | None
    final_root_cause: str | None
    severity: BadCaseSeverity | None
    review_note: str
    assignee: str | None
    merge_target_id: int | None
    created_at: datetime


class RegressionSampleDraftResponse(AdminSchema):
    id: int
    bad_case_id: int
    input_text: str
    expected_output: str | None
    expected_constraints: tuple[str, ...]
    developer_confirmed: bool
    confirmed_by: str | None
    created_at: datetime
    confirmed_at: datetime | None


class BadCaseResolutionResponse(AdminSchema):
    id: int
    bad_case_id: int
    event_type: str
    actor_id: str
    fix_reference: str | None
    issue_reference: str | None
    regression_test_reference: str | None
    evidence: tuple[str, ...]
    metrics: dict[str, float]
    note: str
    created_at: datetime


class BadCaseSummaryResponse(AdminSchema):
    id: int
    status: str
    score: float
    normalized_request: str
    triggers: tuple[str, ...]
    occurrence_count: int
    updated_at: datetime


class BadCaseDetailResponse(BadCaseSummaryResponse):
    first_run_id: str
    latest_run_id: str
    snapshot: dict[str, JsonValue]
    trace: dict[str, JsonValue]
    user_question: str
    assistant_answer: str
    explicit_feedback: dict[str, JsonValue] | None
    implicit_signals: tuple[dict[str, JsonValue], ...]
    similar_bad_cases: tuple[BadCaseSummaryResponse, ...]
    versions: dict[str, JsonValue]
    root_cause_suggestion: RootCauseSuggestion
    reviews: tuple[BadCaseReviewResponse, ...]
    regression_draft: RegressionSampleDraftResponse | None
    resolutions: tuple[BadCaseResolutionResponse, ...]
