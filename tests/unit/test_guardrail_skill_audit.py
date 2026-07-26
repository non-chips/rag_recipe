from __future__ import annotations

import pytest

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ExpertCapability,
    TaskStatus,
)
from recipe_assistant.agents.quality import GuardrailAgent
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType


SELECTED_REFS = (
    "allergy_safe_recommendation@1.0.0",
    "weather_aware_recommendation@1.0.0",
)


def _candidate(recipe_id: str = "safe-recipe") -> dict:
    return {
        "recipe_id": recipe_id,
        "recipe_name": "Safe recipe",
        "ingredients": ("tofu",),
        "tools": ("pot",),
        "cook_time_minutes": 15,
        "source_path": "recipes/safe.md",
        "evidence": "Verified recipe evidence.",
    }


def _review_fixture(
    *,
    artifact_refs: tuple[str, ...] = SELECTED_REFS,
    proposal_refs: tuple[str, ...] | None = None,
    authority: bool = True,
    references_skill: bool = True,
    message: str = "Use the validated plan.",
    candidates: tuple[dict, ...] = (),
    include_skill: bool = True,
    critique_rejected_ids: tuple[str, ...] = (),
) -> tuple[CollaborationBlackboard, AgentTask]:
    board = CollaborationBlackboard(
        run_id="guardrail-skill-run",
        user_id=1,
        session_id="guardrail-skill-session",
        user_input="test",
        route=RouteDecision(
            route=RouteType.RECIPE_RECOMMENDATION,
            confidence=1.0,
            reason="test",
        ),
    )
    skill_task = AgentTask(
        id="context.skills",
        title="SelectSkillContext",
        capability=ExpertCapability.SKILL_SELECTION,
        status=TaskStatus.SUCCEEDED,
        expected_artifacts=(ArtifactKind.SKILL_CONTEXT,),
    )
    response_plan_task = AgentTask(
        id="recommendation.response_plan",
        title="BuildResponsePlan",
        capability=ExpertCapability.RECIPE_RECOMMENDATION,
        status=TaskStatus.SUCCEEDED,
        expected_artifacts=(ArtifactKind.RESPONSE_PLAN,),
    )
    proposal_task = AgentTask(
        id="quality.proposal.0",
        title="BuildResponseProposal",
        capability=ExpertCapability.RESPONSE_GENERATION,
        status=TaskStatus.SUCCEEDED,
        expected_artifacts=(ArtifactKind.RESPONSE_PROPOSAL,),
        metadata=(
            {"critique_task_id": "quality.review.previous"}
            if critique_rejected_ids
            else {}
        ),
    )
    board = (
        board.add_task(response_plan_task)
        .add_task(skill_task)
        .add_task(proposal_task)
    )
    board = board.add_artifact(
        AgentArtifact(
            id="response-plan",
            owner="domain",
            kind=ArtifactKind.RESPONSE_PLAN,
            payload={"message": "Use the validated plan."},
            confidence=1.0,
            task_id=response_plan_task.id,
        )
    )
    if include_skill:
        board = board.add_artifact(
            AgentArtifact(
                id="skill-context-artifact",
                owner="skill_context_agent",
                kind=ArtifactKind.SKILL_CONTEXT,
                payload={
                    "selected_skill_refs": artifact_refs,
                    "signals": (),
                    "risk": "LOW",
                    "prompt_context": "VALIDATED-SKILL-PROMPT",
                    "selection_reason": "safe reason",
                    "hard_constraints_authoritative": authority,
                },
                confidence=1.0,
                task_id=skill_task.id,
            )
        )
    if critique_rejected_ids:
        critique_task = AgentTask(
            id="quality.review.previous",
            title="PriorReview",
            capability=ExpertCapability.QUALITY_REVIEW,
            status=TaskStatus.SUCCEEDED,
            expected_artifacts=(ArtifactKind.CRITIQUE,),
        )
        board = board.add_task(critique_task)
        board = board.add_artifact(
            AgentArtifact(
                id="prior-critique",
                owner="guardrail_agent",
                kind=ArtifactKind.CRITIQUE,
                payload={
                    "approved": False,
                    "violations": ("allergen_conflict",),
                    "rejected_candidate_ids": critique_rejected_ids,
                },
                confidence=1.0,
                task_id=critique_task.id,
                review_of="prior-proposal",
            )
        )
    references = ["response-plan"]
    if references_skill:
        references.append("skill-context-artifact")
    board = board.add_artifact(
        AgentArtifact(
            id="proposal",
            owner="response_agent",
            kind=ArtifactKind.RESPONSE_PROPOSAL,
            payload={
                "message": message,
                "answer_mode": "constraint_checked_recommendation",
                "candidates": candidates,
                "evidence": (),
                "references": references,
            },
            confidence=1.0,
            task_id=proposal_task.id,
            metadata={
                "selected_skill_refs": (
                    artifact_refs if proposal_refs is None else proposal_refs
                )
            },
        )
    )
    review_task = AgentTask(
        id="quality.review.0",
        title="ReviewResponseProposal",
        capability=ExpertCapability.QUALITY_REVIEW,
        status=TaskStatus.OPEN,
        metadata={
            "proposal_task_id": proposal_task.id,
            "skill_task_id": skill_task.id,
        },
    )
    return board, review_task


def _violations(board: CollaborationBlackboard, task: AgentTask) -> tuple:
    return GuardrailAgent().execute(task, board).payload["violations"]


def test_guardrail_skill_matching_refs_and_empty_selection_pass() -> None:
    board, task = _review_fixture()
    review = GuardrailAgent().execute(task, board)
    assert review.kind is ArtifactKind.REVIEW
    assert review.payload["selected_skill_refs"] == SELECTED_REFS

    empty_board, empty_task = _review_fixture(
        artifact_refs=(),
        proposal_refs=(),
    )
    empty_review = GuardrailAgent().execute(empty_task, empty_board)
    assert empty_review.kind is ArtifactKind.REVIEW
    assert empty_review.payload["selected_skill_refs"] == ()


@pytest.mark.parametrize(
    ("proposal_refs", "expected"),
    [
        (
            (*SELECTED_REFS, "ingredient_substitution@1.0.0"),
            "skill_refs_mismatch",
        ),
        (tuple(reversed(SELECTED_REFS)), "skill_refs_mismatch"),
        (
            (SELECTED_REFS[0], SELECTED_REFS[0]),
            "proposal_skill_refs_invalid",
        ),
    ],
)
def test_guardrail_skill_added_reordered_or_duplicate_refs_fail(
    proposal_refs: tuple[str, ...],
    expected: str,
) -> None:
    board, task = _review_fixture(proposal_refs=proposal_refs)
    assert expected in _violations(board, task)


@pytest.mark.parametrize(
    "artifact_refs",
    [
        ("not-a-versioned-ref",),
        (SELECTED_REFS[0], SELECTED_REFS[0]),
        tuple(reversed(SELECTED_REFS)),
    ],
)
def test_guardrail_skill_artifact_refs_must_be_canonical(
    artifact_refs: tuple[str, ...],
) -> None:
    board, task = _review_fixture(
        artifact_refs=artifact_refs,
        proposal_refs=artifact_refs,
    )

    assert "skill_refs_invalid" in _violations(board, task)


def test_guardrail_skill_missing_invalid_authority_and_reference_fail() -> None:
    missing_board, missing_task = _review_fixture(include_skill=False)
    assert "skill_context_missing" in _violations(missing_board, missing_task)

    authority_board, authority_task = _review_fixture(authority=False)
    authority_violations = _violations(authority_board, authority_task)
    assert "skill_authority_invalid" in authority_violations
    assert "skill_context_invalid" in authority_violations

    reference_board, reference_task = _review_fixture(references_skill=False)
    assert "skill_artifact_not_referenced" in _violations(
        reference_board,
        reference_task,
    )


def test_guardrail_skill_rejects_restored_candidate() -> None:
    candidate = _candidate("rejected-recipe")
    board, task = _review_fixture(
        candidates=(candidate,),
        critique_rejected_ids=("rejected-recipe",),
    )

    violations = _violations(board, task)

    assert "skill_restored_rejected_candidate" in violations


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("当前实时气温是 31℃。", "unsupported_realtime_weather_claim"),
        ("这餐的热量是 500千卡。", "unsupported_exact_nutrition_claim"),
        ("可以用豆腐替代鸡蛋，按 1 比 2。", "unsupported_substitution_ratio"),
    ],
)
def test_guardrail_skill_rejects_unsupported_exact_facts(
    message: str,
    expected: str,
) -> None:
    board, task = _review_fixture(message=message)
    assert expected in _violations(board, task)


def test_coordinator_review_task_declares_skill_dependency() -> None:
    from recipe_assistant.agents.coordinator import CollaborativeRecipeCoordinator
    from recipe_assistant.agents.registry import ExpertRegistry

    coordinator = CollaborativeRecipeCoordinator(ExpertRegistry())
    board, _ = _review_fixture()
    review_ready = coordinator._derive_quality_work(board)

    assert review_ready.tasks["quality.review.0"].metadata["skill_task_id"] == (
        "context.skills"
    )
