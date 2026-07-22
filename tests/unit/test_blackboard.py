from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentEvent,
    AgentTask,
    ArtifactKind,
    EventType,
    ExpertCapability,
    TaskStatus,
)
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType


def _board() -> CollaborationBlackboard:
    return CollaborationBlackboard(
        run_id="run-1",
        user_id=1,
        session_id="session-1",
        user_input="宫保鸡丁怎么做",
        route=RouteDecision(
            route=RouteType.RECIPE_KNOWLEDGE,
            confidence=0.9,
            reason="knowledge",
        ),
    )


def _task() -> AgentTask:
    return AgentTask(
        id="knowledge.retrieve",
        title="RetrieveRecipeKnowledge",
        capability=ExpertCapability.RECIPE_KNOWLEDGE,
        expected_artifacts=(ArtifactKind.RECIPE_EVIDENCE,),
    )


def test_blackboard_updates_return_new_append_only_objects() -> None:
    original = _board()
    with_task = original.add_task(_task())
    running = with_task.with_task_status(_task().id, TaskStatus.RUNNING)

    payload = {"recipes": [{"recipe_id": "recipe-1"}]}
    artifact = AgentArtifact(
        id="artifact-1",
        owner="knowledge",
        kind=ArtifactKind.RECIPE_EVIDENCE,
        payload=payload,
        confidence=0.8,
        task_id=_task().id,
    )
    with_artifact = running.add_artifact(artifact)
    with_event = with_artifact.append_event(
        AgentEvent(
            event_type=EventType.ARTIFACT_ADDED,
            actor="knowledge",
            task_id=_task().id,
            artifact_id=artifact.id,
        )
    )

    payload["recipes"][0]["recipe_id"] = "mutated"
    assert original.tasks == {}
    assert with_task.artifacts == ()
    assert with_artifact.events == with_task.events
    assert artifact.payload["recipes"][0]["recipe_id"] == "recipe-1"
    with pytest.raises(TypeError):
        artifact.payload["new"] = "forbidden"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        artifact.owner = "other"  # type: ignore[misc]
    assert [event.sequence for event in with_event.events] == [1, 2]


def test_duplicate_ids_and_invalid_final_reference_are_rejected() -> None:
    board = _board().add_task(_task())
    artifact = AgentArtifact(
        id="artifact-1",
        owner="knowledge",
        kind=ArtifactKind.RESPONSE_PLAN,
        payload={"answer": "plan"},
        confidence=0.9,
        task_id=_task().id,
    )
    board = board.add_artifact(artifact)

    with pytest.raises(ValueError, match="already exists"):
        board.add_task(_task())
    with pytest.raises(ValueError, match="already exists"):
        board.add_artifact(artifact)
    with pytest.raises(ValueError, match="does not exist"):
        board.select_final("missing")

    selected = board.select_final(artifact.id)
    assert selected.final_artifact_id == artifact.id
    assert selected.events[-1].event_type is EventType.FINAL_SELECTED
    with pytest.raises(ValueError, match="already been selected"):
        selected.select_final(artifact.id)


def test_route_and_event_metadata_are_immutable_and_traceable() -> None:
    metadata = {"nested": {"items": [1, 2]}}
    board = _board().append_event(
        AgentEvent(event_type=EventType.DEGRADED, actor="coordinator", metadata=metadata)
    )
    metadata["nested"]["items"].append(3)

    with pytest.raises(TypeError):
        board.events[0].metadata["x"] = 1  # type: ignore[index]
    with pytest.raises(ValidationError):
        board.route.confidence = 0.1
    trace = board.trace_events()[0]
    assert trace["sequence"] == 1
    assert trace["metadata"] == {"nested": {"items": [1, 2]}}
