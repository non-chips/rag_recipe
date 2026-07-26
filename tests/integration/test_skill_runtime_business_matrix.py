from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.coordinator import (
    CollaborativeRecipeCoordinator,
    CoordinationStatus,
)
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ClaimDecision,
    EventType,
    ExpertCapability,
)
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.agents.skills import SkillContextAgent
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.services.skills import SkillContextPayload, SkillRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_REGISTRY = SkillRegistry.load(PROJECT_ROOT / "skills")

ALLERGY_REF = "allergy_safe_recommendation@1.0.0"
SUBSTITUTION_REF = "ingredient_substitution@1.0.0"
NUTRITION_REF = "source_aware_nutrition_report@1.0.0"
WEATHER_REF = "weather_aware_recommendation@1.0.0"


@dataclass(frozen=True, slots=True)
class _BusinessCase:
    case_id: str
    route: RouteType
    user_input: str
    expected_refs: tuple[str, ...]
    requires_weather: bool = False
    allergy: bool = False
    substitution: bool = False
    nutrition: bool = False


CASES = (
    _BusinessCase(
        case_id="allergy_recommendation",
        route=RouteType.RECIPE_RECOMMENDATION,
        user_input="我对花生过敏，请推荐一道晚餐。",
        expected_refs=(ALLERGY_REF,),
        allergy=True,
    ),
    _BusinessCase(
        case_id="dairy_substitution",
        route=RouteType.RECIPE_KNOWLEDGE,
        user_input="牛奶可以用豆浆替代吗？",
        expected_refs=(SUBSTITUTION_REF,),
        substitution=True,
    ),
    _BusinessCase(
        case_id="source_nutrition_without_data",
        route=RouteType.NUTRITION_PLANNING,
        user_input="请给我一份带来源的营养报告。",
        expected_refs=(NUTRITION_REF,),
        nutrition=True,
    ),
    _BusinessCase(
        case_id="weather_recommendation",
        route=RouteType.RECIPE_RECOMMENDATION,
        user_input="结合北京当前天气推荐一道菜。",
        expected_refs=(WEATHER_REF,),
        requires_weather=True,
    ),
    _BusinessCase(
        case_id="allergy_and_weather",
        route=RouteType.RECIPE_RECOMMENDATION,
        user_input="我对花生过敏，请结合北京天气推荐。",
        expected_refs=(ALLERGY_REF, WEATHER_REF),
        requires_weather=True,
        allergy=True,
    ),
    _BusinessCase(
        case_id="ordinary_recipe_question",
        route=RouteType.RECIPE_KNOWLEDGE,
        user_input="番茄面怎么做？",
        expected_refs=(),
    ),
    _BusinessCase(
        case_id="complex_artifact_driven",
        route=RouteType.COMPLEX,
        user_input="结合我的饮食记录推荐安全晚餐。",
        expected_refs=(ALLERGY_REF, NUTRITION_REF),
        allergy=True,
        nutrition=True,
    ),
)


def _candidate(recipe_id: str, ingredients: tuple[str, ...]) -> dict:
    return {
        "recipe_id": recipe_id,
        "recipe_name": recipe_id.replace("-", " ").title(),
        "ingredients": ingredients,
        "tools": ("pot",),
        "cook_time_minutes": 20,
        "category": "dinner",
        "weather_tags": ("clear",),
        "source_path": f"recipes/{recipe_id}.md",
        "evidence": f"Verified evidence for {recipe_id}.",
        "retrieval_score": 1.0,
        "ranking_score": 1.0,
        "ranking_features": {"evidence": 1.0},
    }


SAFE_CANDIDATE = _candidate("safe-tofu", ("tofu", "tomato"))
ALLERGEN_CANDIDATE = _candidate("peanut-noodles", ("noodles", "peanut"))
EVIDENCE_ITEM = {
    "recipe_id": "tomato-noodles",
    "recipe_name": "Tomato noodles",
    "content": "Verified tomato noodle steps and ingredients.",
    "source_path": "recipes/tomato-noodles.md",
    "retrieval_sources": ("offline_fixture",),
}


@dataclass
class _OfflineDomainExpert:
    case: _BusinessCase
    name: str = "offline_domain_expert"
    capabilities: frozenset[ExpertCapability] = frozenset(
        {
            ExpertCapability.RECIPE_KNOWLEDGE,
            ExpertCapability.RECIPE_RECOMMENDATION,
            ExpertCapability.NUTRITION_PLANNING,
        }
    )

    def decide(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> ClaimDecision:
        del board
        accepted = task.capability in self.capabilities
        return ClaimDecision(
            expert_name=self.name,
            accepted=accepted,
            confidence=1.0 if accepted else 0.0,
            reason=f"offline domain fixture executes {task.id}" if accepted else "",
        )

    def execute(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        payload = self._payload(task.id)
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}",
            owner=self.name,
            kind=task.expected_artifacts[0],
            payload=payload,
            confidence=1.0,
            task_id=task.id,
        )

    def _payload(self, task_id: str) -> dict:
        topics = ("substitution",) if self.case.substitution else ("general",)
        recommendation_candidates = (
            (SAFE_CANDIDATE, ALLERGEN_CANDIDATE)
            if self.case.allergy
            else (SAFE_CANDIDATE,)
        )
        rejected = (
            (
                {
                    "candidate": ALLERGEN_CANDIDATE,
                    "reasons": ("allergen_conflict",),
                },
            )
            if self.case.allergy
            else ()
        )
        hard_constraints = ("data_source", "allergens") if self.case.allergy else (
            "data_source",
        )
        payloads = {
            "knowledge.extract_constraints": {
                "query": self.case.user_input,
                "topics": topics,
                "recipe_names": (),
                "include_ingredients": (),
                "exclude_ingredients": (),
                "tools": (),
            },
            "knowledge.retrieve": {
                "query": self.case.user_input,
                "items": (EVIDENCE_ITEM,),
                "retrieval_confidence": 1.0,
                "warnings": (),
                "sufficient": True,
                "degraded": False,
            },
            "knowledge.evidence_check": {
                "sufficient": True,
                "evidence_count": 1,
                "covered_topics": topics,
                "missing_topics": (),
                "warnings": (),
            },
            "knowledge.response_plan": {
                "answer_mode": "evidence_grounded_recipe_knowledge",
                "message": (
                    "可以说明替代会改变口感，但来源没有提供精确替代比例。"
                    if self.case.substitution
                    else "仅依据已验证食谱证据回答。"
                ),
                "topics": topics,
                "evidence": (EVIDENCE_ITEM,),
                "source_paths": ("recipes/tomato-noodles.md",),
                "grounded_only": True,
                "degraded": False,
            },
            "recommendation.extract_constraints": {
                "available_ingredients": (),
                "excluded_ingredients": (),
                "available_tools": (),
                "max_time_minutes": None,
                "city": "北京" if self.case.requires_weather else "",
            },
            "recommendation.weather": {
                "available": True,
                "city": "北京",
                "condition": "晴",
                "temperature_c": "26",
                "humidity_percent": "45",
                "warning": "",
            },
            "recommendation.preferences": {
                "preferred_cuisines": (),
                "disliked_ingredients": (),
                "allergens": ("peanut",) if self.case.allergy else (),
            },
            "recommendation.retrieve": {
                "stage": "recalled",
                "candidates": recommendation_candidates,
                "warnings": (),
            },
            "recommendation.rank": {
                "stage": "ranked",
                "candidates": recommendation_candidates,
                "warnings": (),
            },
            "recommendation.validate": {
                "accepted": (SAFE_CANDIDATE,),
                "rejected": rejected,
                "hard_constraints_applied": hard_constraints,
            },
            "recommendation.response_plan": {
                "answer_mode": "constraint_checked_recommendation",
                "candidates": (SAFE_CANDIDATE,),
                "rejected_count": len(rejected),
                "hard_constraints_applied": hard_constraints,
                "weather": (
                    {
                        "available": True,
                        "city": "北京",
                        "condition": "晴",
                        "temperature_c": "26",
                        "humidity_percent": "45",
                        "warning": "",
                    }
                    if self.case.requires_weather
                    else None
                ),
                "message": "仅使用已验证候选和实际天气 Artifact。",
                "grounded_only": True,
                "degraded": False,
            },
            "nutrition.meal_history": {
                "user_id": 1,
                "records": (),
                "included_event_types": ("CONSUME",),
                "start_at": None,
                "end_at": None,
            },
            "nutrition.summary": self._nutrition_summary(),
            "nutrition.guidance": self._nutrition_goal(),
            "nutrition.response_plan": {
                "answer_mode": "food_category_diversity_only",
                "report_id": "offline-report",
                "message": "没有已确认饮食数据，因此不提供精确营养结论。",
                "precise_metrics_available": False,
                "medical_advice": False,
                "degraded": True,
            },
            "complex.nutrition_goal": self._nutrition_goal(),
            "complex.recipe_candidates": {
                "stage": "ranked",
                "candidates": recommendation_candidates,
                "warnings": (),
            },
            "complex.recipe_evidence": {
                "query": self.case.user_input,
                "items": (EVIDENCE_ITEM,),
                "retrieval_confidence": 1.0,
                "warnings": (),
                "sufficient": True,
                "degraded": False,
            },
            "complex.validate": {
                "accepted": (SAFE_CANDIDATE,),
                "rejected": rejected,
                "hard_constraints_applied": hard_constraints,
            },
            "complex.response_plan": {
                "answer_mode": "constraint_checked_multi_expert_recommendation",
                "candidates": (SAFE_CANDIDATE,),
                "rejected_count": len(rejected),
                "hard_constraints_applied": hard_constraints,
                "message": "依据营养目标和安全校验后的候选回答。",
                "grounded_only": True,
                "degraded": False,
            },
        }
        return payloads[task_id]

    @staticmethod
    def _nutrition_summary() -> dict:
        return {
            "confirmed_meal_count": 0,
            "distinct_recipe_count": 0,
            "data_coverage": 0.0,
            "metrics": {},
            "food_category_distribution": {},
            "precise_metrics_available": False,
            "limitations": ("no confirmed meals",),
            "calculation_version": "offline-v1",
        }

    @staticmethod
    def _nutrition_goal() -> dict:
        return {
            "mode": "food_category_diversity_only",
            "food_categories_to_vary": (),
            "target_recipe_diversity": 0,
            "guidance": ("confirm meals before precise analysis",),
            "based_on_confirmed_meals": 0,
            "medical_advice": False,
        }


def _run(case: _BusinessCase):
    coordinator = CollaborativeRecipeCoordinator(
        ExpertRegistry(
            [
                _OfflineDomainExpert(case),
                SkillContextAgent(SKILL_REGISTRY),
            ]
        )
    )
    board = CollaborationBlackboard(
        run_id=f"skill-matrix-{case.case_id}",
        user_id=1,
        session_id=f"skill-matrix-{case.case_id}",
        user_input=case.user_input,
        route=RouteDecision(
            route=case.route,
            confidence=1.0,
            reason="offline Skill integration matrix",
            requires_weather=case.requires_weather,
        ),
    )
    return coordinator.coordinate(board)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_skill_runtime_business_matrix(case: _BusinessCase) -> None:
    outcome = _run(case)
    board = outcome.blackboard
    skill_artifact = board.artifact_for(
        task_id="context.skills",
        kind=ArtifactKind.SKILL_CONTEXT,
    )
    assert skill_artifact is not None
    skill_context = SkillContextPayload.model_validate(skill_artifact.payload)

    assert outcome.status is CoordinationStatus.SUCCEEDED
    assert skill_context.selected_skill_refs == list(case.expected_refs)
    assert outcome.final_artifact.metadata["selected_skill_refs"] == (
        case.expected_refs
    )
    assert skill_artifact.id in outcome.final_artifact.payload["references"]
    assert board.artifacts_for(kind=ArtifactKind.REVIEW)[-1].payload[
        "approved"
    ] is True
    assert outcome.steps_used <= 14
    assert outcome.budget_used <= 14
    assert not any(
        event.event_type in {
            EventType.BUDGET_EXHAUSTED,
            EventType.ROUND_LIMIT_REACHED,
        }
        for event in board.events
    )

    final_candidates = tuple(
        outcome.final_artifact.payload.get("candidates", ())
    )
    if case.allergy:
        assert {
            str(candidate.get("recipe_id")) for candidate in final_candidates
        } == {"safe-tofu"}
        assert all(
            "peanut" not in candidate.get("ingredients", ())
            for candidate in final_candidates
        )
    if case.substitution:
        assert "1:1" not in str(outcome.final_artifact.payload["message"])
        assert "1 比 1" not in str(outcome.final_artifact.payload["message"])
    if case.nutrition:
        assert "不提供精确营养结论" in str(
            outcome.final_artifact.payload["message"]
        ) or case.route is RouteType.COMPLEX
    if case.requires_weather:
        weather = board.artifact_for(
            task_id="recommendation.weather",
            kind=ArtifactKind.WEATHER_CONTEXT,
        )
        assert weather is not None
        assert weather.payload["available"] is True
        assert weather.payload["city"] == "北京"
        assert weather.id in outcome.final_artifact.payload["references"]

    skill_event = next(
        event
        for event in board.events
        if event.event_type is EventType.ARTIFACT_ADDED
        and event.task_id == "context.skills"
    )
    assert len(str(skill_event.metadata["skill_context_hash"])) == 64
    assert "prompt_context" not in skill_event.metadata


def test_skill_runtime_matrix_covers_all_four_skills_and_empty_selection() -> None:
    covered = {
        reference
        for case in CASES
        for reference in case.expected_refs
    }

    assert covered == {
        ALLERGY_REF,
        SUBSTITUTION_REF,
        NUTRITION_REF,
        WEATHER_REF,
    }
    assert any(not case.expected_refs for case in CASES)
