"""Transparent scoring and de-duplication of Bad Case candidates."""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from recipe_assistant.core.database import session_scope
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.interaction_feedback import FeedbackRating
from recipe_assistant.repositories.bad_case_repository import BadCaseRepository
from recipe_assistant.schemas.feedback import (
    BadCaseEvaluationRequest,
    BadCaseEvaluationResult,
    BadCaseScoringConfig,
    BadCaseStatus,
    SignalType,
)


class BadCaseService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        config: BadCaseScoringConfig | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.config = config or BadCaseScoringConfig()

    def evaluate(self, request: BadCaseEvaluationRequest) -> BadCaseEvaluationResult:
        triggers, score, weak_triggers, strong_trigger = self._score(request)
        with session_scope(self.session_factory) as session:
            trace = session.scalar(
                select(AgentRunTrace).where(AgentRunTrace.run_id == request.run_id)
            )
            if trace is None:
                raise LookupError("agent run was not found")
            if trace.user_id != request.user_id or trace.session_id != request.session_id:
                raise PermissionError("agent run does not belong to the supplied user/session")

            repository = BadCaseRepository(session)
            signal_ids = self._save_signals(repository, request)
            qualifies = strong_trigger or (
                len(weak_triggers) >= self.config.minimum_weak_signal_count
                and score >= self.config.candidate_threshold
            )
            if not qualifies:
                return BadCaseEvaluationResult(
                    status=BadCaseStatus.SIGNAL,
                    score=score,
                    triggers=tuple(triggers),
                    signal_ids=tuple(signal_ids),
                )

            fingerprint = self._fingerprint(request, triggers)
            snapshot = {
                "run_id": request.run_id,
                "session_id": request.session_id,
                "tone_signal": request.tone_signal.model_dump(mode="json"),
                "trace": request.trace_snapshot,
                "hard_constraint_violations": list(
                    request.hard_constraint_violations
                ),
                "triggers": triggers,
                "score": score,
            }
            candidate = repository.get_candidate_by_fingerprint(fingerprint)
            created = candidate is None
            if candidate is None:
                candidate = repository.create_candidate(
                    fingerprint=fingerprint,
                    user_id=request.user_id,
                    session_id=request.session_id,
                    run_id=request.run_id,
                    score=score,
                    normalized_request=request.normalized_request,
                    triggers=triggers,
                    snapshot=snapshot,
                )
            else:
                candidate = repository.merge_occurrence(
                    candidate,
                    run_id=request.run_id,
                    score=score,
                    triggers=triggers,
                    snapshot=snapshot,
                )
            return BadCaseEvaluationResult(
                status=BadCaseStatus.PENDING_REVIEW,
                score=score,
                triggers=tuple(triggers),
                signal_ids=tuple(signal_ids),
                candidate_id=candidate.id,
                candidate_created=created,
                occurrence_count=candidate.occurrence_count,
            )

    def _score(
        self, request: BadCaseEvaluationRequest
    ) -> tuple[list[str], float, set[str], bool]:
        config = self.config
        weights: list[tuple[str, float]] = []
        weak: set[str] = set()
        strong = False
        if request.explicit_rating is FeedbackRating.DISLIKE:
            weights.append(("EXPLICIT_DISLIKE", config.explicit_dislike_weight))
            strong = True
        elif request.explicit_rating is FeedbackRating.LIKE:
            weights.append(("EXPLICIT_LIKE", config.explicit_like_weight))
        if request.explicit_error_reported or request.tone_signal.explicit_error_reported:
            weights.append(("EXPLICIT_ERROR", config.explicit_error_weight))
            strong = True
        if request.hard_constraint_violations:
            weights.append(
                ("HARD_CONSTRAINT_VIOLATION", config.hard_constraint_violation_weight)
            )
            strong = True
        if request.tool_failure:
            weights.append(("TOOL_FAILURE", config.tool_failure_weight))
            weak.add("TOOL_FAILURE")
            strong = strong or request.unrecoverable_failure
        if request.empty_retrieval:
            weights.append(("EMPTY_RETRIEVAL", config.empty_retrieval_weight))
            weak.add("EMPTY_RETRIEVAL")
        if request.tone_signal.repeated_request or request.tone_signal.requested_retry:
            weights.append(("REPEATED_REQUEST", config.repeated_request_weight))
            weak.add("REPEATED_REQUEST")
        if request.tone_signal.repeated_constraint:
            weights.append(("REPEATED_CONSTRAINT", config.repeated_constraint_weight))
            weak.add("REPEATED_CONSTRAINT")
        tone_probability = max(
            request.tone_signal.possible_frustration,
            request.tone_signal.possible_impatience,
            request.tone_signal.possible_dissatisfaction,
        )
        if (
            tone_probability >= config.tone_probability_threshold
            and request.tone_signal.confidence >= config.tone_confidence_threshold
        ):
            weights.append(
                ("HIGH_CONFIDENCE_TONE", config.high_confidence_tone_weight)
            )
            weak.add("HIGH_CONFIDENCE_TONE")
        triggers = [name for name, _weight in weights]
        score = round(
            min(1.0, max(0.0, sum(weight for _name, weight in weights))), 6
        )
        return triggers, score, weak, strong

    @staticmethod
    def _fingerprint(request: BadCaseEvaluationRequest, triggers: list[str]) -> str:
        stable_triggers = sorted(trigger for trigger in triggers if trigger != "EXPLICIT_LIKE")
        source = "|".join(
            [
                str(request.user_id),
                request.normalized_request.strip().casefold(),
                *stable_triggers,
            ]
        )
        return sha256(source.encode("utf-8")).hexdigest()

    @staticmethod
    def _save_signals(
        repository: BadCaseRepository, request: BadCaseEvaluationRequest
    ) -> list[int]:
        tone = request.tone_signal
        signal_rows: list[tuple[SignalType, float, float, list[str]]] = []
        tone_values = (
            (SignalType.POSSIBLE_FRUSTRATION, tone.possible_frustration),
            (SignalType.POSSIBLE_IMPATIENCE, tone.possible_impatience),
            (SignalType.POSSIBLE_DISSATISFACTION, tone.possible_dissatisfaction),
        )
        for signal_type, probability in tone_values:
            if probability >= 0.50:
                signal_rows.append(
                    (signal_type, probability, tone.confidence, list(tone.evidence))
                )
        if tone.repeated_request:
            signal_rows.append(
                (SignalType.REPEATED_REQUEST, 1.0, tone.confidence, list(tone.evidence))
            )
        if tone.repeated_constraint:
            signal_rows.append(
                (
                    SignalType.REPEATED_CONSTRAINT,
                    1.0,
                    tone.confidence,
                    list(tone.evidence),
                )
            )
        if tone.requested_retry:
            signal_rows.append(
                (SignalType.REQUESTED_RETRY, 1.0, tone.confidence, list(tone.evidence))
            )
        if request.tool_failure:
            signal_rows.append((SignalType.TOOL_FAILURE, 1.0, 1.0, ["trace reported tool failure"]))
        if request.empty_retrieval:
            signal_rows.append((SignalType.EMPTY_RETRIEVAL, 1.0, 1.0, ["trace reported empty retrieval"]))
        if request.hard_constraint_violations:
            signal_rows.append(
                (
                    SignalType.HARD_CONSTRAINT_VIOLATION,
                    1.0,
                    1.0,
                    list(request.hard_constraint_violations),
                )
            )
        ids: list[int] = []
        for signal_type, probability, confidence, evidence in signal_rows:
            signal = repository.upsert_signal(
                user_id=request.user_id,
                session_id=request.session_id,
                run_id=request.run_id,
                signal_type=signal_type.value,
                probability=probability,
                confidence=confidence,
                evidence=evidence,
            )
            ids.append(signal.id)
        return ids
