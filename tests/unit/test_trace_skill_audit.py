from __future__ import annotations

from recipe_assistant.agents.result import (
    AgentRunResult,
    HarnessOutcome,
    ProfileSnapshot,
    RunContext,
    RunStatus,
)
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.services.skills import SkillContextPayload
from recipe_assistant.services.trace import TraceService


class _TraceRepository:
    def __init__(self) -> None:
        self.values = {}

    def add(self, **values):
        self.values = values
        return values


def _payload(
    refs: list[str],
    signals: list[str],
) -> SkillContextPayload:
    return SkillContextPayload(
        selected_skill_refs=refs,
        signals=signals,
        risk="HIGH",
        prompt_context="SECRET-FULL-SKILL-PROMPT",
        selection_reason="route and safe enum signals",
        hard_constraints_authoritative=True,
    )


def _outcome(events: list[dict]) -> HarnessOutcome:
    return HarnessOutcome(
        context=RunContext(
            run_id="trace-skill-run",
            user_id=1,
            session_id=2,
            session_public_id="trace-skill-session",
            original_input="test",
            normalized_input="test",
            profile=ProfileSnapshot(),
        ),
        route_decision=RouteDecision(
            route=RouteType.RECIPE_RECOMMENDATION,
            confidence=1.0,
            reason="test",
        ),
        result=AgentRunResult(
            status=RunStatus.SUCCEEDED,
            final_text="safe response",
            events=events,
        ),
        latency_ms=1.0,
    )


def test_trace_skill_projection_contains_hash_and_no_prompt() -> None:
    payload = _payload(
        ["allergy_safe_recommendation@1.0.0"],
        ["ALLERGY_MENTIONED"],
    )
    metadata = {
        "kind": "SKILL_CONTEXT",
        **payload.audit_projection(),
        "prompt_context": payload.prompt_context,
        "sensitive_preference_text": "do not persist",
    }
    repository = _TraceRepository()

    TraceService(repository).save(
        _outcome(
            [
                {
                    "event_type": "ARTIFACT_ADDED",
                    "actor": "skill_context_agent",
                    "metadata": metadata,
                },
                {
                    "event_type": "TONE_ANALYZED",
                    "actor": "tone_analysis_service",
                    "metadata": {"possible_dissatisfaction": 0.4},
                },
                {
                    "event_type": "BAD_CASE_CANDIDATE",
                    "actor": "coordinator",
                    "metadata": {"trigger": "QUALITY_REVISIONS_EXHAUSTED"},
                },
            ]
        )
    )

    events = repository.values["events"]
    skill_audit = events[0]["metadata"]
    assert skill_audit["selected_skill_refs"] == [
        "allergy_safe_recommendation@1.0.0"
    ]
    assert skill_audit["signals"] == ["ALLERGY_MENTIONED"]
    assert skill_audit["risk"] == "HIGH"
    assert skill_audit["hard_constraints_authoritative"] is True
    assert len(skill_audit["skill_context_hash"]) == 64
    assert skill_audit["selection_reason_code"] == "REGISTRY_MATCH"
    assert "prompt_context" not in skill_audit
    assert "SECRET-FULL-SKILL-PROMPT" not in str(events)
    assert "sensitive_preference_text" not in str(events)
    assert events[1]["event_type"] == "TONE_ANALYZED"
    assert events[2]["event_type"] == "BAD_CASE_CANDIDATE"


def test_trace_skill_hash_and_order_are_stable() -> None:
    first = _payload(
        [
            "weather_aware_recommendation@1.0.0",
            "allergy_safe_recommendation@1.0.0",
        ],
        ["WEATHER_CONTEXT_REQUIRED", "ALLERGY_MENTIONED"],
    ).audit_projection()
    second = _payload(
        [
            "allergy_safe_recommendation@1.0.0",
            "weather_aware_recommendation@1.0.0",
        ],
        ["ALLERGY_MENTIONED", "WEATHER_CONTEXT_REQUIRED"],
    ).audit_projection()

    assert first == second
    assert first["selected_skill_refs"] == [
        "allergy_safe_recommendation@1.0.0",
        "weather_aware_recommendation@1.0.0",
    ]
