"""Persist one completed HarnessOutcome without leaking ORM entities."""

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
            events=outcome.result.events,
            sources=outcome.result.sources,
            latency_ms=outcome.latency_ms,
            token_usage=outcome.result.token_usage,
        )
