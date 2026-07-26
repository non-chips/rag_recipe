from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ExpertCapability,
    thaw_value,
)
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.agents.skills import SkillContextAgent
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.services.skills import (
    SkillContextPayload,
    SkillRegistry,
    SkillSignal,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class _SignalExtractor:
    signals: tuple[SkillSignal, ...]

    def extract(
        self,
        board: CollaborationBlackboard,
    ) -> tuple[SkillSignal, ...]:
        del board
        return self.signals


class _UnknownSignalExtractor:
    def extract(self, board: CollaborationBlackboard):
        del board
        return ("UNKNOWN_SIGNAL",)


class _FailingRegistry:
    def select(self, request):
        del request
        raise RuntimeError("registry unavailable")


def _board(
    route: RouteType,
    *,
    artifacts: tuple[AgentArtifact, ...] = (),
) -> CollaborationBlackboard:
    return CollaborationBlackboard(
        run_id="run-skill-agent",
        user_id=1,
        session_id="session-skill-agent",
        user_input="current request",
        route=RouteDecision(
            route=route,
            confidence=1.0,
            reason="test route",
        ),
        artifacts=artifacts,
    )


def _task(
    capability: ExpertCapability = ExpertCapability.SKILL_SELECTION,
) -> AgentTask:
    return AgentTask(
        id="context.skills",
        title="SelectBusinessSkills",
        capability=capability,
        expected_artifacts=(ArtifactKind.SKILL_CONTEXT,),
    )


def _payload(artifact: AgentArtifact) -> SkillContextPayload:
    return SkillContextPayload.model_validate(artifact.payload)


def _registry() -> SkillRegistry:
    return SkillRegistry.load(PROJECT_ROOT / "skills")


@pytest.mark.parametrize(
    ("route", "signal", "expected_ref"),
    [
        (
            RouteType.RECIPE_RECOMMENDATION,
            SkillSignal.ALLERGY_MENTIONED,
            "allergy_safe_recommendation@1.0.0",
        ),
        (
            RouteType.RECIPE_KNOWLEDGE,
            SkillSignal.SUBSTITUTION_REQUESTED,
            "ingredient_substitution@1.0.0",
        ),
        (
            RouteType.NUTRITION_PLANNING,
            SkillSignal.NUTRITION_REPORT_REQUESTED,
            "source_aware_nutrition_report@1.0.0",
        ),
        (
            RouteType.RECIPE_RECOMMENDATION,
            SkillSignal.WEATHER_CONTEXT_REQUIRED,
            "weather_aware_recommendation@1.0.0",
        ),
    ],
)
def test_skill_context_agent_selects_each_business_skill(
    route: RouteType,
    signal: SkillSignal,
    expected_ref: str,
) -> None:
    agent = SkillContextAgent(
        _registry(),
        _SignalExtractor((signal,)),
    )

    artifact = agent.execute(_task(), _board(route))
    payload = _payload(artifact)

    assert artifact.kind is ArtifactKind.SKILL_CONTEXT
    assert payload.selected_skill_refs == [expected_ref]
    assert payload.signals == [signal]
    assert payload.hard_constraints_authoritative is True


def test_skill_context_agent_selects_allergy_and_weather_stably() -> None:
    agent = SkillContextAgent(
        _registry(),
        _SignalExtractor(
            (
                SkillSignal.WEATHER_CONTEXT_REQUIRED,
                SkillSignal.ALLERGY_MENTIONED,
            )
        ),
    )

    payload = _payload(
        agent.execute(
            _task(),
            _board(RouteType.RECIPE_RECOMMENDATION),
        )
    )

    assert payload.selected_skill_refs == [
        "allergy_safe_recommendation@1.0.0",
        "weather_aware_recommendation@1.0.0",
    ]
    assert payload.signals == [
        SkillSignal.ALLERGY_MENTIONED,
        SkillSignal.WEATHER_CONTEXT_REQUIRED,
    ]
    assert payload.risk.value == "HIGH"


def test_skill_context_agent_publishes_valid_empty_selection() -> None:
    agent = SkillContextAgent(
        _registry(),
        _SignalExtractor(()),
    )

    artifact = agent.execute(
        _task(),
        _board(RouteType.RECIPE_RECOMMENDATION),
    )
    payload = _payload(artifact)

    assert payload.selected_skill_refs == []
    assert payload.signals == []
    assert payload.selection_reason.endswith("signals=none;selected=none")
    assert artifact.metadata == {
        "selected_skill_count": 0,
        "signal_count": 0,
    }


def test_skill_context_agent_rejects_unknown_signal_without_matching() -> None:
    agent = SkillContextAgent(
        _registry(),
        _UnknownSignalExtractor(),
    )

    with pytest.raises(ValidationError, match="UNKNOWN_SIGNAL"):
        agent.execute(
            _task(),
            _board(RouteType.COMPLEX),
        )


def test_skill_context_agent_output_order_and_payload_hash_are_stable(
) -> None:
    agent = SkillContextAgent(
        _registry(),
        _SignalExtractor(
            (
                SkillSignal.WEATHER_CONTEXT_REQUIRED,
                SkillSignal.SUBSTITUTION_REQUESTED,
                SkillSignal.ALLERGY_MENTIONED,
            )
        ),
    )
    board = _board(RouteType.COMPLEX)

    first = agent.execute(_task(), board)
    second = agent.execute(_task(), board)
    first_json = json.dumps(
        thaw_value(first.payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    second_json = json.dumps(
        thaw_value(second.payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    assert first_json == second_json
    assert hashlib.sha256(first_json.encode()).hexdigest() == hashlib.sha256(
        second_json.encode()
    ).hexdigest()


def test_skill_context_agent_does_not_rewrite_input_artifacts() -> None:
    source = AgentArtifact(
        id="source-artifact",
        owner="fixture",
        kind=ArtifactKind.RECIPE_EVIDENCE,
        payload={"items": [{"recipe_id": "recipe-1"}]},
        confidence=1.0,
        task_id="knowledge.retrieve",
    )
    board = _board(RouteType.RECIPE_KNOWLEDGE, artifacts=(source,))
    before = thaw_value(board.artifacts[0].payload)
    agent = SkillContextAgent(
        _registry(),
        _SignalExtractor((SkillSignal.SUBSTITUTION_REQUESTED,)),
    )

    agent.execute(_task(), board)

    assert thaw_value(board.artifacts[0].payload) == before
    assert board.artifacts == (source,)


def test_skill_context_agent_registry_failure_publishes_no_partial_artifact() -> None:
    board = _board(RouteType.RECIPE_RECOMMENDATION)
    agent = SkillContextAgent(
        _FailingRegistry(),  # type: ignore[arg-type]
        _SignalExtractor((SkillSignal.ALLERGY_MENTIONED,)),
    )

    with pytest.raises(RuntimeError, match="registry unavailable"):
        agent.execute(_task(), board)
    assert board.artifacts == ()


def test_skill_context_agent_is_independently_registered() -> None:
    agent = SkillContextAgent(
        _registry(),
        _SignalExtractor(()),
    )
    registry = ExpertRegistry([agent])

    assert registry.resolve(ExpertCapability.SKILL_SELECTION) is agent
    assert agent.decide(_task(), _board(RouteType.COMPLEX)).accepted is True
    assert (
        agent.decide(
            _task(ExpertCapability.RECIPE_RECOMMENDATION),
            _board(RouteType.RECIPE_RECOMMENDATION),
        ).accepted
        is False
    )
