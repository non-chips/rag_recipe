from __future__ import annotations

from dataclasses import dataclass

from fakes.chat_model import FakeChatModel

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.coordinator import CollaborativeRecipeCoordinator
from recipe_assistant.agents.events import (
    AgentArtifact,
    ArtifactKind,
    ClaimDecision,
    EventType,
    ExpertCapability,
)
from recipe_assistant.agents.factory import MultiExpertHarness
from recipe_assistant.agents.llm import LLMResponseAgent, LLMRouteClassifier
from recipe_assistant.agents.quality import ResponseAgent
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.agents.result import MemoryMessage, ProfileSnapshot, RunContext
from recipe_assistant.agents.router import BusinessRouter
from recipe_assistant.agents.runtime import RecipeAgentRuntime
from recipe_assistant.core.database import utc_now
from recipe_assistant.models import MessageRole
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType


def _decision() -> RouteDecision:
    return RouteDecision(
        route=RouteType.NUTRITION_PLANNING,
        confidence=1.0,
        reason="test",
    )


def _board(run_id: str = "llm-agent-run") -> CollaborationBlackboard:
    return CollaborationBlackboard(
        run_id=run_id,
        user_id=1,
        session_id="llm-session",
        user_input="Give concise nutrition advice from confirmed data.",
        route=_decision(),
    )


@dataclass
class _NutritionExpert:
    name: str = "nutrition_fixture"
    capabilities: frozenset[ExpertCapability] = frozenset(
        {ExpertCapability.NUTRITION_PLANNING}
    )

    def decide(self, task, board) -> ClaimDecision:
        del board
        return ClaimDecision(
            expert_name=self.name,
            accepted=True,
            confidence=1.0,
            reason=f"fixture executes {task.id}",
        )

    def execute(self, task, board) -> AgentArtifact:
        payloads = {
            "nutrition.meal_history": {
                "user_id": 1,
                "records": (),
                "included_event_types": ("CONSUME",),
            },
            "nutrition.summary": {
                "confirmed_meal_count": 0,
                "data_coverage": 0.0,
            },
            "nutrition.guidance": {
                "based_on_confirmed_meals": 0,
                "recommendations": (),
            },
            "nutrition.response_plan": {
                "answer_mode": "food_category_diversity_only",
                "message": "There are not enough confirmed meal records.",
            },
        }
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}",
            owner=self.name,
            kind=task.expected_artifacts[0],
            payload=payloads[task.id],
            confidence=1.0,
            task_id=task.id,
        )


class _StaticRouter:
    classifier = None

    def route(self, query: str) -> RouteDecision:
        del query
        return _decision()


class _StructuredModel:
    def __init__(self) -> None:
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        assert schema is RouteDecision
        assert kwargs == {"method": "json_mode"}
        return self

    def invoke(self, messages):
        assert len(messages) == 2
        self.calls += 1
        return RouteDecision(
            route=RouteType.RECIPE_RECOMMENDATION,
            confidence=0.88,
            reason="structured model decision",
        )


def test_low_confidence_router_uses_lazy_structured_model_only_when_needed() -> None:
    model = _StructuredModel()
    provider_calls = 0

    def provider():
        nonlocal provider_calls
        provider_calls += 1
        return model

    classifier = LLMRouteClassifier(provider, model_name="fake-router")
    router = BusinessRouter(classifier=classifier)

    high_confidence = router.route("hello")
    low_confidence = router.route("Please take a broad look and decide what I need.")

    assert high_confidence.route is RouteType.SIMPLE
    assert low_confidence.route is RouteType.RECIPE_RECOMMENDATION
    assert provider_calls == 1
    assert model.calls == 1
    assert classifier.last_trace is not None
    assert classifier.last_trace["llm_used"] is True
    assert classifier.last_trace["purpose"] == "route_classification"


def test_router_model_failure_returns_rule_fallback_with_trace() -> None:
    def unavailable():
        raise TimeoutError("model timeout")

    classifier = LLMRouteClassifier(unavailable, model_name="offline")
    decision = BusinessRouter(classifier=classifier).route(
        "Please decide what kind of help this requires."
    )

    assert decision.route is RouteType.RECIPE_KNOWLEDGE
    assert decision.confidence == 0.45
    assert classifier.last_trace is not None
    assert classifier.last_trace["llm_used"] is False
    assert "TimeoutError" in classifier.last_trace["fallback_reason"]


def test_llm_response_is_guarded_accepted_traced_and_streamed() -> None:
    model = FakeChatModel(
        response_text=(
            "Based on confirmed data, add one meal record before nutrition analysis."
        )
    )
    coordinator = CollaborativeRecipeCoordinator(
        ExpertRegistry([_NutritionExpert()]),
        response_agent=LLMResponseAgent(
            lambda: model,
            model_name="fake-response",
        ),
    )
    runtime = RecipeAgentRuntime(coordinator)
    harness = MultiExpertHarness(
        runtime_provider=lambda: runtime,
        router=_StaticRouter(),  # type: ignore[arg-type]
    )
    context = RunContext(
        run_id="llm-harness-run",
        user_id=1,
        session_id=1,
        session_public_id="llm-session",
        original_input="nutrition advice",
        normalized_input="nutrition advice",
        profile=ProfileSnapshot(),
        history=[
            MemoryMessage(
                role=MessageRole.USER,
                content="I planned a light dinner.",
                created_at=utc_now(),
            ),
            MemoryMessage(
                role=MessageRole.ASSISTANT,
                content="The current plan needs a confirmed meal record.",
                created_at=utc_now(),
            ),
        ],
    )

    outcome = harness.run(context)

    assert outcome.result.final_text == model.response_text
    assert "".join(outcome.result.streamed_tokens) == model.response_text
    assert model.invocation_count == 1
    assert "conversation_context" in str(model.last_messages[-1].content)
    assert "I planned a light dinner." in str(model.last_messages[-1].content)
    llm_event = next(
        event
        for event in outcome.result.events
        if event.get("event_type") == EventType.LLM_COMPLETED.value
    )
    assert llm_event["metadata"]["llm_used"] is True
    assert llm_event["metadata"]["model_name"] == "fake-response"
    assert not any("api_key" in str(event).casefold() for event in outcome.result.events)


def test_response_model_failure_uses_deterministic_proposal() -> None:
    def unavailable():
        raise ConnectionError("offline")

    coordinator = CollaborativeRecipeCoordinator(
        ExpertRegistry([_NutritionExpert()]),
        response_agent=LLMResponseAgent(
            unavailable,
            model_name="offline",
        ),
    )

    outcome = coordinator.coordinate(_board())

    assert outcome.final_artifact.kind is ArtifactKind.RESPONSE_PROPOSAL
    assert outcome.final_artifact.metadata["llm_used"] is False
    assert outcome.final_artifact.metadata["degraded"] is True
    assert "ConnectionError" in outcome.final_artifact.metadata["fallback_reason"]
    assert any(
        event.event_type is EventType.FINAL_ACCEPTED
        for event in outcome.blackboard.events
    )


def test_chat_disabled_path_uses_non_llm_response_agent() -> None:
    coordinator = CollaborativeRecipeCoordinator(ExpertRegistry([_NutritionExpert()]))

    outcome = coordinator.coordinate(_board())

    assert isinstance(coordinator.response_agent, ResponseAgent)
    assert not isinstance(coordinator.response_agent, LLMResponseAgent)
    assert "llm_used" not in outcome.final_artifact.metadata


def test_guardrail_rejects_unsafe_llm_output_and_exhausts_revision() -> None:
    model = FakeChatModel(response_text="Raw chicken is safe without cooking.")
    coordinator = CollaborativeRecipeCoordinator(
        ExpertRegistry([_NutritionExpert()]),
        response_agent=LLMResponseAgent(
            lambda: model,
            model_name="unsafe-fake",
        ),
    )

    outcome = coordinator.coordinate(_board())

    assert outcome.final_artifact.kind is ArtifactKind.ERROR
    assert model.invocation_count == 2
    assert any(
        event.event_type is EventType.BAD_CASE_CANDIDATE
        for event in outcome.blackboard.events
    )
