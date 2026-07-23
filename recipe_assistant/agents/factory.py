"""Task22 runtime assembly, V2 harness adaptation, and explicit rollback modes."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from threading import Lock, Thread
from time import perf_counter
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import urlopen

from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from recipe_assistant.agents.coordinator import CoordinatorOutcome, RecipeCoordinator
from recipe_assistant.agents.events import (
    AgentArtifact,
    ArtifactKind,
    ExpertCapability,
    thaw_value,
)
from recipe_assistant.agents.experts.nutrition_planning import NutritionPlanningExpert
from recipe_assistant.agents.experts.recipe_knowledge import (
    RecipeEvidence,
    RecipeEvidenceItem,
    RecipeKnowledgeExpert,
)
from recipe_assistant.agents.experts.recipe_recommendation import (
    CandidateSet,
    RecommendationResponsePlan,
    RecipeRecommendationExpert,
)
from recipe_assistant.agents.registry import ExpertRegistry
from recipe_assistant.agents.result import (
    AgentRunResult,
    HarnessOutcome,
    RunContext,
    RunStatus,
)
from recipe_assistant.agents.router import BusinessRouter
from recipe_assistant.agents.runtime import RecipeAgentRuntime
from recipe_assistant.core.config import PROJECT_ROOT, Settings
from recipe_assistant.core.database import session_scope
from recipe_assistant.repositories.sqlite import (
    SqlAlchemyInteractionRepository,
    SqlAlchemyProfileRepository,
)
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType
from recipe_assistant.schemas.nutrition import ConfirmedMealHistory
from recipe_assistant.services.constraint import (
    ConstraintService,
    ConstraintValidationResult,
    PreferenceContext,
)
from recipe_assistant.services.meal_history import MealHistoryService
from recipe_assistant.services.nutrition import NutritionCatalog, NutritionService
from recipe_assistant.services.profile import ProfileService
from recipe_assistant.services.recommendation import RecommendationService
from recipe_assistant.services.retrieval import RetrievalService
from recipe_assistant.services.simple_chat import SimpleChatService
from recipe_assistant.services.weather import WeatherService
from recipe_assistant.tools.nutrition_tools import create_nutrition_tools
from recipe_assistant.tools.recipe_knowledge_tools import create_recipe_knowledge_tool
from recipe_assistant.tools.recommendation_tools import create_recommendation_service_tools
from recipe_assistant.tools.registry import ToolRegistry
from recipe_assistant.tools.schemas import CalculateNutritionInput, MealHistoryInput


logger = logging.getLogger(__name__)


class LegacyExecutor(Protocol):
    def execute(self, query: str, thread_id: str) -> str: ...


class RuntimeProvider(Protocol):
    def __call__(self) -> RecipeAgentRuntime: ...


ShadowSink = Callable[[dict[str, Any]], None]


class LazyRuntimeProvider:
    """Build the production V2 expert graph only on the first non-SIMPLE request."""

    def __init__(self, builder: Callable[[], RecipeAgentRuntime]) -> None:
        self.builder = builder
        self._runtime: RecipeAgentRuntime | None = None
        self._lock = Lock()

    def __call__(self) -> RecipeAgentRuntime:
        if self._runtime is None:
            with self._lock:
                if self._runtime is None:
                    self._runtime = self.builder()
        return self._runtime


class _RuntimeExpertDispatcher:
    """Delegate normal tasks and bridge the existing deterministic COMPLEX template."""

    name = "multi_expert_runtime_dispatcher"
    capabilities = frozenset(ExpertCapability)

    def __init__(
        self,
        knowledge: RecipeKnowledgeExpert,
        recommendation: RecipeRecommendationExpert,
        nutrition: NutritionPlanningExpert,
        recommendation_service: RecommendationService,
        preference_provider: Callable[[int], PreferenceContext],
        weather_service: WeatherService,
    ) -> None:
        self.knowledge = knowledge
        self.recommendation = recommendation
        self.nutrition = nutrition
        self.recommendation_service = recommendation_service
        self.preference_provider = preference_provider
        self.weather_service = weather_service
        self.constraint_service = ConstraintService()

    def execute(self, task, board):
        if not task.id.startswith("complex."):
            return {
                ExpertCapability.RECIPE_KNOWLEDGE: self.knowledge,
                ExpertCapability.RECIPE_RECOMMENDATION: self.recommendation,
                ExpertCapability.NUTRITION_PLANNING: self.nutrition,
            }[task.capability].execute(task, board)

        handlers = {
            "NutritionPlanningExpert": self.nutrition.execute,
            "RecipeRecommendationExpert": self._complex_candidates,
            "RecipeKnowledgeExpert": self._complex_evidence,
            "ConstraintValidation": self._complex_validation,
            "BuildResponsePlan": self._complex_response_plan,
        }
        return handlers[task.title](task, board)

    def _complex_candidates(self, task, board) -> AgentArtifact:
        constraints = RecipeRecommendationExpert._parse_constraints(board.user_input)
        preferences = self.preference_provider(board.user_id)
        weather = (
            self.weather_service.get_current(constraints.city)
            if constraints.city
            else None
        )
        recall = self.recommendation_service.recall(board.user_input, top_k=20)
        ranked = RecommendationService.rank_candidates(
            recall.candidates,
            constraints,
            preferences,
            weather,
        )
        payload = CandidateSet(
            stage="ranked",
            candidates=ranked,
            warnings=recall.warnings,
        )
        return self._artifact(task, board, ArtifactKind.RECIPE_CANDIDATES, payload)

    def _complex_evidence(self, task, board) -> AgentArtifact:
        candidates = self._candidate_set(board)
        items = tuple(
            RecipeEvidenceItem(
                recipe_id=item.recipe_id,
                recipe_name=item.recipe_name,
                content=item.evidence or "候选来自结构化检索结果。",
                source_path=item.source_path,
                retrieval_sources=("multi_expert_retrieval",),
            )
            for item in candidates.candidates
            if item.source_path
        )
        payload = RecipeEvidence(
            query=board.user_input,
            items=items,
            retrieval_confidence=1.0 if items else 0.0,
            warnings=candidates.warnings,
            sufficient=bool(items),
            degraded=not items,
        )
        return self._artifact(task, board, ArtifactKind.RECIPE_EVIDENCE, payload)

    def _complex_validation(self, task, board) -> AgentArtifact:
        validation = self.constraint_service.validate(
            self._candidate_set(board).candidates,
            RecipeRecommendationExpert._parse_constraints(board.user_input),
            self.preference_provider(board.user_id),
        )
        return self._artifact(
            task,
            board,
            ArtifactKind.CONSTRAINT_VALIDATION,
            validation,
        )

    def _complex_response_plan(self, task, board) -> AgentArtifact:
        validation = self._validation(board)
        if validation.accepted:
            plan = RecommendationResponsePlan(
                answer_mode="constraint_checked_multi_expert_recommendation",
                candidates=validation.accepted,
                rejected_count=len(validation.rejected),
                hard_constraints_applied=validation.hard_constraints_applied,
                message="根据营养目标、检索证据和硬约束生成最终推荐。",
            )
        else:
            plan = RecommendationResponsePlan(
                answer_mode="no_safe_candidate",
                rejected_count=len(validation.rejected),
                hard_constraints_applied=validation.hard_constraints_applied,
                message="当前检索结果中没有满足全部硬约束且证据完整的菜谱。",
                degraded=True,
            )
        return self._artifact(task, board, ArtifactKind.RESPONSE_PLAN, plan)

    def _artifact(
        self,
        task,
        board,
        kind: ArtifactKind,
        payload: BaseModel,
    ) -> AgentArtifact:
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}:{kind.value.lower()}",
            owner=self.name,
            kind=kind,
            payload=payload.model_dump(mode="python"),
            confidence=1.0,
            task_id=task.id,
        )

    @staticmethod
    def _candidate_set(board) -> CandidateSet:
        artifacts = board.artifacts_for(kind=ArtifactKind.RECIPE_CANDIDATES)
        if not artifacts:
            raise ValueError("complex runtime has no recipe candidates")
        return CandidateSet.model_validate(artifacts[-1].payload)

    @staticmethod
    def _validation(board) -> ConstraintValidationResult:
        artifacts = board.artifacts_for(kind=ArtifactKind.CONSTRAINT_VALIDATION)
        if not artifacts:
            raise ValueError("complex runtime has no constraint validation")
        return ConstraintValidationResult.model_validate(artifacts[-1].payload)


class ArtifactResponseRenderer:
    """Convert coordinator artifacts into the existing public chat result contract."""

    def render(self, outcome: CoordinatorOutcome) -> tuple[str, list[dict[str, Any]]]:
        artifact = outcome.final_artifact
        payload = thaw_value(artifact.payload)
        if artifact.kind is ArtifactKind.ERROR:
            text = str(payload.get("message") or "当前协作结果不完整，请稍后重试。")
        elif payload.get("candidates"):
            text = self._render_candidates(payload)
        elif payload.get("evidence"):
            text = self._render_evidence(payload)
        else:
            text = str(payload.get("message") or "V2 已完成结构化处理。")
            if payload.get("report_id"):
                text += f"\n报告编号：{payload['report_id']}"
        return text.strip(), self._sources(outcome)

    @staticmethod
    def _render_candidates(payload: Mapping[str, Any]) -> str:
        lines = [str(payload.get("message") or "以下菜谱已通过约束检查：")]
        for index, candidate in enumerate(payload["candidates"][:5], start=1):
            name = candidate.get("recipe_name") or candidate["recipe_id"]
            lines.append(f"{index}. {name}")
        return "\n".join(lines)

    @staticmethod
    def _render_evidence(payload: Mapping[str, Any]) -> str:
        lines = []
        for item in payload["evidence"][:5]:
            name = item.get("recipe_name") or item["recipe_id"]
            lines.append(f"{name}：{item['content']}")
        return "\n\n".join(lines) or str(payload.get("message") or "未找到足够证据。")

    @staticmethod
    def _sources(outcome: CoordinatorOutcome) -> list[dict[str, Any]]:
        deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
        for artifact in outcome.blackboard.artifacts:
            payload = thaw_value(artifact.payload)
            for key in ("evidence", "candidates"):
                for item in payload.get(key, []):
                    source_path = str(item.get("source_path") or "")
                    recipe_id = str(item.get("recipe_id") or "")
                    if not source_path and not recipe_id:
                        continue
                    deduplicated[(recipe_id, source_path)] = {
                        "recipeId": recipe_id,
                        "recipeName": item.get("recipe_name"),
                        "sourcePath": source_path,
                        "retrievalSources": list(item.get("retrieval_sources") or []),
                    }
        return list(deduplicated.values())


class MultiExpertHarness:
    """Default V2 harness with explicit developer-only legacy and shadow modes."""

    def __init__(
        self,
        *,
        mode: str,
        runtime_provider: RuntimeProvider,
        legacy_executor: LegacyExecutor,
        legacy_fallback_enabled: bool = False,
        router: BusinessRouter | None = None,
        simple_chat: SimpleChatService | None = None,
        renderer: ArtifactResponseRenderer | None = None,
        shadow_sink: ShadowSink | None = None,
    ) -> None:
        self.mode = mode
        self.runtime_provider = runtime_provider
        self.legacy_executor = legacy_executor
        self.legacy_fallback_enabled = legacy_fallback_enabled
        self.router = router or BusinessRouter()
        self.simple_chat = simple_chat or SimpleChatService()
        self.renderer = renderer or ArtifactResponseRenderer()
        self.shadow_sink = shadow_sink or self._log_shadow

    @staticmethod
    def normalize_input(text: str) -> str:
        return " ".join((text or "").strip().split())

    def run(self, context: RunContext) -> HarnessOutcome:
        started_at = perf_counter()
        decision = self.router.route(context.normalized_input)
        events: list[dict[str, Any]] = [
            {
                "type": "route",
                "route": decision.route.value,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "runtime_mode": self.mode,
            }
        ]
        sources: list[dict[str, Any]] = []
        used_legacy = False
        try:
            if self.mode == "legacy":
                final_text = self._legacy(context)
                used_legacy = True
                events.append({"type": "legacy_executor", "status": "succeeded"})
            else:
                final_text, sources, runtime_events = self._v2(context, decision)
                events.extend(runtime_events)
                if self.mode == "shadow":
                    self._schedule_shadow(context, decision, final_text)
                    events.append({"type": "shadow_scheduled", "primary": "v2"})
            status = RunStatus.SUCCEEDED
            error = None
        except Exception as exc:
            if self.mode == "v2" and self.legacy_fallback_enabled:
                final_text = self._legacy(context)
                used_legacy = True
                status = RunStatus.SUCCEEDED
                error = None
                events.append(
                    {
                        "type": "legacy_fallback",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
            else:
                final_text = "抱歉，本次请求暂时无法完成，请稍后重试。"
                status = RunStatus.FAILED
                error = str(exc)
                events.append(
                    {
                        "type": "execution_error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )

        result = AgentRunResult(
            status=status,
            final_text=final_text,
            events=events,
            sources=sources,
            used_legacy_executor=used_legacy,
            error=error,
        )
        return HarnessOutcome(
            context=context,
            route_decision=decision,
            result=result,
            latency_ms=(perf_counter() - started_at) * 1000,
        )

    def _v2(
        self,
        context: RunContext,
        decision: RouteDecision,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        if decision.route is RouteType.SIMPLE:
            response = self.simple_chat.respond(context.normalized_input)
            return response.message, [], [
                {"type": "simple_chat", "category": response.category.value}
            ]
        outcome = self.runtime_provider().run(context, decision)
        text, sources = self.renderer.render(outcome)
        return text, sources, [
            {"type": "v2_runtime", "status": outcome.status.value},
            *outcome.blackboard.trace_events(),
        ]

    def _legacy(self, context: RunContext) -> str:
        return self.legacy_executor.execute(
            context.normalized_input,
            context.session_public_id,
        )

    def _schedule_shadow(
        self,
        context: RunContext,
        decision: RouteDecision,
        v2_text: str,
    ) -> None:
        def compare() -> None:
            started_at = perf_counter()
            try:
                legacy_text = self._legacy(context)
                record = {
                    "run_id": context.run_id,
                    "route": decision.route.value,
                    "status": "succeeded",
                    "v2_sha256": self._digest(v2_text),
                    "legacy_sha256": self._digest(legacy_text),
                    "same_text": v2_text == legacy_text,
                    "v2_length": len(v2_text),
                    "legacy_length": len(legacy_text),
                    "latency_ms": (perf_counter() - started_at) * 1000,
                }
            except Exception as exc:
                record = {
                    "run_id": context.run_id,
                    "route": decision.route.value,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            self.shadow_sink(record)

        Thread(target=compare, name=f"shadow-{context.run_id[:8]}", daemon=True).start()

    @staticmethod
    def _digest(text: str) -> str:
        return sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _log_shadow(record: dict[str, Any]) -> None:
        logger.info("runtime_shadow_comparison %s", json.dumps(record, ensure_ascii=False))


def build_multi_expert_runtime(
    settings: Settings,
    session_factory: sessionmaker[Session],
) -> RecipeAgentRuntime:
    retrieval_overrides: dict[str, Any] = {}
    if not settings.neo4j_enabled:
        retrieval_overrides["graph_retriever"] = None
    if not settings.chroma_enabled:
        retrieval_overrides["vector_retriever"] = None
    if not settings.bm25_enabled:
        retrieval_overrides["bm25_retriever"] = None
    retrieval = RetrievalService(**retrieval_overrides)
    recommendation_service = RecommendationService(retrieval)
    weather_service = _build_weather_service(settings)
    catalog_path = Path(PROJECT_ROOT) / "data" / "nutrition" / "recipes.json"
    catalog = (
        NutritionCatalog.from_json(catalog_path)
        if catalog_path.exists()
        else NutritionCatalog()
    )
    nutrition_service = NutritionService(catalog)

    def preference_provider(user_id: int) -> PreferenceContext:
        with session_scope(session_factory) as session:
            profile = ProfileService(
                SqlAlchemyProfileRepository(session)
            ).load_snapshot(user_id)
        return PreferenceContext(
            preferred_cuisines=tuple(profile.preferred_cuisines),
            disliked_ingredients=tuple(profile.disliked_ingredients),
            allergens=tuple(profile.allergens),
        )

    def meal_history(arguments: BaseModel, context) -> dict[str, Any]:
        parsed = MealHistoryInput.model_validate(arguments)
        with session_scope(session_factory) as session:
            history = MealHistoryService(
                SqlAlchemyInteractionRepository(session)
            ).load_confirmed(context.user_id, days=parsed.days)
        return history.model_dump(mode="json")

    def calculate_nutrition(arguments: BaseModel, context) -> dict[str, Any]:
        parsed = CalculateNutritionInput.model_validate(arguments)
        with session_scope(session_factory) as session:
            history = MealHistoryService(
                SqlAlchemyInteractionRepository(session)
            ).load_confirmed(context.user_id, days=7)
        requested = set(parsed.recipe_ids)
        filtered = ConfirmedMealHistory(
            user_id=history.user_id,
            records=tuple(
                record for record in history.records if record.recipe_id in requested
            ),
            included_event_types=history.included_event_types,
            start_at=history.start_at,
            end_at=history.end_at,
        )
        return nutrition_service.summarize(filtered).model_dump(mode="json")

    tools = [create_recipe_knowledge_tool(retrieval)]
    tools.extend(
        create_recommendation_service_tools(recommendation_service, weather_service)
    )
    tools.extend(
        create_nutrition_tools(
            meal_history=meal_history,
            calculate=calculate_nutrition,
        )
    )
    registry = ToolRegistry(tools)
    knowledge = RecipeKnowledgeExpert(registry)
    recommendation = RecipeRecommendationExpert(
        registry,
        preference_provider=preference_provider,
    )
    nutrition = NutritionPlanningExpert(registry)
    dispatcher = _RuntimeExpertDispatcher(
        knowledge,
        recommendation,
        nutrition,
        recommendation_service,
        preference_provider,
        weather_service,
    )
    return RecipeAgentRuntime(RecipeCoordinator(ExpertRegistry([dispatcher])))


def build_runtime_harness(
    settings: Settings,
    session_factory: sessionmaker[Session],
    legacy_executor: LegacyExecutor,
    *,
    runtime_provider: RuntimeProvider | None = None,
    shadow_sink: ShadowSink | None = None,
) -> MultiExpertHarness:
    provider = runtime_provider or LazyRuntimeProvider(
        lambda: build_multi_expert_runtime(settings, session_factory)
    )
    return MultiExpertHarness(
        mode=settings.agent_runtime_mode,
        runtime_provider=provider,
        legacy_executor=legacy_executor,
        legacy_fallback_enabled=settings.legacy_fallback_enabled,
        shadow_sink=shadow_sink,
    )


def observe_harness(
    harness: MultiExpertHarness,
    contexts: list[RunContext],
) -> dict[str, Any]:
    started_at = perf_counter()
    outcomes = [harness.run(context) for context in contexts]
    latencies = sorted(item.latency_ms for item in outcomes)
    passed = sum(
        item.result.status is RunStatus.SUCCEEDED
        and not item.result.used_legacy_executor
        for item in outcomes
    )
    return {
        "runtime_mode": harness.mode,
        "total": len(outcomes),
        "passed": passed,
        "failed": len(outcomes) - passed,
        "legacy_primary_responses": sum(
            item.result.used_legacy_executor for item in outcomes
        ),
        "routes": dict(
            sorted(
                {
                    route: sum(item.route_decision.route.value == route for item in outcomes)
                    for route in {item.route_decision.route.value for item in outcomes}
                }.items()
            )
        ),
        "latency_ms": {
            "p50": latencies[len(latencies) // 2] if latencies else 0.0,
            "p95": latencies[int((len(latencies) - 1) * 0.95)] if latencies else 0.0,
        },
        "elapsed_ms": (perf_counter() - started_at) * 1000,
    }


def _build_weather_service(settings: Settings) -> WeatherService:
    if not settings.weather_enabled or settings.amap_api_key is None:
        return WeatherService()
    api_key = settings.amap_api_key.get_secret_value().strip()
    if not api_key:
        return WeatherService()

    def provider(city: str) -> dict[str, Any]:
        query = urlencode({"city": city, "key": api_key, "extensions": "base"})
        url = f"{settings.amap_base_url.rstrip('/')}/v3/weather/weatherInfo?{query}"
        with urlopen(url, timeout=settings.amap_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        lives = payload.get("lives") or []
        if payload.get("status") != "1" or not lives:
            return {
                "success": False,
                "city": city,
                "message": payload.get("info") or "天气查询失败",
            }
        current = lives[0]
        return {
            "success": True,
            "city": current.get("city") or city,
            "weather": current.get("weather") or "",
            "temperature_c": current.get("temperature") or "",
            "humidity_percent": current.get("humidity") or "",
        }

    return WeatherService(weather_provider=provider)
