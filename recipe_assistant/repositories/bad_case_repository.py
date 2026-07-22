"""Persistence for weak signals and review-gated Bad Case candidates."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from recipe_assistant.core.database import utc_now
from recipe_assistant.models.bad_case import BadCaseCandidate
from recipe_assistant.models.implicit_feedback_signal import ImplicitFeedbackSignal


class BadCaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_signal(
        self,
        *,
        user_id: int,
        session_id: int,
        run_id: str,
        signal_type: str,
        probability: float,
        confidence: float,
        evidence: list[str],
    ) -> ImplicitFeedbackSignal:
        signal = self.session.scalar(
            select(ImplicitFeedbackSignal).where(
                ImplicitFeedbackSignal.run_id == run_id,
                ImplicitFeedbackSignal.signal_type == signal_type,
            )
        )
        if signal is None:
            signal = ImplicitFeedbackSignal(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                signal_type=signal_type,
                status="SIGNAL",
                probability=probability,
                confidence=confidence,
                evidence_json=list(evidence),
            )
            self.session.add(signal)
        else:
            signal.probability = probability
            signal.confidence = confidence
            signal.evidence_json = list(evidence)
            signal.updated_at = utc_now()
        self.session.flush()
        return signal

    def get_candidate_by_fingerprint(self, fingerprint: str) -> BadCaseCandidate | None:
        return self.session.scalar(
            select(BadCaseCandidate).where(BadCaseCandidate.fingerprint == fingerprint)
        )

    def create_candidate(
        self,
        *,
        fingerprint: str,
        user_id: int,
        session_id: int,
        run_id: str,
        score: float,
        normalized_request: str,
        triggers: list[str],
        snapshot: dict,
    ) -> BadCaseCandidate:
        candidate = BadCaseCandidate(
            fingerprint=fingerprint,
            user_id=user_id,
            session_id=session_id,
            first_run_id=run_id,
            latest_run_id=run_id,
            status="PENDING_REVIEW",
            score=score,
            normalized_request=normalized_request,
            trigger_types_json=list(triggers),
            snapshot_json=dict(snapshot),
            occurrence_count=1,
        )
        self.session.add(candidate)
        self.session.flush()
        return candidate

    def merge_occurrence(
        self,
        candidate: BadCaseCandidate,
        *,
        run_id: str,
        score: float,
        triggers: list[str],
        snapshot: dict,
    ) -> BadCaseCandidate:
        candidate.latest_run_id = run_id
        candidate.score = max(candidate.score, score)
        candidate.trigger_types_json = sorted(
            set(candidate.trigger_types_json) | set(triggers)
        )
        candidate.snapshot_json = dict(snapshot)
        candidate.occurrence_count += 1
        candidate.updated_at = utc_now()
        self.session.flush()
        return candidate
