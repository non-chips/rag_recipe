"""Deterministic end-to-end service baseline without external infrastructure."""

from __future__ import annotations

import json
import platform
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from langchain_core.documents import Document
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from recipe_assistant.agents.router import BusinessRouter
from recipe_assistant.core.database import (
    Base,
    create_session_factory,
    session_scope,
    utc_now,
)
from recipe_assistant.models.agent_trace import AgentRunTrace
from recipe_assistant.models.bad_case import BadCaseCandidate
from recipe_assistant.models.interaction_feedback import InteractionFeedback
from recipe_assistant.models.message import ChatMessage, MessageRole
from recipe_assistant.models.session import ChatSession
from recipe_assistant.models.user import UserAccount
from recipe_assistant.schemas.feedback import (
    AnswerFeedbackRequest,
    BadCaseEvaluationRequest,
    BadCaseStatus,
    ToneSignal,
)
from recipe_assistant.schemas.nutrition import (
    ConfirmedMealHistory,
    ConfirmedMealRecord,
    ConfirmedMealType,
    RecipeNutritionData,
)
from recipe_assistant.schemas.retrieval import RetrievalRequest, RetrievalStrategy
from recipe_assistant.services.bad_case import BadCaseService
from recipe_assistant.services.constraint import (
    ConstraintService,
    PreferenceContext,
    RecipeCandidate,
    TemporaryConstraints,
)
from rag.evaluation.metrics import (
    EvaluationCaseResult,
    summarize_results,
)
from recipe_assistant.services.feedback import FeedbackService
from recipe_assistant.services.nutrition import NutritionCatalog, NutritionService
from recipe_assistant.services.recommendation import RecommendationService
from recipe_assistant.services.retrieval import RetrievalService


class _BackendCounter:
    def __init__(self, failed_sources: set[str]) -> None:
        self.failed_sources = failed_sources
        self.calls: dict[str, int] = defaultdict(int)

    def document(self, source: str) -> Document:
        return Document(
            page_content=f"offline {source} evidence for tomato egg",
            metadata={
                "recipe_id": "recipe-tomato-egg",
                "recipe_name": "Tomato Egg",
                "source_path": "recipes/tomato-egg.md",
                "ingredients": ["tomato", "egg"],
                "tools": ["wok"],
            },
        )


class _GraphBackend:
    def __init__(self, counter: _BackendCounter) -> None:
        self.counter = counter

    def hybrid_graph_retrieve(self, **_kwargs: Any) -> dict[str, Any]:
        self.counter.calls["graph"] += 1
        if "graph" in self.counter.failed_sources:
            raise ConnectionError("fixture graph unavailable")
        return {
            "candidate_recipe_ids": ["recipe-tomato-egg"],
            "graph_context_docs": [self.counter.document("graph")],
        }

    def get_recipe_evidence(self, recipe_ids: list[str]) -> list[dict[str, str]]:
        self.counter.calls["graph_evidence"] += 1
        return [{"recipe_id": recipe_ids[0], "source": "fixture-graph"}]


class _VectorBackend:
    def __init__(self, counter: _BackendCounter) -> None:
        self.counter = counter

    def invoke(self, _query: str, **_kwargs: Any) -> list[Document]:
        self.counter.calls["chroma"] += 1
        if "chroma" in self.counter.failed_sources:
            raise RuntimeError("fixture vector unavailable")
        return [self.counter.document("chroma")]


class _Bm25Backend:
    def __init__(self, counter: _BackendCounter) -> None:
        self.counter = counter

    def search(self, **_kwargs: Any) -> list[tuple[Document, float]]:
        self.counter.calls["bm25"] += 1
        if "bm25" in self.counter.failed_sources:
            raise RuntimeError("fixture bm25 unavailable")
        return [(self.counter.document("bm25"), 3.5)]


class SystemEvaluationRunner:
    """Run an offline release baseline against real application services."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        dataset_dir = self.project_root / "tests" / "datasets"
        self.routing_cases = self._read_json(dataset_dir / "business_router_cases.json")
        self.cases = self._read_json(dataset_dir / "system_evaluation_cases.json")

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def run(self) -> dict[str, Any]:
        results = [
            *self._evaluate_routing(),
            *self._evaluate_retrieval(),
            *self._evaluate_recommendation(),
            *self._evaluate_nutrition(),
            *self._evaluate_feedback_and_bad_case(),
        ]
        domains: dict[str, Any] = {}
        for domain in sorted({result.domain for result in results}):
            domains[domain] = summarize_results(
                [result for result in results if result.domain == domain]
            )
        return {
            "schema_version": "task19-evaluation-v1",
            "mode": "offline_deterministic",
            "environment": {
                "platform": platform.platform(),
                "python": sys.version.split()[0],
            },
            "summary": summarize_results(results),
            "domains": domains,
            "cases": [result.as_dict() for result in results],
            "limitations": [
                "No production LLM or remote data source is called by this baseline.",
                "Latency is a local service baseline, not a production capacity claim.",
            ],
        }

    def _evaluate_routing(self) -> list[EvaluationCaseResult]:
        router = BusinessRouter()
        results = []
        for index, case in enumerate(self.routing_cases, start=1):
            started = perf_counter()
            decision = router.route(case["query"])
            latency = (perf_counter() - started) * 1000
            checks = {
                "route": decision.route.value == case["expected_route"],
                "requires_weather": decision.requires_weather
                is case.get("requires_weather", False),
                "requires_meal_history": decision.requires_meal_history
                is case.get("requires_meal_history", False),
                "requires_multiple_experts": decision.requires_multiple_experts
                is case.get("requires_multiple_experts", False),
            }
            results.append(
                EvaluationCaseResult(
                    case_id=case.get("id", f"business-routing-{index:02d}"),
                    domain="business_routing",
                    passed=all(checks.values()),
                    latency_ms=latency,
                    details={"checks": checks, "actual_route": decision.route.value},
                )
            )
        return results

    def _evaluate_retrieval(self) -> list[EvaluationCaseResult]:
        results = []
        for case in self.cases["retrieval"]:
            counter = _BackendCounter(set(case["failed_sources"]))
            service = RetrievalService(
                graph_retriever=_GraphBackend(counter),
                vector_retriever=_VectorBackend(counter),
                bm25_retriever=_Bm25Backend(counter),
            )
            started = perf_counter()
            result = service.retrieve(
                RetrievalRequest(
                    query="tomato egg recipe",
                    strategy=RetrievalStrategy(case["strategy"]),
                )
            )
            latency = (perf_counter() - started) * 1000
            actual_ids = [hit.recipe_id for hit in result.hits]
            passed = (
                actual_ids == case["expected_recipe_ids"]
                and result.fallback_used is case["expected_fallback"]
            )
            results.append(
                EvaluationCaseResult(
                    case_id=case["id"],
                    domain="retrieval",
                    passed=passed,
                    latency_ms=latency,
                    tool_calls=sum(counter.calls.values()),
                    fallback_count=int(result.fallback_used),
                    details={
                        "recipe_ids": actual_ids,
                        "backend_calls": dict(counter.calls),
                        "warnings": result.warnings,
                    },
                )
            )
        return results

    def _evaluate_recommendation(self) -> list[EvaluationCaseResult]:
        results = []
        for case in self.cases["recommendation"]:
            candidates = tuple(RecipeCandidate(**item) for item in case["candidates"])
            constraints = TemporaryConstraints(**case["constraints"])
            preferences = PreferenceContext(**case["preferences"])
            started = perf_counter()
            validated = ConstraintService().validate(
                candidates, constraints, preferences
            )
            ranked = RecommendationService.rank_candidates(
                validated.accepted, constraints, preferences
            )
            latency = (perf_counter() - started) * 1000
            accepted = [item.recipe_id for item in validated.accepted]
            top = ranked[0].recipe_id if ranked else None
            passed = accepted == case["expected_accepted"] and top == case["expected_top"]
            results.append(
                EvaluationCaseResult(
                    case_id=case["id"],
                    domain="recommendation",
                    passed=passed,
                    latency_ms=latency,
                    details={
                        "accepted": accepted,
                        "top": top,
                        "rejected": {
                            item.candidate.recipe_id: list(item.reasons)
                            for item in validated.rejected
                        },
                    },
                )
            )
        return results

    def _evaluate_nutrition(self) -> list[EvaluationCaseResult]:
        results = []
        for case in self.cases["nutrition"]:
            catalog = NutritionCatalog(
                [RecipeNutritionData(**item) for item in case["catalog"]]
            )
            now = utc_now()
            history = ConfirmedMealHistory(
                user_id=1,
                records=tuple(
                    ConfirmedMealRecord(
                        recipe_id=item["recipe_id"],
                        event_type=ConfirmedMealType.CONSUME,
                        servings=item["servings"],
                        source="task19_fixture",
                        occurred_at=now,
                    )
                    for item in case["meals"]
                ),
                included_event_types=(ConfirmedMealType.CONSUME,),
                start_at=now - timedelta(days=7),
                end_at=now,
            )
            started = perf_counter()
            summary = NutritionService(catalog).summarize(history)
            latency = (perf_counter() - started) * 1000
            calories = summary.metrics["calories"].value
            passed = (
                calories == case["expected_calories"]
                and summary.data_coverage == case["expected_coverage"]
            )
            results.append(
                EvaluationCaseResult(
                    case_id=case["id"],
                    domain="nutrition",
                    passed=passed,
                    latency_ms=latency,
                    fallback_count=int(not summary.precise_metrics_available),
                    details={
                        "calories": calories,
                        "coverage": summary.data_coverage,
                        "precise_metrics_available": summary.precise_metrics_available,
                    },
                )
            )
        return results

    def _evaluate_feedback_and_bad_case(self) -> list[EvaluationCaseResult]:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        factory = create_session_factory(engine)
        with session_scope(factory) as session:
            user = UserAccount(username="task19-evaluation", password_hash="offline")
            session.add(user)
            session.flush()
            chat = ChatSession(user_id=user.id)
            session.add(chat)
            session.flush()
            message = ChatMessage(
                session_id=chat.id,
                user_id=user.id,
                role=MessageRole.ASSISTANT,
                content="offline evaluated answer",
            )
            trace = AgentRunTrace(
                run_id="task19-evaluation-run",
                user_id=user.id,
                session_id=chat.id,
                route="RECIPE_RECOMMENDATION",
                original_input="recommend dinner",
                normalized_input="recommend dinner",
            )
            session.add_all([message, trace])
            session.flush()
            user_id, session_id, message_id = user.id, chat.id, message.id

        feedback_request = AnswerFeedbackRequest(
            run_id="task19-evaluation-run",
            message_id=message_id,
            rating="DISLIKE",
            reason_tags=["CONSTRAINT_VIOLATION"],
            comment="offline idempotency fixture",
        )
        started = perf_counter()
        feedback_service = FeedbackService(factory)
        first = feedback_service.submit(user_id, feedback_request)
        repeated = feedback_service.submit(user_id, feedback_request)
        feedback_latency = (perf_counter() - started) * 1000
        with session_scope(factory) as session:
            feedback_count = session.scalar(select(func.count(InteractionFeedback.id)))
        feedback_result = EvaluationCaseResult(
            case_id="feedback-idempotent-submit",
            domain="feedback",
            passed=first.id == repeated.id and feedback_count == 1,
            latency_ms=feedback_latency,
            details={"feedback_id": first.id, "row_count": feedback_count},
        )

        bad_case_request = BadCaseEvaluationRequest(
            user_id=user_id,
            run_id="task19-evaluation-run",
            session_id=session_id,
            normalized_request="recommend dinner without peanut",
            tone_signal=ToneSignal(
                possible_frustration=0.1,
                possible_impatience=0.1,
                possible_dissatisfaction=0.1,
                repeated_request=False,
                repeated_constraint=False,
                requested_retry=False,
                explicit_error_reported=False,
                confidence=0.9,
            ),
            explicit_rating="DISLIKE",
            hard_constraint_violations=("allergen_conflict",),
        )
        started = perf_counter()
        bad_case_service = BadCaseService(factory)
        first_bad_case = bad_case_service.evaluate(bad_case_request)
        repeated_bad_case = bad_case_service.evaluate(bad_case_request)
        bad_case_latency = (perf_counter() - started) * 1000
        with session_scope(factory) as session:
            candidate_count = session.scalar(select(func.count(BadCaseCandidate.id)))
        bad_case_result = EvaluationCaseResult(
            case_id="bad-case-strong-signal-deduplication",
            domain="bad_case",
            passed=(
                first_bad_case.status is BadCaseStatus.PENDING_REVIEW
                and first_bad_case.candidate_id == repeated_bad_case.candidate_id
                and repeated_bad_case.occurrence_count == 2
                and candidate_count == 1
            ),
            latency_ms=bad_case_latency,
            details={
                "score": first_bad_case.score,
                "candidate_count": candidate_count,
                "occurrence_count": repeated_bad_case.occurrence_count,
            },
        )
        engine.dispose()
        return [feedback_result, bad_case_result]
