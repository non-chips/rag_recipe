"""Deterministic business-signal extraction from trusted blackboard state."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import AgentArtifact, ArtifactKind, TaskStatus
from recipe_assistant.agents.experts.recipe_knowledge import (
    KnowledgeConstraints,
    KnowledgeTopic,
)
from recipe_assistant.schemas.agent.route import RouteType
from recipe_assistant.schemas.nutrition import NutritionGoal, NutritionSummary
from recipe_assistant.services.constraint import (
    ConstraintValidationResult,
    PreferenceContext,
    TemporaryConstraints,
)
from recipe_assistant.services.skills import SkillSignal
from recipe_assistant.services.weather import WeatherContext


_PayloadModel = TypeVar("_PayloadModel", bound=BaseModel)
_SUBSTITUTION_PATTERNS = (
    re.compile(
        r"(?:食材|原料|调料|配料).{0,12}(?:替代|代替|替换)"
        r"|(?:替代|代替|替换).{0,12}(?:食材|原料|调料|配料)"
    ),
    re.compile(
        r"[\u4e00-\u9fffA-Za-z]{1,12}"
        r"(?:可以|能|能否|能不能|可不可以)?用"
        r"[\u4e00-\u9fffA-Za-z]{1,12}(?:替代|代替)"
    ),
    re.compile(
        r"(?:把)?[\u4e00-\u9fffA-Za-z]{1,12}"
        r"(?:换成|替换成|改用)"
        r"[\u4e00-\u9fffA-Za-z]{1,12}"
    ),
    re.compile(
        r"没有[\u4e00-\u9fffA-Za-z]{1,12}"
        r".{0,8}(?:什么|哪种|[\u4e00-\u9fffA-Za-z]{1,12})"
        r"(?:替代|代替)"
    ),
)


class SkillSignalExtractor:
    """Extract reproducible Skill signals without loading Skills or calling an LLM."""

    def extract(
        self,
        board: CollaborationBlackboard,
    ) -> tuple[SkillSignal, ...]:
        signals: set[SkillSignal] = set()
        artifacts = tuple(self._successful_artifacts(board))

        if self._allergy_mentioned(artifacts):
            signals.add(SkillSignal.ALLERGY_MENTIONED)
        if self._excluded_ingredient_present(board.route.route, artifacts):
            signals.add(SkillSignal.EXCLUDED_INGREDIENT_PRESENT)
        if self._substitution_requested(board.user_input, artifacts):
            signals.add(SkillSignal.SUBSTITUTION_REQUESTED)
        if board.route.requires_weather or self._has_valid_artifact(
            artifacts,
            ArtifactKind.WEATHER_CONTEXT,
            WeatherContext,
        ):
            signals.add(SkillSignal.WEATHER_CONTEXT_REQUIRED)
        if board.route.route in {
            RouteType.NUTRITION_PLANNING,
            RouteType.COMPLEX,
        } and (
            self._has_valid_artifact(
                artifacts,
                ArtifactKind.NUTRITION_SUMMARY,
                NutritionSummary,
            )
            or self._has_valid_artifact(
                artifacts,
                ArtifactKind.NUTRITION_GOAL,
                NutritionGoal,
            )
        ):
            signals.add(SkillSignal.NUTRITION_REPORT_REQUESTED)

        return tuple(sorted(signals, key=lambda signal: signal.value))

    @staticmethod
    def _successful_artifacts(
        board: CollaborationBlackboard,
    ) -> Iterable[AgentArtifact]:
        for artifact in board.artifacts:
            task = board.tasks.get(artifact.task_id)
            if task is not None and task.status is TaskStatus.SUCCEEDED:
                yield artifact

    @classmethod
    def _allergy_mentioned(
        cls,
        artifacts: tuple[AgentArtifact, ...],
    ) -> bool:
        for artifact in artifacts:
            if artifact.kind is ArtifactKind.USER_PREFERENCE_CONTEXT:
                preferences = cls._parse(artifact, PreferenceContext)
                if preferences is not None and preferences.allergens:
                    return True
            elif artifact.kind is ArtifactKind.CONSTRAINT_VALIDATION:
                validation = cls._parse(artifact, ConstraintValidationResult)
                if validation is None:
                    continue
                if "allergens" in validation.hard_constraints_applied:
                    return True
                if cls._has_rejection_reason(validation, "allergen_conflict"):
                    return True
        return False

    @classmethod
    def _excluded_ingredient_present(
        cls,
        route: RouteType,
        artifacts: tuple[AgentArtifact, ...],
    ) -> bool:
        for artifact in artifacts:
            if artifact.kind is ArtifactKind.CONSTRAINT_VALIDATION:
                validation = cls._parse(artifact, ConstraintValidationResult)
                if validation is not None and cls._has_rejection_reason(
                    validation,
                    "excluded_ingredient_conflict",
                ):
                    return True
            if artifact.kind is not ArtifactKind.QUERY_CONSTRAINTS:
                continue
            if route in {RouteType.RECIPE_RECOMMENDATION, RouteType.COMPLEX}:
                constraints = cls._parse(artifact, TemporaryConstraints)
                if constraints is not None and constraints.excluded_ingredients:
                    return True
            if route in {RouteType.RECIPE_KNOWLEDGE, RouteType.COMPLEX}:
                constraints = cls._parse(artifact, KnowledgeConstraints)
                if constraints is not None and constraints.exclude_ingredients:
                    return True
        return False

    @classmethod
    def _substitution_requested(
        cls,
        user_input: str,
        artifacts: tuple[AgentArtifact, ...],
    ) -> bool:
        malformed_query_constraints = False
        for artifact in artifacts:
            if artifact.kind is not ArtifactKind.QUERY_CONSTRAINTS:
                continue
            knowledge = cls._parse(artifact, KnowledgeConstraints)
            recommendation = cls._parse(artifact, TemporaryConstraints)
            if knowledge is None and recommendation is None:
                malformed_query_constraints = True
                continue
            if (
                knowledge is not None
                and KnowledgeTopic.SUBSTITUTION in knowledge.topics
            ):
                return True
        if malformed_query_constraints:
            return False
        return any(pattern.search(user_input) for pattern in _SUBSTITUTION_PATTERNS)

    @staticmethod
    def _has_rejection_reason(
        validation: ConstraintValidationResult,
        reason: str,
    ) -> bool:
        return any(reason in rejected.reasons for rejected in validation.rejected)

    @classmethod
    def _has_valid_artifact(
        cls,
        artifacts: tuple[AgentArtifact, ...],
        kind: ArtifactKind,
        model: type[_PayloadModel],
    ) -> bool:
        return any(
            artifact.kind is kind and cls._parse(artifact, model) is not None
            for artifact in artifacts
        )

    @staticmethod
    def _parse(
        artifact: AgentArtifact,
        model: type[_PayloadModel],
    ) -> _PayloadModel | None:
        try:
            return model.model_validate(artifact.payload)
        except (ValidationError, TypeError, ValueError):
            return None
