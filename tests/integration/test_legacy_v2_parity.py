from __future__ import annotations

import json
from pathlib import Path

from scripts.compare_legacy_vs_v2 import ParityEvaluator, main, write_reports


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET = PROJECT_ROOT / "tests" / "datasets" / "legacy_v2_parity_cases.json"


def test_dataset_covers_required_task21_capabilities() -> None:
    payload = json.loads(DATASET.read_text(encoding="utf-8"))
    categories = {case["category"] for case in payload["cases"]}

    assert {
        "simple_chat",
        "knowledge",
        "recommendation",
        "weather",
        "hard_constraint",
        "multi_turn_memory",
        "nutrition",
        "feedback",
        "bad_case",
        "degradation",
        "api_contract",
        "data_consistency",
        "runtime_wiring",
    } <= categories
    assert len(payload["cases"]) >= 20


def test_parity_report_reaches_p0_p1_gate_before_task22() -> None:
    parity, performance = ParityEvaluator(DATASET).run()
    by_id = {case["id"]: case for case in parity["cases"]}

    assert by_id["exclude_001"]["passed"] is True
    assert by_id["allergen_001"]["passed"] is True
    assert by_id["session_001"]["passed"] is True
    assert by_id["meal_query_001"]["passed"] is True
    assert by_id["feedback_001"]["passed"] is True
    assert by_id["retrieval_degrade_001"]["passed"] is True

    assert by_id["api_feedback_001"]["passed"] is True
    assert by_id["api_bad_case_admin_001"]["passed"] is True
    assert by_id["v2_runtime_direct_001"]["passed"] is True
    assert by_id["default_runtime_001"]["passed"] is True
    assert by_id["default_runtime_001"]["v2"]["data"]["uses_v2_runtime"] is False
    assert parity["status"] == "PASSED"
    assert parity["summary"]["by_severity"]["P0"]["pass_rate"] == 1.0
    assert parity["summary"]["by_severity"]["P1"]["pass_rate"] == 1.0
    assert performance["legacy"]["latency_ms"]["p50"] >= 0
    assert performance["v2"]["latency_ms"]["p95"] >= 0
    assert performance["v2"]["call_counts"]


def test_report_writer_and_cli_return_passed_status(tmp_path: Path) -> None:
    parity, performance = ParityEvaluator(DATASET).run()
    write_reports(parity, performance, tmp_path)

    parity_path = tmp_path / "legacy_v2_parity_report.json"
    performance_path = tmp_path / "legacy_v2_performance_report.json"
    assert parity_path.exists()
    assert performance_path.exists()
    assert json.loads(parity_path.read_text(encoding="utf-8"))["status"] == "PASSED"
    assert main(["--dataset", str(DATASET), "--output-dir", str(tmp_path)]) == 0
