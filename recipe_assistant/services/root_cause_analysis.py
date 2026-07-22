"""Rule-first possible root cause suggestions for developer review."""

from __future__ import annotations

from recipe_assistant.schemas.api.bad_case_admin import (
    BadCaseCategory,
    RootCauseContext,
    RootCauseSuggestion,
)


class RootCauseAnalysisService:
    """Produce explainable suggestions, never final developer conclusions."""

    def __init__(self, latency_threshold_ms: float = 5000.0) -> None:
        self.latency_threshold_ms = latency_threshold_ms

    def suggest(self, context: RootCauseContext) -> RootCauseSuggestion:
        triggers = set(context.triggers)
        signal_types = set(context.implicit_signal_types)
        event_text = " ".join(str(event).casefold() for event in context.events)
        if context.hard_constraint_violations or "HARD_CONSTRAINT_VIOLATION" in triggers:
            evidence = list(context.hard_constraint_violations) or [
                "candidate trigger includes HARD_CONSTRAINT_VIOLATION"
            ]
            return self._result(
                BadCaseCategory.CONSTRAINT_VIOLATION,
                0.95,
                "ConstraintService / recommendation filtering",
                evidence,
                ("constraint extraction", "hard-filter result", "candidate ingredients"),
            )
        if "TOOL_FAILURE" in triggers or "tool_error" in event_text:
            return self._result(
                BadCaseCategory.TOOL_FAILURE,
                0.90,
                "Tool Adapter / external dependency",
                ("Trace contains a tool failure signal",),
                ("tool request parameters", "adapter exception", "retry policy"),
            )
        if "EMPTY_RETRIEVAL" in triggers or (
            not context.sources and context.route not in {"", "SIMPLE"}
        ):
            return self._result(
                BadCaseCategory.RETRIEVAL_MISS,
                0.85,
                "RetrievalService",
                ("retrieval returned no usable source",),
                ("normalized query", "retriever filters", "source index coverage"),
            )
        if (
            context.latency_ms is not None
            and context.latency_ms >= self.latency_threshold_ms
        ):
            return self._result(
                BadCaseCategory.LATENCY,
                0.80,
                "Agent runtime / tool latency",
                (f"Trace latency was {context.latency_ms:.0f} ms",),
                ("per-tool timing", "model latency", "network timeout"),
            )
        if signal_types & {
            "POSSIBLE_IMPATIENCE",
            "POSSIBLE_DISSATISFACTION",
            "REQUESTED_RETRY",
        }:
            return self._result(
                BadCaseCategory.STYLE_MISMATCH,
                0.55,
                "Answer composition",
                ("interaction contains a style-related weak signal",),
                ("answer length", "instruction adherence", "response structure"),
            )
        return self._result(
            BadCaseCategory.OTHER,
            0.30,
            None,
            ("available Trace evidence does not isolate one component",),
            ("route decision", "tool timeline", "retrieval sources", "answer evidence"),
        )

    @staticmethod
    def _result(
        category: BadCaseCategory,
        confidence: float,
        component: str | None,
        evidence: tuple[str, ...] | list[str],
        inspection_points: tuple[str, ...],
    ) -> RootCauseSuggestion:
        return RootCauseSuggestion(
            possible_category=category,
            confidence=confidence,
            affected_component=component,
            evidence=tuple(evidence),
            suggested_inspection_points=inspection_points,
            explanation=(
                f"根据当前 Trace 与反馈证据，可能属于 {category.value}；"
                "该结果仅供开发者检查，不是最终根因结论。"
            ),
        )
