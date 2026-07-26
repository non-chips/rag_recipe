from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ExpertCapability,
)
from recipe_assistant.services.skills import (
    SkillContextPayload,
    SkillRisk,
    SkillSignal,
)


def _payload(**changes) -> SkillContextPayload:
    values = {
        "selected_skill_refs": (),
        "signals": (),
        "risk": SkillRisk.LOW,
        "prompt_context": "# Active behavioral Skills\n- none",
        "selection_reason": "no route and signal match",
    }
    values.update(changes)
    return SkillContextPayload(**values)


@pytest.mark.parametrize(
    ("references", "expected"),
    [
        (
            ["weather_aware_recommendation@1.0.0"],
            ["weather_aware_recommendation@1.0.0"],
        ),
        (
            [
                "weather_aware_recommendation@1.0.0",
                "allergy_safe_recommendation@1.0.0",
                "weather_aware_recommendation@1.0.0",
            ],
            [
                "allergy_safe_recommendation@1.0.0",
                "weather_aware_recommendation@1.0.0",
            ],
        ),
        ([], []),
    ],
)
def test_skill_context_contract_normalizes_single_multiple_and_empty_refs(
    references: list[str],
    expected: list[str],
) -> None:
    payload = _payload(selected_skill_refs=references)

    assert payload.selected_skill_refs == expected
    assert payload.hard_constraints_authoritative is True


def test_skill_context_payload_normalizes_signals_and_serializes_stably() -> None:
    payload = _payload(
        signals=[
            SkillSignal.WEATHER_CONTEXT_REQUIRED,
            SkillSignal.ALLERGY_MENTIONED,
            SkillSignal.WEATHER_CONTEXT_REQUIRED,
        ],
        risk=SkillRisk.HIGH,
    )

    assert payload.signals == [
        SkillSignal.ALLERGY_MENTIONED,
        SkillSignal.WEATHER_CONTEXT_REQUIRED,
    ]
    first = payload.model_dump_json()
    second = payload.model_dump_json()
    assert first == second
    assert json.loads(first)["signals"] == [
        "ALLERGY_MENTIONED",
        "WEATHER_CONTEXT_REQUIRED",
    ]


@pytest.mark.parametrize(
    "reference",
    [
        "missing-version",
        "Invalid_Name@1.0.0",
        "valid_name@latest",
        "@1.0.0",
    ],
)
def test_skill_context_payload_rejects_invalid_skill_refs(reference: str) -> None:
    with pytest.raises(ValidationError, match="Skill reference"):
        _payload(selected_skill_refs=[reference])


def test_skill_context_payload_requires_hard_constraint_authority() -> None:
    with pytest.raises(ValidationError, match="hard_constraints_authoritative"):
        _payload(hard_constraints_authoritative=False)


def test_skill_event_contracts_accept_new_capability_and_artifact_kind() -> None:
    payload = _payload(
        selected_skill_refs=["allergy_safe_recommendation@1.0.0"],
        signals=[SkillSignal.ALLERGY_MENTIONED],
        risk=SkillRisk.HIGH,
        selection_reason="allergy signal matched recommendation route",
    )
    task = AgentTask(
        id="context.skills",
        title="SelectBusinessSkills",
        capability=ExpertCapability.SKILL_SELECTION,
        expected_artifacts=(ArtifactKind.SKILL_CONTEXT,),
    )
    artifact = AgentArtifact(
        id="run-1:context.skills",
        owner="skill_context_agent",
        kind=ArtifactKind.SKILL_CONTEXT,
        payload=payload.model_dump(mode="json"),
        confidence=1.0,
        task_id=task.id,
    )

    assert task.capability is ExpertCapability.SKILL_SELECTION
    assert task.expected_artifacts == (ArtifactKind.SKILL_CONTEXT,)
    assert artifact.kind is ArtifactKind.SKILL_CONTEXT
    assert artifact.payload["selected_skill_refs"] == (
        "allergy_safe_recommendation@1.0.0",
    )


def test_existing_artifact_contract_remains_compatible() -> None:
    artifact = AgentArtifact(
        id="run-1:knowledge",
        owner="knowledge",
        kind=ArtifactKind("RECIPE_EVIDENCE"),
        payload={"items": [{"recipe_id": "recipe-1"}]},
        confidence=0.8,
        task_id="knowledge.retrieve",
    )

    assert artifact.kind is ArtifactKind.RECIPE_EVIDENCE
    assert artifact.payload["items"][0]["recipe_id"] == "recipe-1"
