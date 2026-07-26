"""Persist one completed HarnessOutcome without leaking ORM entities."""

from recipe_assistant.agents.events import thaw_value
from recipe_assistant.agents.result import HarnessOutcome
from recipe_assistant.models import AgentRunTrace
from recipe_assistant.repositories.interfaces import TraceRepository


class TraceService:
    def __init__(self, repository: TraceRepository) -> None:
        self.repository = repository

    def save(self, outcome: HarnessOutcome) -> AgentRunTrace:
        context = outcome.context
        return self.repository.add(
            run_id=context.run_id,
            user_id=context.user_id,
            session_id=context.session_id,
            route=outcome.route_decision.route.value,
            original_input=context.original_input,
            normalized_input=context.normalized_input,
            events=self._project_events(outcome.result.events),
            sources=thaw_value(outcome.result.sources),
            latency_ms=outcome.latency_ms,
            token_usage=thaw_value(outcome.result.token_usage),
        )

    @staticmethod
    def _project_events(events: list[dict]) -> list[dict]:
        projected = thaw_value(events)
        skill_audit_keys = (
            "selected_skill_refs",
            "signals",
            "risk",
            "hard_constraints_authoritative",
            "skill_context_hash",
            "selection_reason_code",
        )
        for event in projected:
            metadata = event.get("metadata")
            if not isinstance(metadata, dict):
                continue
            if metadata.get("kind") != "SKILL_CONTEXT":
                continue
            event["metadata"] = {
                "kind": "SKILL_CONTEXT",
                **{
                    key: metadata[key]
                    for key in skill_audit_keys
                    if key in metadata
                },
            }
        return projected
