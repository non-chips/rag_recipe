"""Developer-controlled Bad Case state machine and regression gates."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from recipe_assistant.core.database import session_scope, utc_now
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.bad_case import BadCaseCandidate
from recipe_assistant.models.bad_case_resolution import (
    BadCaseResolution,
    RegressionSampleDraft,
)
from recipe_assistant.models.bad_case_review import BadCaseReview
from recipe_assistant.models.implicit_feedback_signal import ImplicitFeedbackSignal
from recipe_assistant.models.interaction_feedback import InteractionFeedback
from recipe_assistant.schemas.api.bad_case_admin import (
    ApproveBadCaseRequest,
    BadCaseDetailResponse,
    BadCaseResolutionResponse,
    BadCaseReviewResponse,
    BadCaseSummaryResponse,
    ConfirmRegressionDraftRequest,
    MergeBadCaseRequest,
    RegressionSampleDraftResponse,
    RejectBadCaseRequest,
    ResolveBadCaseRequest,
    ReviewAction,
    RootCauseContext,
    RootCauseSuggestion,
    VerifyBadCaseRequest,
)
from recipe_assistant.services.root_cause_analysis import RootCauseAnalysisService


class EvaluationService:
    """Apply only explicit developer actions and append an audit record."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        root_cause_service: RootCauseAnalysisService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.root_cause_service = root_cause_service or RootCauseAnalysisService()

    def list_candidates(self, status: str | None = None) -> list[BadCaseSummaryResponse]:
        with session_scope(self.session_factory) as session:
            statement = select(BadCaseCandidate)
            if status:
                statement = statement.where(BadCaseCandidate.status == status)
            statement = statement.order_by(
                BadCaseCandidate.updated_at.desc(), BadCaseCandidate.id.desc()
            )
            return [self._summary(item) for item in session.scalars(statement)]

    def get_detail(self, bad_case_id: int) -> BadCaseDetailResponse:
        with session_scope(self.session_factory) as session:
            candidate = self._require_candidate(session, bad_case_id)
            return self._detail(session, candidate)

    def approve(
        self,
        bad_case_id: int,
        actor_id: str,
        request: ApproveBadCaseRequest,
    ) -> BadCaseDetailResponse:
        with session_scope(self.session_factory) as session:
            candidate = self._require_candidate(session, bad_case_id)
            self._require_status(candidate, "PENDING_REVIEW")
            suggestion = self._suggest(session, candidate)
            self._append_review(
                session,
                candidate=candidate,
                actor_id=actor_id,
                action=ReviewAction.APPROVE,
                to_status="APPROVED",
                note=request.review_note,
                suggestion=suggestion,
                final_category=request.final_category.value,
                final_root_cause=request.final_root_cause,
                severity=request.severity.value,
                assignee=request.assignee,
            )
            candidate.status = "APPROVED"
            candidate.updated_at = utc_now()
            draft = session.scalar(
                select(RegressionSampleDraft).where(
                    RegressionSampleDraft.bad_case_id == candidate.id
                )
            )
            if draft is None:
                session.add(
                    RegressionSampleDraft(
                        bad_case_id=candidate.id,
                        input_text=candidate.normalized_request,
                        expected_output=None,
                        expected_constraints_json=list(
                            candidate.snapshot_json.get(
                                "hard_constraint_violations", []
                            )
                        ),
                        developer_confirmed=False,
                    )
                )
            session.flush()
            return self._detail(session, candidate)

    def reject(
        self,
        bad_case_id: int,
        actor_id: str,
        request: RejectBadCaseRequest,
    ) -> BadCaseDetailResponse:
        with session_scope(self.session_factory) as session:
            candidate = self._require_candidate(session, bad_case_id)
            self._require_status(candidate, "PENDING_REVIEW")
            suggestion = self._suggest(session, candidate)
            self._append_review(
                session,
                candidate=candidate,
                actor_id=actor_id,
                action=ReviewAction.REJECT,
                to_status="REJECTED",
                note=request.review_note,
                suggestion=suggestion,
            )
            candidate.status = "REJECTED"
            candidate.updated_at = utc_now()
            session.flush()
            return self._detail(session, candidate)

    def merge(
        self,
        bad_case_id: int,
        actor_id: str,
        request: MergeBadCaseRequest,
    ) -> BadCaseDetailResponse:
        with session_scope(self.session_factory) as session:
            candidate = self._require_candidate(session, bad_case_id)
            self._require_status(candidate, "PENDING_REVIEW")
            target = self._require_candidate(session, request.target_bad_case_id)
            if target.id == candidate.id:
                raise ValueError("a Bad Case cannot be merged into itself")
            if target.status in {"REJECTED", "MERGED"}:
                raise ValueError("merge target must remain an active Bad Case")
            suggestion = self._suggest(session, candidate)
            self._append_review(
                session,
                candidate=candidate,
                actor_id=actor_id,
                action=ReviewAction.MERGE,
                to_status="MERGED",
                note=request.review_note,
                suggestion=suggestion,
                merge_target_id=target.id,
            )
            candidate.status = "MERGED"
            candidate.updated_at = utc_now()
            session.flush()
            return self._detail(session, candidate)

    def confirm_regression_draft(
        self,
        bad_case_id: int,
        actor_id: str,
        request: ConfirmRegressionDraftRequest,
    ) -> BadCaseDetailResponse:
        with session_scope(self.session_factory) as session:
            candidate = self._require_candidate(session, bad_case_id)
            self._require_status(candidate, "APPROVED")
            draft = self._require_draft(session, candidate.id)
            draft.expected_output = request.expected_output
            draft.expected_constraints_json = list(request.expected_constraints)
            draft.developer_confirmed = True
            draft.confirmed_by = actor_id
            draft.confirmed_at = utc_now()
            self._append_review(
                session,
                candidate=candidate,
                actor_id=actor_id,
                action=ReviewAction.CONFIRM_REGRESSION_DRAFT,
                to_status="APPROVED",
                note=request.review_note,
            )
            session.flush()
            return self._detail(session, candidate)

    def resolve(
        self,
        bad_case_id: int,
        actor_id: str,
        request: ResolveBadCaseRequest,
    ) -> BadCaseDetailResponse:
        if not request.evaluation_passed:
            raise ValueError("a failed evaluation cannot transition to RESOLVED")
        with session_scope(self.session_factory) as session:
            candidate = self._require_candidate(session, bad_case_id)
            self._require_status(candidate, "APPROVED")
            draft = self._require_draft(session, candidate.id)
            if not draft.developer_confirmed or not draft.expected_output:
                raise ValueError(
                    "developer must confirm the regression draft expectation first"
                )
            session.add(
                BadCaseResolution(
                    bad_case_id=candidate.id,
                    event_type="RESOLVED",
                    actor_id=actor_id,
                    fix_reference=request.fix_reference,
                    issue_reference=request.issue_reference,
                    regression_test_reference=request.regression_test_reference,
                    evidence_json=list(request.evaluation_evidence),
                    metrics_json=dict(request.metrics),
                    note=request.review_note,
                )
            )
            self._append_review(
                session,
                candidate=candidate,
                actor_id=actor_id,
                action=ReviewAction.RESOLVE,
                to_status="RESOLVED",
                note=request.review_note,
            )
            candidate.status = "RESOLVED"
            candidate.updated_at = utc_now()
            session.flush()
            return self._detail(session, candidate)

    def verify(
        self,
        bad_case_id: int,
        actor_id: str,
        request: VerifyBadCaseRequest,
    ) -> BadCaseDetailResponse:
        if not request.verification_passed:
            raise ValueError("a failed verification cannot transition to VERIFIED")
        with session_scope(self.session_factory) as session:
            candidate = self._require_candidate(session, bad_case_id)
            self._require_status(candidate, "RESOLVED")
            session.add(
                BadCaseResolution(
                    bad_case_id=candidate.id,
                    event_type="VERIFIED",
                    actor_id=actor_id,
                    evidence_json=list(request.verification_evidence),
                    metrics_json=dict(request.metrics),
                    note=request.review_note,
                )
            )
            self._append_review(
                session,
                candidate=candidate,
                actor_id=actor_id,
                action=ReviewAction.VERIFY,
                to_status="VERIFIED",
                note=request.review_note,
            )
            candidate.status = "VERIFIED"
            candidate.updated_at = utc_now()
            session.flush()
            return self._detail(session, candidate)

    @staticmethod
    def _require_candidate(session: Session, bad_case_id: int) -> BadCaseCandidate:
        candidate = session.get(BadCaseCandidate, bad_case_id)
        if candidate is None:
            raise LookupError("Bad Case was not found")
        return candidate

    @staticmethod
    def _require_draft(session: Session, bad_case_id: int) -> RegressionSampleDraft:
        draft = session.scalar(
            select(RegressionSampleDraft).where(
                RegressionSampleDraft.bad_case_id == bad_case_id
            )
        )
        if draft is None:
            raise LookupError("regression sample draft was not found")
        return draft

    @staticmethod
    def _require_status(candidate: BadCaseCandidate, expected: str) -> None:
        if candidate.status != expected:
            raise ValueError(
                f"Bad Case status must be {expected}, got {candidate.status}"
            )

    def _suggest(
        self, session: Session, candidate: BadCaseCandidate
    ) -> RootCauseSuggestion:
        trace = session.scalar(
            select(AgentRunTrace).where(
                AgentRunTrace.run_id == candidate.latest_run_id
            )
        )
        signals = list(
            session.scalars(
                select(ImplicitFeedbackSignal).where(
                    ImplicitFeedbackSignal.run_id == candidate.latest_run_id
                )
            )
        )
        snapshot = candidate.snapshot_json or {}
        trace_snapshot = snapshot.get("trace", {})
        return self.root_cause_service.suggest(
            RootCauseContext(
                candidate_id=candidate.id,
                triggers=tuple(candidate.trigger_types_json or []),
                route=trace.route if trace else str(trace_snapshot.get("route", "")),
                original_input=trace.original_input if trace else candidate.normalized_request,
                assistant_answer=str(snapshot.get("assistant_answer", "")),
                events=tuple(trace.events_json or []) if trace else (),
                sources=tuple(trace.sources_json or []) if trace else (),
                latency_ms=trace.latency_ms if trace else None,
                hard_constraint_violations=tuple(
                    snapshot.get("hard_constraint_violations", [])
                ),
                explicit_feedback=dict(snapshot.get("explicit_feedback", {})),
                implicit_signal_types=tuple(item.signal_type for item in signals),
                versions=dict(trace_snapshot.get("versions", {})),
            )
        )

    def _append_review(
        self,
        session: Session,
        *,
        candidate: BadCaseCandidate,
        actor_id: str,
        action: ReviewAction,
        to_status: str,
        note: str,
        suggestion: RootCauseSuggestion | None = None,
        final_category: str | None = None,
        final_root_cause: str | None = None,
        severity: str | None = None,
        assignee: str | None = None,
        merge_target_id: int | None = None,
    ) -> None:
        session.add(
            BadCaseReview(
                bad_case_id=candidate.id,
                reviewer_id=actor_id,
                action=action.value,
                from_status=candidate.status,
                to_status=to_status,
                automatic_category=(
                    suggestion.possible_category.value if suggestion else None
                ),
                automatic_suggestion_json=(
                    suggestion.model_dump(mode="json") if suggestion else {}
                ),
                final_category=final_category,
                final_root_cause=final_root_cause,
                severity=severity,
                review_note=note,
                assignee=assignee,
                merge_target_id=merge_target_id,
            )
        )

    @staticmethod
    def _summary(candidate: BadCaseCandidate) -> BadCaseSummaryResponse:
        return BadCaseSummaryResponse(
            id=candidate.id,
            status=candidate.status,
            score=candidate.score,
            normalized_request=candidate.normalized_request,
            triggers=tuple(candidate.trigger_types_json or []),
            occurrence_count=candidate.occurrence_count,
            updated_at=candidate.updated_at,
        )

    def _detail(
        self, session: Session, candidate: BadCaseCandidate
    ) -> BadCaseDetailResponse:
        trace = session.scalar(
            select(AgentRunTrace).where(
                AgentRunTrace.run_id == candidate.latest_run_id
            )
        )
        signals = list(
            session.scalars(
                select(ImplicitFeedbackSignal)
                .where(
                    ImplicitFeedbackSignal.run_id.in_(
                        {candidate.first_run_id, candidate.latest_run_id}
                    )
                )
                .order_by(ImplicitFeedbackSignal.created_at, ImplicitFeedbackSignal.id)
            )
        )
        explicit_feedback = session.scalar(
            select(InteractionFeedback).where(
                InteractionFeedback.run_id == candidate.latest_run_id
            )
        )
        possible_similar = list(
            session.scalars(
                select(BadCaseCandidate).where(BadCaseCandidate.id != candidate.id)
            )
        )
        candidate_triggers = set(candidate.trigger_types_json or [])
        similar = sorted(
            (
                item
                for item in possible_similar
                if candidate_triggers & set(item.trigger_types_json or [])
            ),
            key=lambda item: (
                -len(candidate_triggers & set(item.trigger_types_json or [])),
                -item.score,
                item.id,
            ),
        )[:5]
        reviews = list(
            session.scalars(
                select(BadCaseReview)
                .where(BadCaseReview.bad_case_id == candidate.id)
                .order_by(BadCaseReview.created_at, BadCaseReview.id)
            )
        )
        draft = session.scalar(
            select(RegressionSampleDraft).where(
                RegressionSampleDraft.bad_case_id == candidate.id
            )
        )
        resolutions = list(
            session.scalars(
                select(BadCaseResolution)
                .where(BadCaseResolution.bad_case_id == candidate.id)
                .order_by(BadCaseResolution.created_at, BadCaseResolution.id)
            )
        )
        trace_payload = {}
        if trace is not None:
            trace_payload = {
                "run_id": trace.run_id,
                "route": trace.route,
                "original_input": trace.original_input,
                "events": trace.events_json or [],
                "tasks": trace.tasks_json or [],
                "artifacts": trace.artifacts_json or [],
                "sources": trace.sources_json or [],
                "latency_ms": trace.latency_ms,
                "token_usage": trace.token_usage_json or {},
                "created_at": trace.created_at.isoformat(),
            }
        summary = self._summary(candidate)
        snapshot = dict(candidate.snapshot_json or {})
        snapshot_trace = dict(snapshot.get("trace", {}))
        return BadCaseDetailResponse(
            **summary.model_dump(),
            first_run_id=candidate.first_run_id,
            latest_run_id=candidate.latest_run_id,
            snapshot=snapshot,
            trace=trace_payload,
            user_question=(
                trace.original_input if trace is not None else candidate.normalized_request
            ),
            assistant_answer=str(snapshot.get("assistant_answer", "")),
            explicit_feedback=(
                {
                    "id": explicit_feedback.id,
                    "rating": explicit_feedback.rating.value,
                    "reason_tags": explicit_feedback.reason_tags_json or [],
                    "comment": explicit_feedback.comment,
                }
                if explicit_feedback is not None
                else None
            ),
            implicit_signals=tuple(
                {
                    "id": item.id,
                    "run_id": item.run_id,
                    "signal_type": item.signal_type,
                    "status": item.status,
                    "probability": item.probability,
                    "confidence": item.confidence,
                    "evidence": item.evidence_json or [],
                }
                for item in signals
            ),
            similar_bad_cases=tuple(self._summary(item) for item in similar),
            versions=dict(snapshot_trace.get("versions", {})),
            root_cause_suggestion=self._suggest(session, candidate),
            reviews=tuple(self._review_response(item) for item in reviews),
            regression_draft=(self._draft_response(draft) if draft else None),
            resolutions=tuple(
                self._resolution_response(item) for item in resolutions
            ),
        )

    @staticmethod
    def _review_response(review: BadCaseReview) -> BadCaseReviewResponse:
        return BadCaseReviewResponse(
            id=review.id,
            bad_case_id=review.bad_case_id,
            reviewer_id=review.reviewer_id,
            action=review.action,
            from_status=review.from_status,
            to_status=review.to_status,
            automatic_category=review.automatic_category,
            automatic_suggestion=dict(review.automatic_suggestion_json or {}),
            final_category=review.final_category,
            final_root_cause=review.final_root_cause,
            severity=review.severity,
            review_note=review.review_note,
            assignee=review.assignee,
            merge_target_id=review.merge_target_id,
            created_at=review.created_at,
        )

    @staticmethod
    def _draft_response(draft: RegressionSampleDraft) -> RegressionSampleDraftResponse:
        return RegressionSampleDraftResponse(
            id=draft.id,
            bad_case_id=draft.bad_case_id,
            input_text=draft.input_text,
            expected_output=draft.expected_output,
            expected_constraints=tuple(draft.expected_constraints_json or []),
            developer_confirmed=draft.developer_confirmed,
            confirmed_by=draft.confirmed_by,
            created_at=draft.created_at,
            confirmed_at=draft.confirmed_at,
        )

    @staticmethod
    def _resolution_response(
        resolution: BadCaseResolution,
    ) -> BadCaseResolutionResponse:
        return BadCaseResolutionResponse(
            id=resolution.id,
            bad_case_id=resolution.bad_case_id,
            event_type=resolution.event_type,
            actor_id=resolution.actor_id,
            fix_reference=resolution.fix_reference,
            issue_reference=resolution.issue_reference,
            regression_test_reference=resolution.regression_test_reference,
            evidence=tuple(resolution.evidence_json or []),
            metrics=dict(resolution.metrics_json or {}),
            note=resolution.note,
            created_at=resolution.created_at,
        )
