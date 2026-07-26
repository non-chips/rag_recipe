"""Deterministic response proposal and recipe quality review agents."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import ValidationError

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ClaimDecision,
    ExpertCapability,
    TaskStatus,
    thaw_value,
)
from recipe_assistant.services.constraint import (
    ConstraintService,
    PreferenceContext,
    RecipeCandidate,
    TemporaryConstraints,
)
from recipe_assistant.services.skills import SkillContextPayload


class ResponseAgent:
    """Turn one exact response plan into a referenced user-facing proposal."""

    name: ClassVar[str] = "response_agent"
    capabilities: ClassVar[frozenset[ExpertCapability]] = frozenset(
        {ExpertCapability.RESPONSE_GENERATION}
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
            reason=(
                "compose a proposal from declared artifact dependencies"
                if accepted
                else ""
            ),
        )

    def execute(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        plan_task_id = str(task.metadata["response_plan_task_id"])
        plan = board.artifact_for(
            task_id=plan_task_id,
            kind=ArtifactKind.RESPONSE_PLAN,
        )
        if plan is None:
            raise ValueError(
                f"required artifact is missing: {plan_task_id}/RESPONSE_PLAN"
            )
        skill_artifact, skill_context = self._skill_context(board)

        prior_proposal_id = str(task.metadata.get("prior_proposal_id") or "")
        critique_task_id = str(task.metadata.get("critique_task_id") or "")
        rejected_ids: set[str] = set()
        critique_id = ""
        if critique_task_id:
            critique = board.artifact_for(
                task_id=critique_task_id,
                kind=ArtifactKind.CRITIQUE,
            )
            if critique is None:
                raise ValueError(
                    f"required artifact is missing: {critique_task_id}/CRITIQUE"
                )
            critique_id = critique.id
            rejected_ids = {
                str(item)
                for item in critique.payload.get("rejected_candidate_ids", ())
            }

        plan_payload = thaw_value(plan.payload)
        candidates = tuple(
            candidate
            for candidate in plan_payload.get("candidates", ())
            if str(candidate.get("recipe_id") or "") not in rejected_ids
        )
        evidence = tuple(plan_payload.get("evidence", ()))
        revision_number = int(task.metadata.get("revision_number") or 0)
        if revision_number and rejected_ids and not candidates:
            message = (
                "现有候选未能通过食品安全与硬约束审核，"
                "本轮不提供具体菜谱，并建议补充条件后重新检索。"
            )
        else:
            message = str(
                plan_payload.get("message")
                or "已依据当前结构化业务方案生成回答。"
            )

        references = [plan.id, skill_artifact.id]
        for reference in task.metadata.get("artifact_dependencies", ()):
            dependency_task_id = str(reference["task_id"])
            dependency_kind = ArtifactKind(str(reference["kind"]))
            artifact = board.artifact_for(
                task_id=dependency_task_id,
                kind=dependency_kind,
            )
            if artifact is not None:
                references.append(artifact.id)
        if critique_id:
            references.append(critique_id)

        payload: dict[str, Any] = {
            "message": message,
            "answer_mode": plan_payload.get("answer_mode", ""),
            "candidates": candidates,
            "evidence": evidence,
            "references": tuple(dict.fromkeys(references)),
            "response_plan_artifact_id": plan.id,
            "revision_number": revision_number,
            "degraded": bool(plan_payload.get("degraded")) or bool(rejected_ids),
        }
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}:proposal",
            owner=self.name,
            kind=ArtifactKind.RESPONSE_PROPOSAL,
            payload=payload,
            confidence=plan.confidence if not rejected_ids else 0.5,
            task_id=task.id,
            metadata={
                "declared_dependencies_only": True,
                "selected_skill_refs": list(skill_context.selected_skill_refs),
            },
            revision_of=prior_proposal_id,
        )

    @staticmethod
    def _skill_context(
        board: CollaborationBlackboard,
    ) -> tuple[AgentArtifact, SkillContextPayload]:
        artifact = board.artifact_for(
            task_id="context.skills",
            kind=ArtifactKind.SKILL_CONTEXT,
        )
        if artifact is None:
            raise ValueError(
                "required artifact is missing: context.skills/SKILL_CONTEXT"
            )
        return artifact, SkillContextPayload.model_validate(artifact.payload)


class GuardrailAgent:
    """Apply deterministic evidence, constraint and food-safety rules."""

    name: ClassVar[str] = "guardrail_agent"
    capabilities: ClassVar[frozenset[ExpertCapability]] = frozenset(
        {ExpertCapability.QUALITY_REVIEW}
    )
    _UNSAFE_PHRASES = (
        "生吃鸡肉",
        "鸡肉无需加热",
        "raw chicken",
        "undercooked chicken",
        "生吃猪肉",
        "raw pork",
    )
    _MISSING_RECIPE_PHRASES = (
        "不包含",
        "没有找到",
        "未找到",
        "找不到",
        "不存在",
        "没有相关食谱",
        "没有这道菜",
    )
    _UNVERIFIED_ACTION_PATTERN = re.compile(
        r"(?:已|已经)(?:为(?:您|你)|帮(?:您|你)).{0,6}(?:记录|保存|添加)"
        r"|(?:记录|保存|添加)(?:完成|成功|好了)"
    )
    _SKILL_REF_PATTERN = re.compile(
        r"^[a-z][a-z0-9_]{2,63}@"
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
        r"(?:-[0-9A-Za-z.-]+)?$"
    )
    _EXACT_WEATHER_PATTERN = re.compile(
        r"(?:当前|现在|实时|今日|今天).{0,12}"
        r"-?\d{1,2}(?:\.\d+)?\s*(?:°C|℃|度)"
    )
    _EXACT_NUTRITION_PATTERN = re.compile(
        r"(?:热量|蛋白质|脂肪|碳水|钠).{0,8}"
        r"\d+(?:\.\d+)?\s*(?:kcal|千卡|卡路里|mg|毫克|克|g)\b"
        r"|\d+(?:\.\d+)?\s*(?:kcal|千卡|卡路里)\b",
        re.IGNORECASE,
    )
    _EXACT_SUBSTITUTION_PATTERN = re.compile(
        r"(?:替代|替换).{0,16}(?:\d+\s*[:：]\s*\d+|按\s*\d+\s*比\s*\d+)"
    )

    def __init__(self) -> None:
        self.constraint_service = ConstraintService()

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
            reason=(
                "apply deterministic recipe constraints and food-safety rules"
                if accepted
                else ""
            ),
        )

    def execute(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        proposal_task_id = str(task.metadata["proposal_task_id"])
        proposal = board.artifact_for(
            task_id=proposal_task_id,
            kind=ArtifactKind.RESPONSE_PROPOSAL,
        )
        if proposal is None:
            raise ValueError(
                f"required artifact is missing: {proposal_task_id}/RESPONSE_PROPOSAL"
            )

        violations: list[str] = []
        rejected_ids: set[str] = set()
        skill_task_id = str(task.metadata.get("skill_task_id") or "context.skills")
        skill_artifact = board.artifact_for(
            task_id=skill_task_id,
            kind=ArtifactKind.SKILL_CONTEXT,
        )
        skill_context: SkillContextPayload | None = None
        if skill_artifact is None:
            violations.append("skill_context_missing")
        else:
            raw_refs = tuple(
                str(item)
                for item in skill_artifact.payload.get(
                    "selected_skill_refs",
                    (),
                )
            )
            if (
                skill_artifact.payload.get("hard_constraints_authoritative")
                is not True
            ):
                violations.append("skill_authority_invalid")
            try:
                skill_context = SkillContextPayload.model_validate(
                    skill_artifact.payload
                )
            except ValidationError:
                violations.append("skill_context_invalid")
            if (
                len(raw_refs) != len(set(raw_refs))
                or any(
                    self._SKILL_REF_PATTERN.fullmatch(reference) is None
                    for reference in raw_refs
                )
                or (
                    skill_context is not None
                    and raw_refs
                    != tuple(skill_context.selected_skill_refs)
                )
            ):
                violations.append("skill_refs_invalid")

            proposal_refs = tuple(
                str(item)
                for item in proposal.metadata.get(
                    "selected_skill_refs",
                    (),
                )
            )
            expected_refs = (
                tuple(skill_context.selected_skill_refs)
                if skill_context is not None
                else raw_refs
            )
            if (
                len(proposal_refs) != len(set(proposal_refs))
                or any(
                    self._SKILL_REF_PATTERN.fullmatch(reference) is None
                    for reference in proposal_refs
                )
            ):
                violations.append("proposal_skill_refs_invalid")
            if proposal_refs != expected_refs:
                violations.append("skill_refs_mismatch")
            if skill_artifact.id not in tuple(
                str(item)
                for item in proposal.payload.get("references", ())
            ):
                violations.append("skill_artifact_not_referenced")

        constraints = self._optional_model(
            board,
            task,
            "constraints_task_id",
            ArtifactKind.QUERY_CONSTRAINTS,
            TemporaryConstraints,
        )
        preferences = self._optional_model(
            board,
            task,
            "preferences_task_id",
            ArtifactKind.USER_PREFERENCE_CONTEXT,
            PreferenceContext,
        )
        candidates = tuple(
            RecipeCandidate.model_validate(item)
            for item in proposal.payload.get("candidates", ())
        )

        proposal_task = board.tasks.get(proposal.task_id)
        critique_task_id = (
            str(proposal_task.metadata.get("critique_task_id") or "")
            if proposal_task is not None
            else ""
        )
        if critique_task_id:
            prior_critique = board.artifact_for(
                task_id=critique_task_id,
                kind=ArtifactKind.CRITIQUE,
            )
            if prior_critique is not None:
                prior_rejected = {
                    str(item)
                    for item in prior_critique.payload.get(
                        "rejected_candidate_ids",
                        (),
                    )
                }
                restored = {
                    candidate.recipe_id for candidate in candidates
                } & prior_rejected
                if restored:
                    rejected_ids.update(restored)
                    violations.append("skill_restored_rejected_candidate")

        if candidates:
            validation = self.constraint_service.validate(
                candidates,
                constraints or TemporaryConstraints(),
                preferences or PreferenceContext(),
            )
            for rejected in validation.rejected:
                rejected_ids.add(rejected.candidate.recipe_id)
                violations.extend(rejected.reasons)
            available = {
                item.strip().casefold()
                for item in (constraints.available_ingredients if constraints else ())
                if item.strip()
            }
            if available:
                for candidate in candidates:
                    ingredients = {
                        item.strip().casefold()
                        for item in candidate.ingredients
                        if item.strip()
                    }
                    if ingredients and not ingredients.issubset(available):
                        rejected_ids.add(candidate.recipe_id)
                        violations.append("unavailable_ingredient")
            validation_task_id = str(
                task.metadata.get("validation_task_id") or ""
            )
            if validation_task_id:
                validation_artifact = board.artifact_for(
                    task_id=validation_task_id,
                    kind=ArtifactKind.CONSTRAINT_VALIDATION,
                )
                if validation_artifact is not None:
                    validated_ids = {
                        str(item.get("recipe_id") or "")
                        for item in validation_artifact.payload.get("accepted", ())
                    }
                    for candidate in candidates:
                        if candidate.recipe_id not in validated_ids:
                            rejected_ids.add(candidate.recipe_id)
                            violations.append("not_constraint_validated")

        answer_mode = str(proposal.payload.get("answer_mode") or "")
        evidence = tuple(proposal.payload.get("evidence", ()))
        if "evidence_grounded" in answer_mode:
            grounded = bool(evidence) and all(
                str(item.get("source_path") or "")
                and str(item.get("content") or item.get("evidence") or "")
                for item in evidence
            )
            if not grounded:
                violations.append("missing_retrieval_evidence")

        review_text = " ".join(
            [
                str(proposal.payload.get("message") or ""),
                *[
                    str(candidate.evidence or "")
                    for candidate in candidates
                ],
            ]
        ).casefold()
        if any(phrase.casefold() in review_text for phrase in self._UNSAFE_PHRASES):
            violations.append("food_safety_conflict")
            rejected_ids.update(candidate.recipe_id for candidate in candidates)

        message = str(proposal.payload.get("message") or "")
        if (
            not self._has_succeeded_artifact(
                board,
                ArtifactKind.WEATHER_CONTEXT,
            )
            and self._EXACT_WEATHER_PATTERN.search(message)
        ):
            violations.append("unsupported_realtime_weather_claim")
        if (
            not self._has_succeeded_artifact(
                board,
                ArtifactKind.NUTRITION_SUMMARY,
                ArtifactKind.NUTRITION_GOAL,
            )
            and self._EXACT_NUTRITION_PATTERN.search(message)
        ):
            violations.append("unsupported_exact_nutrition_claim")
        if self._EXACT_SUBSTITUTION_PATTERN.search(message):
            violations.append("unsupported_substitution_ratio")

        supported_recipe_names = {
            str(item.get("recipe_name") or "").strip()
            for item in evidence
            if str(item.get("source_path") or "").strip()
            and str(item.get("content") or item.get("evidence") or "").strip()
        }
        supported_recipe_names.update(
            candidate.recipe_name.strip()
            for candidate in candidates
            if candidate.recipe_name.strip()
            and candidate.source_path.strip()
            and candidate.evidence.strip()
        )
        if any(phrase in message for phrase in self._MISSING_RECIPE_PHRASES) and any(
            recipe_name in message
            for recipe_name in supported_recipe_names
            if recipe_name
        ):
            violations.append("contradictory_missing_recipe_claim")

        action_confirmed = any(
            bool(
                artifact.payload.get("action_confirmed")
                or artifact.payload.get("write_receipt")
                or artifact.payload.get("interaction_id")
            )
            for artifact in board.artifacts
        )
        if (
            self._UNVERIFIED_ACTION_PATTERN.search(message)
            and not action_confirmed
        ):
            violations.append("unverified_action_claim")

        violations = list(dict.fromkeys(violations))
        approved = not violations
        kind = ArtifactKind.REVIEW if approved else ArtifactKind.CRITIQUE
        payload = {
            "approved": approved,
            "proposal_artifact_id": proposal.id,
            "violations": tuple(violations),
            "rejected_candidate_ids": tuple(sorted(rejected_ids)),
            "rules": (
                "allergens",
                "disliked_ingredients",
                "available_ingredients",
                "available_tools",
                "max_time_minutes",
                "retrieval_evidence",
                "food_safety",
                "recipe_existence_consistency",
                "action_receipt_required",
                "skill_refs_match",
                "skill_authority",
                "skill_artifact_reference",
                "no_rejected_candidate_restoration",
                "structured_weather_basis",
                "structured_nutrition_basis",
                "structured_substitution_basis",
            ),
            "selected_skill_refs": (
                tuple(skill_context.selected_skill_refs)
                if skill_context is not None
                else ()
            ),
        }
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}:{kind.value.lower()}",
            owner=self.name,
            kind=kind,
            payload=payload,
            confidence=1.0,
            task_id=task.id,
            review_of=proposal.id,
        )

    @staticmethod
    def _optional_model(
        board: CollaborationBlackboard,
        task: AgentTask,
        metadata_key: str,
        kind: ArtifactKind,
        schema: type[TemporaryConstraints] | type[PreferenceContext],
    ) -> TemporaryConstraints | PreferenceContext | None:
        task_id = str(task.metadata.get(metadata_key) or "")
        if not task_id:
            return None
        artifact = board.artifact_for(task_id=task_id, kind=kind)
        if artifact is None:
            return None
        return schema.model_validate(artifact.payload)

    @staticmethod
    def _has_succeeded_artifact(
        board: CollaborationBlackboard,
        *kinds: ArtifactKind,
    ) -> bool:
        return any(
            artifact.kind in kinds
            and artifact.task_id in board.tasks
            and board.tasks[artifact.task_id].status is TaskStatus.SUCCEEDED
            for artifact in board.artifacts
        )
