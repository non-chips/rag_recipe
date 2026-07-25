from __future__ import annotations

from dataclasses import dataclass, field, replace

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.coordinator import (
    CollaborativeRecipeCoordinator,
    CoordinationStatus,
    CoordinatorLimits,
)
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ClaimDecision,
    EventType,
    ExpertCapability,
    TaskStatus,
    thaw_value,
)
from recipe_assistant.agents.quality import GuardrailAgent, ResponseAgent
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType


def _board() -> CollaborationBlackboard:
    return CollaborationBlackboard(
        run_id="quality-run",
        user_id=1,
        session_id="quality-session",
        user_input="recommend dinner",
        route=RouteDecision(
            route=RouteType.RECIPE_RECOMMENDATION,
            confidence=1.0,
            reason="test",
        ),
    )


def _candidate(
    *,
    recipe_id: str = "peanut-noodles",
    ingredients: tuple[str, ...] = ("noodles", "peanut"),
    source_path: str = "recipes/peanut-noodles.md",
    evidence: str = "Cook noodles and mix with peanut sauce.",
) -> dict:
    return {
        "recipe_id": recipe_id,
        "recipe_name": "Peanut noodles",
        "ingredients": ingredients,
        "tools": ("pot",),
        "cook_time_minutes": 15,
        "source_path": source_path,
        "evidence": evidence,
    }


def _review_board(
    *,
    proposal_payload: dict,
    allergens: tuple[str, ...] = (),
) -> tuple[CollaborationBlackboard, AgentTask]:
    board = _board()
    tasks = (
        AgentTask(
            id="recommendation.extract_constraints",
            title="constraints",
            capability=ExpertCapability.RECIPE_RECOMMENDATION,
            status=TaskStatus.SUCCEEDED,
        ),
        AgentTask(
            id="recommendation.preferences",
            title="preferences",
            capability=ExpertCapability.RECIPE_RECOMMENDATION,
            status=TaskStatus.SUCCEEDED,
        ),
        AgentTask(
            id="recommendation.validate",
            title="validation",
            capability=ExpertCapability.RECIPE_RECOMMENDATION,
            status=TaskStatus.SUCCEEDED,
        ),
        AgentTask(
            id="quality.proposal.0",
            title="proposal",
            capability=ExpertCapability.RESPONSE_GENERATION,
            status=TaskStatus.SUCCEEDED,
        ),
    )
    for task in tasks:
        board = board.add_task(task)
    candidate = _candidate()
    artifacts = (
        AgentArtifact(
            id="constraints",
            owner="test",
            kind=ArtifactKind.QUERY_CONSTRAINTS,
            payload={},
            confidence=1.0,
            task_id="recommendation.extract_constraints",
        ),
        AgentArtifact(
            id="preferences",
            owner="test",
            kind=ArtifactKind.USER_PREFERENCE_CONTEXT,
            payload={"allergens": allergens},
            confidence=1.0,
            task_id="recommendation.preferences",
        ),
        AgentArtifact(
            id="validation",
            owner="test",
            kind=ArtifactKind.CONSTRAINT_VALIDATION,
            payload={
                "accepted": (candidate,),
                "rejected": (),
                "hard_constraints_applied": (),
            },
            confidence=1.0,
            task_id="recommendation.validate",
        ),
        AgentArtifact(
            id="proposal",
            owner="response_agent",
            kind=ArtifactKind.RESPONSE_PROPOSAL,
            payload=proposal_payload,
            confidence=1.0,
            task_id="quality.proposal.0",
        ),
    )
    for artifact in artifacts:
        board = board.add_artifact(artifact)
    review_task = AgentTask(
        id="quality.review.0",
        title="review",
        capability=ExpertCapability.QUALITY_REVIEW,
        status=TaskStatus.OPEN,
        metadata={
            "proposal_task_id": "quality.proposal.0",
            "constraints_task_id": "recommendation.extract_constraints",
            "preferences_task_id": "recommendation.preferences",
            "validation_task_id": "recommendation.validate",
        },
    )
    return board, review_task


def test_allergen_conflict_is_deterministically_rejected() -> None:
    candidate = _candidate()
    board, task = _review_board(
        proposal_payload={
            "message": "Try peanut noodles.",
            "answer_mode": "constraint_checked_recommendation",
            "candidates": (candidate,),
        },
        allergens=("peanut",),
    )

    critique = GuardrailAgent().execute(task, board)

    assert critique.kind is ArtifactKind.CRITIQUE
    assert critique.payload["approved"] is False
    assert "allergen_conflict" in critique.payload["violations"]
    assert critique.payload["rejected_candidate_ids"] == ("peanut-noodles",)


def test_specific_recipe_facts_without_evidence_are_rejected() -> None:
    board, task = _review_board(
        proposal_payload={
            "message": "This recipe has specific preparation facts.",
            "answer_mode": "evidence_grounded_recipe_knowledge",
            "candidates": (),
            "evidence": (),
        }
    )

    critique = GuardrailAgent().execute(task, board)

    assert critique.kind is ArtifactKind.CRITIQUE
    assert "missing_retrieval_evidence" in critique.payload["violations"]


def test_recipe_absence_claim_conflicting_with_evidence_is_rejected() -> None:
    candidate = {
        **_candidate(recipe_id="kou-shui-ji"),
        "recipe_name": "口水鸡",
        "source_path": "recipes/口水鸡.md",
        "evidence": "口水鸡是一道适合夏天的凉菜。",
    }
    board, task = _review_board(
        proposal_payload={
            "message": "目前的食谱中不包含“口水鸡”的详细做法。",
            "answer_mode": "evidence_grounded_recipe_knowledge",
            "candidates": (candidate,),
            "evidence": (
                {
                    "recipe_id": "kou-shui-ji",
                    "recipe_name": "口水鸡",
                    "source_path": "recipes/口水鸡.md",
                    "content": "口水鸡是一道适合夏天的凉菜。",
                },
            ),
        }
    )

    critique = GuardrailAgent().execute(task, board)

    assert critique.kind is ArtifactKind.CRITIQUE
    assert "contradictory_missing_recipe_claim" in critique.payload["violations"]


def test_unverified_recording_claim_is_rejected() -> None:
    board, task = _review_board(
        proposal_payload={
            "message": "好的，已为您记录凉拌豆腐。",
            "answer_mode": "evidence_grounded_recipe_knowledge",
            "candidates": (),
            "evidence": (
                {
                    "recipe_id": "cold-tofu",
                    "recipe_name": "凉拌豆腐",
                    "source_path": "recipes/凉拌豆腐.md",
                    "content": "凉拌豆腐的食谱内容。",
                },
            ),
        }
    )

    critique = GuardrailAgent().execute(task, board)

    assert critique.kind is ArtifactKind.CRITIQUE
    assert "unverified_action_claim" in critique.payload["violations"]


@dataclass
class _RecommendationExpert:
    name: str = "recommendation"
    capabilities: frozenset[ExpertCapability] = frozenset(
        {ExpertCapability.RECIPE_RECOMMENDATION}
    )
    candidate: dict = field(default_factory=_candidate)

    def decide(self, task, board) -> ClaimDecision:
        del board
        return ClaimDecision(
            expert_name=self.name,
            accepted=True,
            confidence=1.0,
            reason=f"execute {task.id}",
        )

    def execute(self, task, board) -> AgentArtifact:
        payloads = {
            "recommendation.extract_constraints": {},
            "recommendation.preferences": {"allergens": ("peanut",)},
            "recommendation.retrieve": {
                "stage": "recalled",
                "candidates": (self.candidate,),
                "warnings": (),
            },
            "recommendation.rank": {
                "stage": "ranked",
                "candidates": (self.candidate,),
                "warnings": (),
            },
            "recommendation.validate": {
                "accepted": (self.candidate,),
                "rejected": (),
                "hard_constraints_applied": (),
            },
            "recommendation.response_plan": {
                "answer_mode": "constraint_checked_recommendation",
                "message": "Try peanut noodles.",
                "candidates": (self.candidate,),
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


def test_rejected_proposal_is_revised_once_then_accepted() -> None:
    outcome = CollaborativeRecipeCoordinator(
        ExpertRegistry([_RecommendationExpert()])
    ).coordinate(_board())

    assert outcome.status is CoordinationStatus.SUCCEEDED
    assert outcome.final_artifact.kind is ArtifactKind.RESPONSE_PROPOSAL
    assert outcome.final_artifact.revision_of.endswith("quality.proposal.0:proposal")
    assert outcome.final_artifact.payload["candidates"] == ()
    assert outcome.final_artifact.payload["response_plan_artifact_id"] in (
        outcome.final_artifact.payload["references"]
    )
    assert outcome.blackboard.tasks["quality.revision.1"].revision_of == (
        "quality.proposal.0"
    )
    assert any(
        event.event_type is EventType.REVISION_REQUESTED
        for event in outcome.blackboard.events
    )
    assert any(
        event.event_type is EventType.FINAL_ACCEPTED
        for event in outcome.blackboard.events
    )


class _StubbornResponseAgent(ResponseAgent):
    def execute(self, task, board) -> AgentArtifact:
        artifact = super().execute(task, board)
        if int(task.metadata.get("revision_number") or 0) == 0:
            return artifact
        plan = board.artifact_for(
            task_id=str(task.metadata["response_plan_task_id"]),
            kind=ArtifactKind.RESPONSE_PLAN,
        )
        assert plan is not None
        payload = thaw_value(artifact.payload)
        payload["candidates"] = tuple(plan.payload.get("candidates", ()))
        return replace(artifact, payload=payload)


def test_revision_exhaustion_degrades_and_queues_bad_case_candidate() -> None:
    outcome = CollaborativeRecipeCoordinator(
        ExpertRegistry([_RecommendationExpert()]),
        limits=CoordinatorLimits(max_revisions=1),
        response_agent=_StubbornResponseAgent(),
    ).coordinate(_board())

    assert outcome.status is CoordinationStatus.DEGRADED
    assert outcome.final_artifact.kind is ArtifactKind.ERROR
    assert not any(
        event.event_type is EventType.FINAL_ACCEPTED
        for event in outcome.blackboard.events
    )
    bad_case = next(
        event
        for event in outcome.blackboard.events
        if event.event_type is EventType.BAD_CASE_CANDIDATE
    )
    assert bad_case.metadata["trigger"] == "QUALITY_REVISIONS_EXHAUSTED"
    assert "allergen_conflict" in bad_case.metadata[
        "hard_constraint_violations"
    ]
