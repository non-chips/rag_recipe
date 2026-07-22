"""Constraint-safe recipe recommendation expert."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import Field

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ExpertCapability,
)
from recipe_assistant.agents.experts.base import BaseExpert, ExpertPayload
from recipe_assistant.schemas.retrieval import RetrievalResult
from recipe_assistant.services.constraint import (
    ConstraintService,
    ConstraintValidationResult,
    PreferenceContext,
    RecipeCandidate,
    TemporaryConstraints,
)
from recipe_assistant.services.recommendation import (
    RecommendationRecall,
    RecommendationService,
)
from recipe_assistant.services.weather import WeatherContext
from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.registry import ToolRegistry
from recipe_assistant.tools.schemas import ToolRole


PreferenceProvider = Callable[[int], PreferenceContext]


class CandidateSet(ExpertPayload):
    stage: str
    candidates: tuple[RecipeCandidate, ...] = ()
    warnings: tuple[str, ...] = ()


class RecommendationResponsePlan(ExpertPayload):
    answer_mode: str
    candidates: tuple[RecipeCandidate, ...] = ()
    rejected_count: int = Field(default=0, ge=0)
    hard_constraints_applied: tuple[str, ...] = ()
    weather: WeatherContext | None = None
    message: str
    grounded_only: bool = True
    degraded: bool = False


class RecipeRecommendationExpert(BaseExpert):
    """Recall candidates through tools and enforce hard constraints in services."""

    name: ClassVar[str] = "recipe_recommendation_expert"
    capabilities: ClassVar[frozenset[ExpertCapability]] = frozenset(
        {ExpertCapability.RECIPE_RECOMMENDATION}
    )

    def __init__(
        self,
        tool_registry: ToolRegistry,
        *,
        preference_provider: PreferenceProvider | None = None,
        constraint_service: ConstraintService | None = None,
    ) -> None:
        super().__init__(tool_registry)
        self.preference_provider = preference_provider or (lambda _user_id: PreferenceContext())
        self.constraint_service = constraint_service or ConstraintService()

    def execute(
        self,
        task: AgentTask,
        blackboard: CollaborationBlackboard,
    ) -> AgentArtifact:
        if task.capability not in self.capabilities:
            raise ValueError(f"unsupported capability: {task.capability.value}")
        handlers = {
            "ExtractConstraints": self._extract_constraints,
            "GetWeather": self._get_weather,
            "LoadPreferences": self._load_preferences,
            "RetrieveCandidates": self._retrieve_candidates,
            "RankCandidates": self._rank_candidates,
            "ValidateConstraints": self._validate_constraints,
            "BuildResponsePlan": self._build_response_plan,
        }
        try:
            return handlers[task.title](task, blackboard)
        except KeyError as exc:
            raise ValueError(f"unsupported recommendation task: {task.title}") from exc

    def tool_context(self, blackboard: CollaborationBlackboard) -> ToolContext:
        return ToolContext(
            run_id=blackboard.run_id,
            user_id=blackboard.user_id,
            session_id=blackboard.session_id,
            route=blackboard.route.route.value,
            permissions=frozenset({"user_data:read"}),
        )

    def _extract_constraints(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        payload = self._parse_constraints(board.user_input)
        return self._artifact(task, board, ArtifactKind.QUERY_CONSTRAINTS, payload, 1.0)

    def _get_weather(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        constraints = self._constraints(board)
        if not constraints.city:
            weather = WeatherContext(available=False, warning="本轮请求未提供城市")
            trace_id = ""
        else:
            try:
                invocation = self.tool_registry.invoke(
                    role=ToolRole.RECOMMENDATION_EXPERT,
                    tool_name="get_current_weather",
                    arguments={"city": constraints.city},
                    context=self.tool_context(board),
                )
                weather = WeatherContext.model_validate(invocation.output)
                trace_id = invocation.trace_id
            except Exception as exc:
                weather = WeatherContext(
                    available=False,
                    city=constraints.city,
                    warning=f"天气不可用：{exc}",
                )
                trace_id = ""
        return self._artifact(
            task,
            board,
            ArtifactKind.WEATHER_CONTEXT,
            weather,
            1.0 if weather.available else 0.0,
            degraded=not weather.available,
            trace_id=trace_id,
        )

    def _load_preferences(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        try:
            preferences = PreferenceContext.model_validate(
                self.preference_provider(board.user_id)
            )
            degraded = False
            warning = ""
        except Exception as exc:
            preferences = PreferenceContext()
            degraded = True
            warning = f"偏好读取失败：{exc}"
        return self._artifact(
            task,
            board,
            ArtifactKind.USER_PREFERENCE_CONTEXT,
            preferences,
            0.0 if degraded else 1.0,
            degraded=degraded,
            warning=warning,
        )

    def _retrieve_candidates(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        constraints = self._constraints(board)
        invocation = self.tool_registry.invoke(
            role=ToolRole.RECOMMENDATION_EXPERT,
            tool_name="recommend_recipes",
            arguments={
                "query": board.user_input,
                "constraints": self._constraint_labels(constraints),
                "top_k": 20,
            },
            context=self.tool_context(board),
        )
        recalled = RecommendationRecall.model_validate(invocation.output)
        candidates, supplement_warnings = self._supplement_candidate_evidence(
            recalled.candidates,
            board,
        )
        payload = CandidateSet(
            stage="recalled",
            candidates=candidates,
            warnings=(*recalled.warnings, *supplement_warnings),
        )
        return self._artifact(
            task,
            board,
            ArtifactKind.RECIPE_CANDIDATES,
            payload,
            1.0 if candidates else 0.0,
            degraded=not candidates,
            trace_id=invocation.trace_id,
        )

    def _rank_candidates(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        recalled = self._candidate_set(board, stage="recalled")
        ranked = RecommendationService.rank_candidates(
            recalled.candidates,
            self._constraints(board),
            self._preferences(board),
            self._weather(board),
        )
        payload = CandidateSet(
            stage="ranked",
            candidates=ranked,
            warnings=recalled.warnings,
        )
        return self._artifact(
            task,
            board,
            ArtifactKind.RECIPE_CANDIDATES,
            payload,
            1.0 if ranked else 0.0,
            degraded=not ranked,
        )

    def _validate_constraints(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        ranked = self._candidate_set(board, stage="ranked")
        validation = self.constraint_service.validate(
            ranked.candidates,
            self._constraints(board),
            self._preferences(board),
        )
        return self._artifact(
            task,
            board,
            ArtifactKind.CONSTRAINT_VALIDATION,
            validation,
            1.0 if validation.accepted else 0.0,
            degraded=not validation.accepted,
        )

    def _build_response_plan(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        validation = self._validation(board)
        weather = self._weather(board)
        if validation.accepted:
            plan = RecommendationResponsePlan(
                answer_mode="constraint_checked_recommendation",
                candidates=validation.accepted,
                rejected_count=len(validation.rejected),
                hard_constraints_applied=validation.hard_constraints_applied,
                weather=weather,
                message="仅推荐 candidates 中通过硬约束校验的检索结果；推荐理由必须引用 ranking_features。",
            )
            confidence = 1.0
        else:
            plan = RecommendationResponsePlan(
                answer_mode="no_safe_candidate",
                rejected_count=len(validation.rejected),
                hard_constraints_applied=validation.hard_constraints_applied,
                weather=weather,
                message="当前检索结果中没有满足全部硬约束且证据完整的菜谱。",
                degraded=True,
            )
            confidence = 0.0
        return self._artifact(
            task,
            board,
            ArtifactKind.RESPONSE_PLAN,
            plan,
            confidence,
            degraded=plan.degraded,
        )

    def _supplement_candidate_evidence(
        self,
        candidates: tuple[RecipeCandidate, ...],
        board: CollaborationBlackboard,
    ) -> tuple[tuple[RecipeCandidate, ...], tuple[str, ...]]:
        available_tools = {
            tool.name for tool in self.tool_registry.for_recommendation_expert()
        }
        if "search_recipe_knowledge" not in available_tools:
            return candidates, ()
        supplemented: list[RecipeCandidate] = []
        warnings: list[str] = []
        for candidate in candidates:
            if candidate.ingredients and candidate.tools and candidate.cook_time_minutes:
                supplemented.append(candidate)
                continue
            try:
                invocation = self.tool_registry.invoke(
                    role=ToolRole.RECOMMENDATION_EXPERT,
                    tool_name="search_recipe_knowledge",
                    arguments={
                        "query": f"{candidate.recipe_name or candidate.recipe_id} 的食材、厨具和制作时间",
                        "recipe_names": [candidate.recipe_name]
                        if candidate.recipe_name
                        else [],
                        "top_k": 1,
                    },
                    context=self.tool_context(board),
                )
                result = RetrievalResult.model_validate(invocation.output)
                match = next(
                    (hit for hit in result.hits if hit.recipe_id == candidate.recipe_id),
                    result.hits[0] if result.hits else None,
                )
                if match is not None:
                    supplemented.append(
                        candidate.model_copy(
                            update={
                                "ingredients": candidate.ingredients
                                or self._as_strings(match.metadata.get("ingredients")),
                                "tools": candidate.tools
                                or self._as_strings(match.metadata.get("tools")),
                                "cook_time_minutes": candidate.cook_time_minutes
                                or self._as_positive_int(
                                    match.metadata.get("cook_time_minutes")
                                    or match.metadata.get("time_minutes")
                                ),
                                "weather_tags": candidate.weather_tags
                                or self._as_strings(match.metadata.get("weather_tags")),
                                "source_path": candidate.source_path or match.source_path,
                                "evidence": candidate.evidence or match.content,
                            }
                        )
                    )
                    continue
                warnings.append(
                    f"候选 {candidate.recipe_id} 未找到可用的知识补证"
                )
            except Exception as exc:
                warnings.append(f"候选 {candidate.recipe_id} 知识补证失败：{exc}")
            supplemented.append(candidate)
        return tuple(supplemented), tuple(warnings)

    def _artifact(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
        kind: ArtifactKind,
        payload: ExpertPayload,
        confidence: float,
        **metadata: Any,
    ) -> AgentArtifact:
        return AgentArtifact(
            id=self.artifact_id(board, task),
            owner=self.name,
            kind=kind,
            payload=payload.model_dump(mode="python"),
            confidence=confidence,
            task_id=task.id,
            metadata=metadata,
        )

    @staticmethod
    def _parse_constraints(query: str) -> TemporaryConstraints:
        available = RecipeRecommendationExpert._capture_list(
            query, r"(?:我有|现有|只有|可用)([^，。；;,.]+)"
        )
        excluded = RecipeRecommendationExpert._capture_list(
            query, r"(?:不要|不吃|排除|过敏(?:于)?)([^，。；;,.]+)"
        )
        known_tools = ("空气炸锅", "烤箱", "蒸锅", "电饭煲", "炒锅", "微波炉")
        tools = tuple(tool for tool in known_tools if tool in query)
        time_match = re.search(r"(\d{1,3})\s*分钟", query)
        city_match = re.search(r"([\u4e00-\u9fff]{2,8}?)(?:市)?(?:的)?天气", query)
        city = city_match.group(1) if city_match else ""
        city = re.sub(r"^(?:根据|在)", "", city)
        return TemporaryConstraints(
            available_ingredients=available,
            excluded_ingredients=excluded,
            available_tools=tools,
            max_time_minutes=int(time_match.group(1)) if time_match else None,
            city=city,
        )

    @staticmethod
    def _capture_list(query: str, pattern: str) -> tuple[str, ...]:
        match = re.search(pattern, query)
        if not match:
            return ()
        return tuple(
            item.strip()
            for item in re.split(r"[、和及]", match.group(1))
            if item.strip()
        )

    @staticmethod
    def _constraint_labels(constraints: TemporaryConstraints) -> list[str]:
        labels = [f"exclude:{item}" for item in constraints.excluded_ingredients]
        labels.extend(f"available:{item}" for item in constraints.available_ingredients)
        labels.extend(f"tool:{item}" for item in constraints.available_tools)
        if constraints.max_time_minutes is not None:
            labels.append(f"max_time:{constraints.max_time_minutes}")
        return labels

    @staticmethod
    def _as_strings(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,) if value.strip() else ()
        if isinstance(value, (list, tuple, set, frozenset)):
            return tuple(str(item) for item in value if str(item).strip())
        return ()

    @staticmethod
    def _as_positive_int(value: object) -> int | None:
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _payload(
        board: CollaborationBlackboard,
        kind: ArtifactKind,
        schema: type[ExpertPayload],
        *,
        stage: str = "",
    ) -> ExpertPayload:
        artifacts = board.artifacts_for(kind=kind)
        if stage:
            artifacts = tuple(
                artifact
                for artifact in artifacts
                if artifact.payload.get("stage") == stage
            )
        if not artifacts:
            raise ValueError(f"required artifact is missing: {kind.value}")
        return schema.model_validate(artifacts[-1].payload)

    def _constraints(self, board: CollaborationBlackboard) -> TemporaryConstraints:
        payload = self._payload(board, ArtifactKind.QUERY_CONSTRAINTS, TemporaryConstraints)
        assert isinstance(payload, TemporaryConstraints)
        return payload

    def _preferences(self, board: CollaborationBlackboard) -> PreferenceContext:
        payload = self._payload(
            board,
            ArtifactKind.USER_PREFERENCE_CONTEXT,
            PreferenceContext,
        )
        assert isinstance(payload, PreferenceContext)
        return payload

    def _weather(self, board: CollaborationBlackboard) -> WeatherContext | None:
        artifacts = board.artifacts_for(kind=ArtifactKind.WEATHER_CONTEXT)
        return WeatherContext.model_validate(artifacts[-1].payload) if artifacts else None

    def _candidate_set(
        self,
        board: CollaborationBlackboard,
        *,
        stage: str,
    ) -> CandidateSet:
        payload = self._payload(
            board,
            ArtifactKind.RECIPE_CANDIDATES,
            CandidateSet,
            stage=stage,
        )
        assert isinstance(payload, CandidateSet)
        return payload

    def _validation(self, board: CollaborationBlackboard) -> ConstraintValidationResult:
        artifacts = board.artifacts_for(kind=ArtifactKind.CONSTRAINT_VALIDATION)
        if not artifacts:
            raise ValueError("required artifact is missing: CONSTRAINT_VALIDATION")
        return ConstraintValidationResult.model_validate(artifacts[-1].payload)
