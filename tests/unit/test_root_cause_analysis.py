from __future__ import annotations

from recipe_assistant.schemas.api.bad_case_admin import (
    BadCaseCategory,
    RootCauseContext,
)
from recipe_assistant.services.root_cause_analysis import RootCauseAnalysisService


def test_constraint_violation_suggestion_is_explainable_and_non_final() -> None:
    suggestion = RootCauseAnalysisService().suggest(
        RootCauseContext(
            candidate_id=1,
            triggers=("HARD_CONSTRAINT_VIOLATION", "EMPTY_RETRIEVAL"),
            route="RECIPE_RECOMMENDATION",
            hard_constraint_violations=("allergen_conflict",),
        )
    )

    assert suggestion.possible_category is BadCaseCategory.CONSTRAINT_VIOLATION
    assert suggestion.confidence == 0.95
    assert "allergen_conflict" in suggestion.evidence
    assert "可能" in suggestion.explanation
    assert "不是最终根因结论" in suggestion.explanation


def test_tool_failure_and_retrieval_miss_use_trace_evidence() -> None:
    service = RootCauseAnalysisService()
    tool = service.suggest(
        RootCauseContext(
            candidate_id=1,
            route="RECIPE_KNOWLEDGE",
            events=({"type": "tool_error", "tool": "search"},),
            sources=(),
        )
    )
    retrieval = service.suggest(
        RootCauseContext(
            candidate_id=2,
            route="RECIPE_KNOWLEDGE",
            sources=(),
        )
    )

    assert tool.possible_category is BadCaseCategory.TOOL_FAILURE
    assert tool.affected_component == "Tool Adapter / external dependency"
    assert retrieval.possible_category is BadCaseCategory.RETRIEVAL_MISS
    assert "retriever filters" in retrieval.suggested_inspection_points


def test_unknown_case_stays_low_confidence_other() -> None:
    suggestion = RootCauseAnalysisService().suggest(RootCauseContext(candidate_id=3))
    assert suggestion.possible_category is BadCaseCategory.OTHER
    assert suggestion.confidence < 0.5
