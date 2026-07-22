"""Shared, dependency-free metrics for offline system evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import ceil
from typing import Any


@dataclass(slots=True)
class EvaluationCaseResult:
    case_id: str
    domain: str
    passed: bool
    latency_ms: float
    model_calls: int = 0
    tool_calls: int = 0
    fallback_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def percentile(values: list[float], quantile: float) -> float:
    """Return a deterministic nearest-rank percentile."""

    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, ceil(quantile * len(ordered)))
    return round(ordered[rank - 1], 3)


def summarize_results(results: list[EvaluationCaseResult]) -> dict[str, Any]:
    latencies = [result.latency_ms for result in results]
    passed = sum(result.passed for result in results)
    return {
        "case_count": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
        },
        "model_calls": sum(result.model_calls for result in results),
        "tool_calls": sum(result.tool_calls for result in results),
        "fallback_count": sum(result.fallback_count for result in results),
    }
