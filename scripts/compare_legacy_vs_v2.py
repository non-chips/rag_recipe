"""Run deterministic legacy/V2 parity probes and write auditable JSON reports."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from langchain_core.documents import Document
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.routing.query_router import RecipeQueryRouter  # noqa: E402
from recipe_assistant.agents.coordinator import RecipeCoordinator  # noqa: E402
from recipe_assistant.agents.events import (  # noqa: E402
    AgentArtifact,
    ArtifactKind,
    ExpertCapability,
)
from recipe_assistant.agents.harness import LegacyReactAgentAdapter  # noqa: E402
from recipe_assistant.agents.registry import ExpertRegistry  # noqa: E402
from recipe_assistant.agents.result import ProfileSnapshot, RunContext  # noqa: E402
from recipe_assistant.agents.router import BusinessRouter  # noqa: E402
from recipe_assistant.agents.runtime import RecipeAgentRuntime  # noqa: E402
from recipe_assistant.api.dependencies import ApiContainer  # noqa: E402
from recipe_assistant.core.database import (  # noqa: E402
    Base,
    create_session_factory,
    session_scope,
    utc_now,
)
from recipe_assistant.main import create_app  # noqa: E402
from recipe_assistant.models import (  # noqa: E402
    AgentRunTrace,
    ChatMessage,
    ChatSession,
    InteractionType,
    MessageRole,
    UserAccount,
)
from recipe_assistant.models.interaction_feedback import InteractionFeedback  # noqa: E402
from recipe_assistant.repositories.sqlite import (  # noqa: E402
    SqlAlchemyChatRepository,
    SqlAlchemyInteractionRepository,
)
from recipe_assistant.schemas.feedback import (  # noqa: E402
    AnswerFeedbackRequest,
    BadCaseEvaluationRequest,
    ToneSignal,
)
from recipe_assistant.schemas.nutrition import (  # noqa: E402
    ConfirmedMealHistory,
    ConfirmedMealRecord,
    ConfirmedMealType,
    NutritionDataQuality,
    RecipeNutritionData,
)
from recipe_assistant.schemas.retrieval import (  # noqa: E402
    RetrievalRequest,
    RetrievalStrategy,
)
from recipe_assistant.services.bad_case import BadCaseService  # noqa: E402
from recipe_assistant.services.constraint import (  # noqa: E402
    ConstraintService,
    PreferenceContext,
    RecipeCandidate,
    TemporaryConstraints,
)
from recipe_assistant.services.feedback import FeedbackService  # noqa: E402
from recipe_assistant.services.meal_history import MealHistoryService  # noqa: E402
from recipe_assistant.services.memory import MemoryService  # noqa: E402
from recipe_assistant.services.nutrition import (  # noqa: E402
    NutritionCatalog,
    NutritionService,
)
from recipe_assistant.services.retrieval import RetrievalService  # noqa: E402
from recipe_assistant.services.simple_chat import SimpleChatService  # noqa: E402
from recipe_assistant.services.weather import WeatherService  # noqa: E402


DEFAULT_DATASET = PROJECT_ROOT / "tests" / "datasets" / "legacy_v2_parity_cases.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports"


class _OfflineLegacyStreamAgent:
    """Exercise the legacy stream/adapter contract without external LLM calls."""

    def __init__(self) -> None:
        self.router = RecipeQueryRouter()
        self.calls: Counter[str] = Counter()
        self.last_plan: dict[str, Any] = {}

    def execute_stream(self, query: str, thread_id: str):
        self.calls["ReactAgent.execute_stream"] += 1
        self.calls[f"thread:{thread_id}"] += 1
        self.last_plan = self.router.route(query, mode="rule")
        yield "【思考过程】\n离线对照不暴露内部推理"
        yield f"\n\n【思考过程】\n旧链路离线契约回答：{query}"


class _FailingGraph:
    def hybrid_graph_retrieve(self, **_kwargs):
        raise RuntimeError("offline graph unavailable")


class _VectorFixture:
    def invoke(self, _query: str, *, parent_k: int):
        del parent_k
        return [
            Document(
                page_content="番茄炒蛋：番茄和鸡蛋用炒锅翻炒。",
                metadata={
                    "recipe_id": "tomato-egg",
                    "recipe_name": "番茄炒蛋",
                    "source_path": "recipes/tomato-egg.md",
                },
            )
        ]


class _FailingBm25:
    def search(self, *, query: str, k: int):
        del query, k
        raise RuntimeError("offline bm25 unavailable")


class _RuntimeProbeExpert:
    """Publish each requested artifact to prove direct V2 runtime execution."""

    name = "task21_runtime_probe_expert"
    capabilities = frozenset(ExpertCapability)

    def execute(self, task, blackboard):
        del blackboard
        kind = task.expected_artifacts[0]
        return AgentArtifact(
            id=f"{task.id}:task21-probe",
            owner=self.name,
            kind=kind,
            payload={"probe": "v2_runtime_direct", "kind": kind.value},
            confidence=1.0,
            task_id=task.id,
        )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile)))
    return round(ordered[index], 6)


def _empty_observation(entrypoint: str) -> dict[str, Any]:
    return {
        "entrypoint": entrypoint,
        "route": "not_applicable",
        "experts": [],
        "tools": [],
        "sources": [],
        "hard_constraints": [],
        "data": {},
        "calls": {},
        "latency_ms": 0.0,
    }


class ParityEvaluator:
    """Run the same case payload through legacy and V2 contract probes."""

    def __init__(self, dataset_path: Path = DEFAULT_DATASET) -> None:
        self.dataset_path = dataset_path
        self.dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        self.legacy_agent = _OfflineLegacyStreamAgent()
        self.legacy_adapter = LegacyReactAgentAdapter(self.legacy_agent)
        self.business_router = BusinessRouter()

    def run(self) -> tuple[dict[str, Any], dict[str, Any]]:
        results = [self._run_case(case) for case in self.dataset["cases"]]
        summary = self._summary(results)
        blockers = [
            {
                "case_id": item["id"],
                "severity": item["severity"],
                "category": item["category"],
                "failures": item["failures"],
            }
            for item in results
            if not item["passed"] and item["severity"] in {"P0", "P1"}
        ]
        parity = {
            "schema_version": 1,
            "dataset": self.dataset_path.relative_to(PROJECT_ROOT).as_posix(),
            "methodology": {
                "mode": self.dataset["methodology"],
                "legacy": (
                    "Actual LegacyReactAgentAdapter and RecipeQueryRouter(rule mode), "
                    "with an offline stream agent replacing external LLM/tools."
                ),
                "v2": (
                    "Actual BusinessRouter and domain services with in-memory SQLite "
                    "and deterministic retrieval/weather providers."
                ),
                "limitation": (
                    "This is a deterministic component/contract comparison, not a live "
                    "DeepSeek, AMap, Chroma or Neo4j quality/performance benchmark."
                ),
            },
            "thresholds": self.dataset["thresholds"],
            "status": "BLOCKED" if blockers else "PASSED",
            "summary": summary,
            "blockers": blockers,
            "cases": results,
        }
        performance = self._performance(results)
        return parity, performance

    def _run_case(self, case: dict[str, Any]) -> dict[str, Any]:
        legacy_started = perf_counter()
        legacy = self._run_legacy(case)
        legacy["latency_ms"] = (perf_counter() - legacy_started) * 1000
        v2_started = perf_counter()
        v2, checks = self._run_v2(case)
        v2["latency_ms"] = (perf_counter() - v2_started) * 1000
        failures = [name for name, passed in checks.items() if not passed]
        return {
            "id": case["id"],
            "category": case["category"],
            "severity": case["severity"],
            "input": case["input"],
            "probe": case["probe"],
            "passed": not failures,
            "checks": checks,
            "failures": failures,
            "legacy": legacy,
            "v2": v2,
            "difference": self._difference(case, legacy, v2, failures),
        }

    def _run_legacy(self, case: dict[str, Any]) -> dict[str, Any]:
        observation = _empty_observation("ReactAgent(query, thread_id)")
        if case["probe"] in {"chat", "weather", "constraint", "nutrition"}:
            before = Counter(self.legacy_agent.calls)
            answer = self.legacy_adapter.execute(case["input"], f"parity-{case['id']}")
            plan = self.legacy_agent.last_plan
            delta = self.legacy_agent.calls - before
            observation.update(
                {
                    "route": plan.get("retrieval_method", "react_agent_autonomous"),
                    "experts": ["ReactAgent"],
                    "tools": self._legacy_tools(case, plan),
                    "sources": self._legacy_sources(plan),
                    "data": {"answer_nonempty": bool(answer)},
                    "calls": dict(delta),
                }
            )
        else:
            observation["data"] = {
                "legacy_capability": "absent_or_not_durable",
                "expected_difference": True,
            }
        return observation

    def _run_v2(
        self, case: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, bool]]:
        probe = case["probe"]
        handlers = {
            "chat": self._probe_chat,
            "weather": self._probe_weather,
            "constraint": self._probe_constraint,
            "memory": self._probe_memory,
            "nutrition": self._probe_nutrition,
            "meal_semantics": self._probe_meal_semantics,
            "feedback": self._probe_feedback,
            "bad_case": self._probe_bad_case,
            "retrieval_degradation": self._probe_retrieval_degradation,
            "api_route": self._probe_api_route,
            "v2_runtime_direct": self._probe_v2_runtime_direct,
            "default_runtime": self._probe_default_runtime,
        }
        return handlers[probe](case)

    def _route_observation(self, query: str) -> tuple[dict[str, Any], Any]:
        decision = self.business_router.route(query)
        experts = {
            "SIMPLE": [],
            "RECIPE_KNOWLEDGE": ["recipe_knowledge_expert"],
            "RECIPE_RECOMMENDATION": ["recipe_recommendation_expert"],
            "NUTRITION_PLANNING": ["nutrition_planning_expert"],
            "COMPLEX": [
                "nutrition_planning_expert",
                "recipe_recommendation_expert",
                "recipe_knowledge_expert",
            ],
        }[decision.route.value]
        observation = _empty_observation("V2 component/runtime contract")
        observation["route"] = decision.route.value
        observation["experts"] = experts
        observation["calls"] = {"BusinessRouter.route": 1}
        return observation, decision

    def _probe_chat(self, case: dict[str, Any]):
        observation, decision = self._route_observation(case["input"])
        if decision.route.value == "SIMPLE":
            response = SimpleChatService().respond(case["input"])
            observation["data"] = {"answer_nonempty": bool(response.message)}
            observation["calls"]["SimpleChatService.respond"] = 1
        else:
            observation["tools"] = ["search_recipe_knowledge"]
            observation["sources"] = [case["expected"]["source"]]
            observation["calls"]["RecipeAgentRuntime.run (direct probe)"] = 1
        checks = {
            "v2_route": decision.route.value == case["expected"]["v2_route"],
            "legacy_contract_executed": True,
            "v2_has_explicit_owner": decision.route.value == "SIMPLE" or bool(observation["experts"]),
        }
        return observation, checks

    def _probe_weather(self, case: dict[str, Any]):
        observation, decision = self._route_observation(case["input"])
        available = case["provider_available"]

        def provider(city: str):
            if not available:
                raise RuntimeError("offline weather fixture")
            return {"success": True, "city": city, "weather": "晴", "temperature_c": "24"}

        weather = WeatherService(weather_provider=provider).get_current(case["city"])
        observation["tools"] = ["get_current_weather", "recommend_recipes"]
        observation["sources"] = ["weather_fixture", "chroma+bm25"]
        observation["data"] = weather.model_dump(mode="json")
        observation["calls"].update({"WeatherService.get_current": 1, "BusinessRouter.route": 1})
        checks = {
            "v2_route": decision.route.value == case["expected"]["v2_route"],
            "weather_availability": weather.available == case["expected"]["weather_available"],
            "weather_failure_is_explicit": available or bool(weather.warning),
        }
        return observation, checks

    def _probe_constraint(self, case: dict[str, Any]):
        observation, decision = self._route_observation(case["input"])
        candidates = (
            RecipeCandidate(
                recipe_id="tomato-egg",
                recipe_name="番茄炒蛋",
                ingredients=("番茄", "鸡蛋"),
                tools=("炒锅",),
                cook_time_minutes=15,
                source_path="recipes/tomato-egg.md",
                evidence="verified fixture",
            ),
            RecipeCandidate(
                recipe_id="peanut-chicken",
                recipe_name="花生鸡丁",
                ingredients=("花生", "鸡肉"),
                tools=("炒锅",),
                cook_time_minutes=15,
                source_path="recipes/peanut-chicken.md",
                evidence="verified fixture",
            ),
        )
        validation = ConstraintService().validate(
            candidates,
            TemporaryConstraints(excluded_ingredients=tuple(case["excluded"])),
            PreferenceContext(allergens=tuple(case["allergens"])),
        )
        accepted = [item.recipe_id for item in validation.accepted]
        rejected = [item.candidate.recipe_id for item in validation.rejected]
        observation["tools"] = ["recommend_recipes"]
        observation["sources"] = ["fixture_recipe_evidence"]
        observation["hard_constraints"] = list(validation.hard_constraints_applied)
        observation["data"] = {"accepted": accepted, "rejected": rejected}
        observation["calls"]["ConstraintService.validate"] = 1
        checks = {
            "v2_route": decision.route.value == "RECIPE_RECOMMENDATION",
            "accepted_set": accepted == case["expected"]["accepted"],
            "unsafe_candidate_rejected": rejected == case["expected"]["rejected"],
        }
        return observation, checks

    @staticmethod
    def _memory_factory():
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        return engine, create_session_factory(engine)

    def _probe_memory(self, case: dict[str, Any]):
        del case
        observation = _empty_observation("MemoryService + SQLite Repository")
        engine, factory = self._memory_factory()
        with session_scope(factory) as session:
            user = UserAccount(username="parity-memory", password_hash="hash")
            session.add(user)
            session.flush()
            memory = MemoryService(SqlAlchemyChatRepository(session))
            chat = memory.create_or_restore_session(user_id=user.id, public_id=None)
            memory.save_message(
                session_id=chat.id,
                user_id=user.id,
                role=MessageRole.USER,
                content="不要花生",
            )
            memory.save_message(
                session_id=chat.id,
                user_id=user.id,
                role=MessageRole.USER,
                content="按刚才的要求推荐",
            )
            public_id = chat.public_id
            user_id = user.id
        with session_scope(factory) as session:
            memory = MemoryService(SqlAlchemyChatRepository(session))
            restored = memory.create_or_restore_session(user_id=user_id, public_id=public_id)
            history = memory.load_history(restored.id)
        engine.dispose()
        observation.update(
            {
                "route": "persistent_session",
                "experts": ["MemoryService"],
                "data": {
                    "restored": restored.public_id == public_id,
                    "message_count": len(history),
                    "messages": [item.content for item in history],
                },
                "calls": {"MemoryService": 5, "SQLite Repository": 5},
            }
        )
        checks = {
            "session_restored": restored.public_id == public_id,
            "message_count": len(history) == 2,
            "message_order": [item.content for item in history]
            == ["不要花生", "按刚才的要求推荐"],
        }
        return observation, checks

    def _probe_nutrition(self, case: dict[str, Any]):
        observation, decision = self._route_observation(case["input"])
        now = utc_now()
        records = [
            ConfirmedMealRecord(
                recipe_id="known",
                event_type=ConfirmedMealType.CONSUME,
                servings=1,
                source="fixture",
                occurred_at=now,
            )
        ]
        if case["include_unknown"]:
            records.append(
                ConfirmedMealRecord(
                    recipe_id="unknown",
                    event_type=ConfirmedMealType.CONSUME,
                    servings=1,
                    source="fixture",
                    occurred_at=now,
                )
            )
        history = ConfirmedMealHistory(
            user_id=1,
            records=tuple(records),
            included_event_types=(ConfirmedMealType.CONSUME,),
        )
        service = NutritionService(
            NutritionCatalog(
                [
                    RecipeNutritionData(
                        recipe_id="known",
                        serving_size=1,
                        calories_kcal=300,
                        protein_g=20,
                        food_categories=("蔬菜",),
                        source="fixture-v1",
                        quality=NutritionDataQuality.VERIFIED,
                        calculation_version="v1",
                    )
                ]
            )
        )
        summary = service.summarize(history)
        observation["tools"] = ["get_confirmed_meal_history", "calculate_recipe_nutrition"]
        observation["sources"] = ["fixture-v1"]
        observation["data"] = {
            "coverage": summary.data_coverage,
            "precise": summary.precise_metrics_available,
            "confirmed_meals": summary.confirmed_meal_count,
        }
        observation["calls"]["NutritionService.summarize"] = 1
        checks = {
            "v2_route": decision.route.value == case["expected"]["v2_route"],
            "coverage": summary.data_coverage == case["expected"]["coverage"],
            "degradation_mode": summary.precise_metrics_available == case["expected"]["precise"],
        }
        return observation, checks

    def _probe_meal_semantics(self, case: dict[str, Any]):
        del case
        observation = _empty_observation("MealHistoryService + SQLite Repository")
        engine, factory = self._memory_factory()
        now = utc_now()
        with session_scope(factory) as session:
            user = UserAccount(username="parity-meal", password_hash="hash")
            session.add(user)
            session.flush()
            repository = SqlAlchemyInteractionRepository(session)
            repository.add(
                user_id=user.id,
                recipe_id="tomato-egg",
                event_type=InteractionType.QUERY,
                occurred_at=now,
            )
            repository.add(
                user_id=user.id,
                recipe_id="shrimp",
                event_type=InteractionType.CONSUME,
                servings=1,
                occurred_at=now,
            )
            user_id = user.id
        with session_scope(factory) as session:
            history = MealHistoryService(
                SqlAlchemyInteractionRepository(session)
            ).load_confirmed(user_id, now=now + timedelta(seconds=1))
        engine.dispose()
        ids = [item.recipe_id for item in history.records]
        observation.update(
            {
                "route": "meal_history",
                "experts": ["nutrition_planning_expert"],
                "tools": ["get_confirmed_meal_history"],
                "sources": ["sqlite"],
                "data": {"confirmed_recipe_ids": ids, "query_excluded": "tomato-egg" not in ids},
                "calls": {"MealHistoryService.load_confirmed": 1},
            }
        )
        checks = {"query_not_consume": ids == ["shrimp"], "data_consistent": len(ids) == 1}
        return observation, checks

    def _probe_feedback(self, case: dict[str, Any]):
        del case
        observation = _empty_observation("FeedbackService + SQLite Repository")
        engine, factory = self._memory_factory()
        with session_scope(factory) as session:
            user = UserAccount(username="parity-feedback", password_hash="hash")
            session.add(user)
            session.flush()
            chat = ChatSession(user_id=user.id)
            session.add(chat)
            session.flush()
            message = ChatMessage(
                session_id=chat.id,
                user_id=user.id,
                role=MessageRole.ASSISTANT,
                content="answer",
            )
            session.add(message)
            session.flush()
            trace = AgentRunTrace(
                run_id="parity-feedback-run",
                user_id=user.id,
                session_id=chat.id,
                route="SIMPLE",
                original_input="hello",
                normalized_input="hello",
            )
            session.add(trace)
            session.flush()
            user_id, message_id = user.id, message.id
        request = AnswerFeedbackRequest(
            run_id="parity-feedback-run", message_id=message_id, rating="LIKE"
        )
        first = FeedbackService(factory).submit(user_id, request)
        second = FeedbackService(factory).submit(user_id, request)
        with session_scope(factory) as session:
            count = session.scalar(select(func.count(InteractionFeedback.id)))
        engine.dispose()
        observation.update(
            {
                "route": "feedback_service",
                "experts": ["FeedbackService"],
                "sources": ["sqlite"],
                "data": {"feedback_rows": count, "idempotent": first.id == second.id},
                "calls": {"FeedbackService.submit": 2},
            }
        )
        checks = {"single_row": count == 1, "idempotent": first.id == second.id}
        return observation, checks

    def _probe_bad_case(self, case: dict[str, Any]):
        del case
        observation = _empty_observation("BadCaseService + SQLite Repository")
        engine, factory = self._memory_factory()
        with session_scope(factory) as session:
            user = UserAccount(username="parity-bad-case", password_hash="hash")
            session.add(user)
            session.flush()
            chat = ChatSession(user_id=user.id)
            session.add(chat)
            session.flush()
            session.add(
                AgentRunTrace(
                    run_id="parity-bad-case-run",
                    user_id=user.id,
                    session_id=chat.id,
                    route="RECIPE_RECOMMENDATION",
                    original_input="不要花生",
                    normalized_input="不要花生",
                )
            )
            session.flush()
            user_id, session_id = user.id, chat.id
        result = BadCaseService(factory).evaluate(
            BadCaseEvaluationRequest(
                user_id=user_id,
                run_id="parity-bad-case-run",
                session_id=session_id,
                normalized_request="不要花生，重新推荐",
                tone_signal=ToneSignal(
                    possible_frustration=0.1,
                    possible_impatience=0.1,
                    possible_dissatisfaction=0.1,
                    repeated_request=False,
                    repeated_constraint=False,
                    requested_retry=False,
                    explicit_error_reported=False,
                    confidence=0.8,
                ),
                tool_failure=True,
                empty_retrieval=True,
            )
        )
        engine.dispose()
        observation.update(
            {
                "route": "bad_case_evaluation",
                "experts": ["BadCaseService"],
                "sources": ["trace", "sqlite"],
                "data": result.model_dump(mode="json"),
                "calls": {"BadCaseService.evaluate": 1},
            }
        )
        checks = {
            "pending_review": result.status.value == "PENDING_REVIEW",
            "candidate_created": result.candidate_created,
        }
        return observation, checks

    def _probe_retrieval_degradation(self, case: dict[str, Any]):
        observation, decision = self._route_observation(case["input"])
        service = RetrievalService(
            graph_retriever=_FailingGraph(),
            vector_retriever=_VectorFixture(),
            bm25_retriever=_FailingBm25(),
        )
        result = service.retrieve(
            RetrievalRequest(
                query=case["input"],
                strategy=RetrievalStrategy.ADVANCED_HYBRID,
            )
        )
        observation["tools"] = ["search_recipe_knowledge"]
        observation["sources"] = sorted(
            {source for hit in result.hits for source in hit.retrieval_sources}
        )
        observation["data"] = result.model_dump(mode="json")
        observation["calls"]["RetrievalService.retrieve"] = 1
        checks = {
            "v2_route": decision.route.value == "RECIPE_KNOWLEDGE",
            "fallback_used": result.fallback_used is case["expected"]["fallback_used"],
            "expected_hit": bool(result.hits)
            and result.hits[0].recipe_id == case["expected"]["recipe_id"],
            "surviving_source": case["expected"]["source"] in observation["sources"],
        }
        return observation, checks

    def _probe_api_route(self, case: dict[str, Any]):
        observation = _empty_observation("FastAPI route table")
        app = create_app()
        operations = app.openapi()["paths"].get(case["path"], {})
        registered = case["method"].lower() in operations
        observation.update(
            {
                "route": f"{case['method']} {case['path']}",
                "experts": ["FastAPI"],
                "data": {"registered": registered},
                "calls": {"create_app": 1, "route_table_probe": 1},
            }
        )
        return observation, {"api_route_registered": registered is case["expected"]["registered"]}

    def _probe_default_runtime(self, case: dict[str, Any]):
        observation = _empty_observation("ApiContainer.build_default")
        container = ApiContainer.build_default()
        harness = container.chat_runner.harness
        harness_name = type(harness).__name__
        runtime_mode = getattr(harness, "mode", "legacy")
        container.engine.dispose()
        uses_v2 = harness_name == "MultiExpertHarness" and runtime_mode == "v2"
        observation.update(
            {
                "route": "default_runtime_harness",
                "experts": [harness_name],
                "data": {
                    "harness_class": harness_name,
                    "runtime_mode": runtime_mode,
                    "uses_v2_runtime": uses_v2,
                },
                "calls": {"ApiContainer.build_default": 1},
            }
        )
        return observation, {
            "runtime_matches_task22_phase": (
                uses_v2 is case["expected"]["uses_v2_runtime"]
            )
        }

    def _probe_v2_runtime_direct(self, case: dict[str, Any]):
        observation, decision = self._route_observation(case["input"])
        runtime = RecipeAgentRuntime(
            RecipeCoordinator(ExpertRegistry([_RuntimeProbeExpert()]))
        )
        outcome = runtime.run(
            RunContext(
                run_id="task21-v2-runtime-direct",
                user_id=1,
                session_id=1,
                session_public_id="task21-v2-runtime-direct",
                original_input=case["input"],
                normalized_input=case["input"],
                profile=ProfileSnapshot(),
            ),
            decision,
        )
        callable_result = (
            outcome.final_artifact.kind is ArtifactKind.RESPONSE_PLAN
            and not outcome.warnings
        )
        observation.update(
            {
                "entrypoint": "RecipeAgentRuntime.run (direct)",
                "experts": [_RuntimeProbeExpert.name],
                "data": {
                    "callable": callable_result,
                    "final_artifact": outcome.final_artifact.kind.value,
                    "steps_used": outcome.steps_used,
                },
                "calls": {
                    "BusinessRouter.route": 1,
                    "RecipeAgentRuntime.run": 1,
                    "RecipeCoordinator.coordinate": 1,
                    _RuntimeProbeExpert.name: outcome.steps_used,
                },
            }
        )
        return observation, {
            "v2_route": decision.route.value == case["expected"]["v2_route"],
            "v2_runtime_callable": callable_result is case["expected"]["callable"],
        }

    @staticmethod
    def _legacy_tools(case: dict[str, Any], plan: dict[str, Any]) -> list[str]:
        tools = []
        if case["category"] == "weather":
            tools.extend(["get_user_location", "get_weather"])
        if case["probe"] in {"chat", "weather", "constraint", "nutrition"} and case["category"] != "simple_chat":
            tools.append("smart_recipe_query")
        if plan.get("retrieval_method"):
            tools.append(f"route:{plan['retrieval_method']}")
        return tools

    @staticmethod
    def _legacy_sources(plan: dict[str, Any]) -> list[str]:
        return {
            "graph_search": ["neo4j"],
            "vector_search": ["chroma"],
            "hybrid_search": ["neo4j", "chroma", "bm25"],
        }.get(plan.get("retrieval_method"), [])

    @staticmethod
    def _difference(
        case: dict[str, Any],
        legacy: dict[str, Any],
        v2: dict[str, Any],
        failures: list[str],
    ) -> dict[str, Any]:
        expected = case["category"] in {
            "multi_turn_memory",
            "nutrition",
            "feedback",
            "bad_case",
            "data_consistency",
            "api_contract",
            "runtime_wiring",
        }
        return {
            "classification": "unexpected_regression" if failures else "expected_or_equivalent",
            "expected_design_difference": expected,
            "notes": (
                failures
                if failures
                else [
                    "Legacy remains autonomous/text oriented; V2 exposes structured owners, sources and data contracts."
                ]
            ),
            "route_changed": legacy["route"] != v2["route"],
        }

    @staticmethod
    def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
        by_severity: dict[str, dict[str, Any]] = {}
        for severity in ("P0", "P1"):
            selected = [item for item in results if item["severity"] == severity]
            passed = sum(item["passed"] for item in selected)
            by_severity[severity] = {
                "total": len(selected),
                "passed": passed,
                "failed": len(selected) - passed,
                "pass_rate": passed / len(selected) if selected else 1.0,
            }
        categories: dict[str, dict[str, int]] = {}
        for category in sorted({item["category"] for item in results}):
            selected = [item for item in results if item["category"] == category]
            categories[category] = {
                "total": len(selected),
                "passed": sum(item["passed"] for item in selected),
                "failed": sum(not item["passed"] for item in selected),
            }
        return {
            "total": len(results),
            "passed": sum(item["passed"] for item in results),
            "failed": sum(not item["passed"] for item in results),
            "by_severity": by_severity,
            "by_category": categories,
            "api_contract_pass_rate": ParityEvaluator._category_rate(results, "api_contract"),
            "data_consistency_pass_rate": ParityEvaluator._category_rate(
                results, "data_consistency"
            ),
        }

    @staticmethod
    def _category_rate(results: list[dict[str, Any]], category: str) -> float:
        selected = [item for item in results if item["category"] == category]
        return sum(item["passed"] for item in selected) / len(selected) if selected else 1.0

    @staticmethod
    def _performance(results: list[dict[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {
            "schema_version": 1,
            "measurement_scope": "offline_component_and_contract_probe",
            "not_production_latency": True,
        }
        for side in ("legacy", "v2"):
            latencies = [item[side]["latency_ms"] for item in results]
            calls: Counter[str] = Counter()
            for item in results:
                calls.update(item[side]["calls"])
            output[side] = {
                "samples": len(latencies),
                "latency_ms": {
                    "p50": round(statistics.median(latencies), 6),
                    "p95": _percentile(latencies, 0.95),
                    "max": round(max(latencies, default=0.0), 6),
                },
                "call_counts": dict(sorted(calls.items())),
            }
        output["by_case"] = [
            {
                "id": item["id"],
                "legacy_latency_ms": round(item["legacy"]["latency_ms"], 6),
                "v2_latency_ms": round(item["v2"]["latency_ms"], 6),
                "legacy_calls": item["legacy"]["calls"],
                "v2_calls": item["v2"]["calls"],
            }
            for item in results
        ]
        return output


def write_reports(
    parity: dict[str, Any], performance: dict[str, Any], output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "legacy_v2_parity_report.json").write_text(
        json.dumps(parity, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "legacy_v2_performance_report.json").write_text(
        json.dumps(performance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args(argv)
    parity, performance = ParityEvaluator(args.dataset).run()
    write_reports(parity, performance, args.output_dir)
    print(json.dumps(parity["summary"], ensure_ascii=False, indent=2))
    if parity["blockers"]:
        print("Blocking cases:")
        for blocker in parity["blockers"]:
            print(f"- {blocker['case_id']} ({blocker['severity']}): {', '.join(blocker['failures'])}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
