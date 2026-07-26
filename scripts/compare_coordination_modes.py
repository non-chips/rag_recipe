"""Reproducible offline fixed/collaborative coordination cutover evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from time import perf_counter, sleep
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recipe_assistant.agents.blackboard import CollaborationBlackboard  # noqa: E402
from recipe_assistant.agents.coordinator import (  # noqa: E402
    CollaborativeRecipeCoordinator,
    CoordinationStatus,
    RecipeCoordinator,
)
from recipe_assistant.agents.events import (  # noqa: E402
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ClaimDecision,
    EventType,
    ExpertCapability,
    TaskStatus,
    thaw_value,
)
from recipe_assistant.agents.registry import ExpertRegistry  # noqa: E402
from recipe_assistant.agents.skills import SkillContextAgent  # noqa: E402
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType  # noqa: E402
from recipe_assistant.services.skills import SkillRegistry  # noqa: E402


_SKILL_AGENT = SkillContextAgent(SkillRegistry.load(PROJECT_ROOT / "skills"))


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    route: RouteType
    category: str
    requires_weather: bool = False
    allergen: bool = False
    grounded: bool = True
    unsafe_message: bool = False
    weather_failure: bool = False


CASES = (
    EvaluationCase("knowledge_grounded", RouteType.RECIPE_KNOWLEDGE, "qa"),
    EvaluationCase(
        "knowledge_ungrounded",
        RouteType.RECIPE_KNOWLEDGE,
        "no_evidence",
        grounded=False,
    ),
    EvaluationCase("recommendation_safe", RouteType.RECIPE_RECOMMENDATION, "recommendation"),
    EvaluationCase(
        "recommendation_allergen",
        RouteType.RECIPE_RECOMMENDATION,
        "allergen",
        allergen=True,
    ),
    EvaluationCase(
        "recommendation_weather",
        RouteType.RECIPE_RECOMMENDATION,
        "weather",
        requires_weather=True,
    ),
    EvaluationCase(
        "recommendation_weather_failure",
        RouteType.RECIPE_RECOMMENDATION,
        "tool_degradation",
        requires_weather=True,
        weather_failure=True,
    ),
    EvaluationCase(
        "recommendation_unsafe",
        RouteType.RECIPE_RECOMMENDATION,
        "food_safety",
        unsafe_message=True,
    ),
    EvaluationCase("nutrition", RouteType.NUTRITION_PLANNING, "nutrition"),
)


@dataclass
class _FixtureExpert:
    case: EvaluationCase
    name: str = "offline_fixture_expert"
    capabilities: frozenset[ExpertCapability] = frozenset(
        {
            ExpertCapability.RECIPE_KNOWLEDGE,
            ExpertCapability.RECIPE_RECOMMENDATION,
            ExpertCapability.NUTRITION_PLANNING,
        }
    )
    calls: list[str] = field(default_factory=list)

    def decide(self, task: AgentTask, board) -> ClaimDecision:
        del board
        return ClaimDecision(
            expert_name=self.name,
            accepted=task.capability in self.capabilities,
            confidence=1.0,
            reason=f"offline fixture handles {task.id}",
        )

    def execute(self, task: AgentTask, board) -> AgentArtifact:
        self.calls.append(task.id)
        sleep(0.01)
        if task.id == "recommendation.weather" and self.case.weather_failure:
            raise TimeoutError("offline weather deadline")
        return AgentArtifact(
            id=f"{board.run_id}:{task.id}",
            owner=self.name,
            kind=task.expected_artifacts[0],
            payload=self._payload(task),
            confidence=1.0,
            task_id=task.id,
        )

    def _payload(self, task: AgentTask) -> dict[str, Any]:
        if task.id == "knowledge.extract_constraints":
            return {"query": "test", "topics": ("general",)}
        if task.id == "knowledge.retrieve":
            return {
                "query": "test",
                "items": (self._evidence(),) if self.case.grounded else (),
                "retrieval_confidence": 1.0 if self.case.grounded else 0.0,
                "sufficient": self.case.grounded,
                "degraded": not self.case.grounded,
            }
        if task.id == "knowledge.evidence_check":
            return {
                "sufficient": self.case.grounded,
                "evidence_count": 1 if self.case.grounded else 0,
            }
        if task.id == "knowledge.response_plan":
            return {
                "answer_mode": "evidence_grounded_recipe_knowledge",
                "message": "Tomato noodles cook in fifteen minutes.",
                "evidence": (self._evidence(),) if self.case.grounded else (),
            }
        if task.id == "recommendation.extract_constraints":
            return {}
        if task.id == "recommendation.weather":
            return {"available": True, "city": "test", "condition": "clear"}
        if task.id == "recommendation.preferences":
            return {"allergens": ("peanut",) if self.case.allergen else ()}
        if task.id in {"recommendation.retrieve", "recommendation.rank"}:
            return {
                "stage": "recalled" if task.id.endswith("retrieve") else "ranked",
                "candidates": () if self.case.unsafe_message else (self._candidate(),),
                "warnings": (),
            }
        if task.id == "recommendation.validate":
            candidates = () if self.case.unsafe_message else (self._candidate(),)
            return {
                "accepted": candidates,
                "rejected": (),
                "hard_constraints_applied": ("data_source",),
            }
        if task.id == "recommendation.response_plan":
            return {
                "answer_mode": "constraint_checked_recommendation",
                "message": (
                    "Raw chicken is safe without cooking."
                    if self.case.unsafe_message
                    else "Safe grounded recommendation."
                ),
                "candidates": (
                    () if self.case.unsafe_message else (self._candidate(),)
                ),
            }
        if task.id == "nutrition.meal_history":
            return {"user_id": 1, "records": (), "included_event_types": ("CONSUME",)}
        if task.id == "nutrition.summary":
            return {"confirmed_meal_count": 0, "data_coverage": 0.0}
        if task.id == "nutrition.guidance":
            return {"based_on_confirmed_meals": 0, "recommendations": ()}
        if task.id == "nutrition.response_plan":
            return {
                "answer_mode": "food_category_diversity_only",
                "message": "Nutrition guidance requires confirmed meal data.",
            }
        raise ValueError(f"unsupported fixture task: {task.id}")

    def _candidate(self) -> dict[str, Any]:
        ingredients = ("noodles", "peanut") if self.case.allergen else (
            "noodles",
            "tomato",
        )
        return {
            "recipe_id": self.case.case_id,
            "recipe_name": "Fixture recipe",
            "ingredients": ingredients,
            "tools": ("pot",),
            "cook_time_minutes": 15,
            "source_path": f"recipes/{self.case.case_id}.md",
            "evidence": "Grounded fixture recipe evidence.",
        }

    def _evidence(self) -> dict[str, Any]:
        return {
            "recipe_id": self.case.case_id,
            "recipe_name": "Fixture recipe",
            "content": "Grounded fixture recipe evidence.",
            "source_path": f"recipes/{self.case.case_id}.md",
        }


class CoordinationModeEvaluator:
    def __init__(self, cases: tuple[EvaluationCase, ...] = CASES) -> None:
        self.cases = cases

    def run(self) -> dict[str, Any]:
        modes = {
            "fixed": self._run_mode("fixed"),
            "collaborative": self._run_mode("collaborative"),
        }
        fixed = modes["fixed"]["metrics"]
        collaborative = modes["collaborative"]["metrics"]
        p95_ratio = (
            collaborative["latency_ms"]["p95"] / fixed["latency_ms"]["p95"]
            if fixed["latency_ms"]["p95"]
            else 1.0
        )
        gates = {
            "critical_cases_100_percent": collaborative["case_pass_rate"] == 1.0,
            "hard_constraint_violations_zero": (
                collaborative["hard_constraint_violations"] == 0
            ),
            "ungrounded_fact_rate_not_worse": (
                collaborative["ungrounded_fact_rate"]
                <= fixed["ungrounded_fact_rate"]
            ),
            "p95_latency_within_1_25x": p95_ratio <= 1.25,
            "infinite_loops_zero": collaborative["infinite_loops"] == 0,
            "bad_case_traceability_100_percent": (
                collaborative["bad_case_traceability"] == 1.0
            ),
        }
        return {
            "schema_version": "coordination-cutover-v1",
            "methodology": {
                "mode": "offline_deterministic_fixture",
                "case_count": len(self.cases),
                "case_ids": [case.case_id for case in self.cases],
                "latency_note": "Common domain tasks include a 10ms deterministic I/O fixture.",
                "tool_call_note": (
                    "Offline tool_calls is the deterministic domain-execution "
                    "count proxy; live ToolRegistry calls remain available in tool trace."
                ),
            },
            "modes": modes,
            "comparison": {"collaborative_to_fixed_p95_ratio": round(p95_ratio, 6)},
            "gates": gates,
            "cutover_approved": all(gates.values()),
            "decommission": {
                "default_mode": "collaborative" if all(gates.values()) else "fixed",
                "fixed_deletion_approved": False,
                "blockers": [
                    "Task 01-05 worktree has no new committed backup/tag.",
                    "Production zero-fixed-traffic observation period is not yet available.",
                ],
            },
        }

    def _run_mode(self, mode: str) -> dict[str, Any]:
        results = [self._run_case(mode, case) for case in self.cases]
        latencies = sorted(item["latency_ms"] for item in results)
        violations = sum(item["hard_constraint_violations"] for item in results)
        ungrounded = sum(item["ungrounded_facts"] for item in results)
        expected_bad_cases = sum(item["expected_bad_case"] for item in results)
        traced_bad_cases = sum(item["bad_case_traced"] for item in results)
        return {
            "metrics": {
                "case_pass_rate": sum(item["passed"] for item in results) / len(results),
                "hard_constraint_violations": violations,
                "ungrounded_fact_rate": ungrounded / len(results),
                "latency_ms": {
                    "p50": round(median(latencies), 3),
                    "p95": round(latencies[int((len(latencies) - 1) * 0.95)], 3),
                },
                "tool_calls": sum(item["tool_calls"] for item in results),
                "degradation_rate": (
                    sum(item["degraded"] for item in results) / len(results)
                ),
                "bad_case_hit_rate": traced_bad_cases / len(results),
                "bad_case_traceability": (
                    traced_bad_cases / expected_bad_cases
                    if expected_bad_cases
                    else 1.0
                ),
                "infinite_loops": sum(item["infinite_loop"] for item in results),
            },
            "cases": results,
        }

    @staticmethod
    def _run_case(mode: str, case: EvaluationCase) -> dict[str, Any]:
        expert = _FixtureExpert(case)
        coordinator = (
            RecipeCoordinator(ExpertRegistry([expert]))
            if mode == "fixed"
            else CollaborativeRecipeCoordinator(
                ExpertRegistry([expert, _SKILL_AGENT])
            )
        )
        board = CollaborationBlackboard(
            run_id=f"cutover-{mode}-{case.case_id}",
            user_id=1,
            session_id=f"cutover-{case.case_id}",
            user_input=case.case_id,
            route=RouteDecision(
                route=case.route,
                confidence=1.0,
                reason="offline cutover fixture",
                requires_weather=case.requires_weather,
            ),
        )
        started = perf_counter()
        outcome = coordinator.coordinate(board)
        latency_ms = (perf_counter() - started) * 1000
        final_payload = thaw_value(outcome.final_artifact.payload)
        candidates = tuple(final_payload.get("candidates", ()))
        violations = sum(
            case.allergen
            and "peanut"
            in {
                str(ingredient).casefold()
                for ingredient in candidate.get("ingredients", ())
            }
            for candidate in candidates
        )
        ungrounded = int(
            "evidence_grounded" in str(final_payload.get("answer_mode") or "")
            and bool(final_payload.get("message"))
            and not final_payload.get("evidence")
        )
        bad_case_traced = int(
            any(
                event.event_type is EventType.BAD_CASE_CANDIDATE
                for event in outcome.blackboard.events
            )
        )
        expected_bad_case = int(
            mode == "collaborative" and (not case.grounded or case.unsafe_message)
        )
        if mode == "collaborative":
            passed = (
                violations == 0
                and ungrounded == 0
                and (not expected_bad_case or bad_case_traced == 1)
                and (
                    expected_bad_case
                    or outcome.final_artifact.kind is ArtifactKind.RESPONSE_PROPOSAL
                )
            )
        else:
            passed = not violations and not ungrounded and not case.unsafe_message
        open_tasks = [
            task.id
            for task in outcome.blackboard.tasks.values()
            if task.status in {TaskStatus.OPEN, TaskStatus.CLAIMED, TaskStatus.RUNNING}
        ]
        return {
            "id": case.case_id,
            "category": case.category,
            "passed": bool(passed),
            "latency_ms": round(latency_ms, 3),
            "tool_calls": len(expert.calls),
            "degraded": outcome.status is CoordinationStatus.DEGRADED,
            "hard_constraint_violations": int(violations),
            "ungrounded_facts": ungrounded,
            "expected_bad_case": expected_bad_case,
            "bad_case_traced": bad_case_traced,
            "infinite_loop": int(bool(open_tasks)),
            "final_kind": outcome.final_artifact.kind.value,
            "event_count": len(outcome.blackboard.events),
        }


def write_reports(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "coordination_cutover_report.json"
    markdown_path = output_dir / "coordination_cutover_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fixed = report["modes"]["fixed"]["metrics"]
    collaborative = report["modes"]["collaborative"]["metrics"]
    gate_lines = "\n".join(
        f"| {name} | {'PASS' if passed else 'FAIL'} |"
        for name, passed in report["gates"].items()
    )
    markdown_path.write_text(
        "\n".join(
            [
                "# Fixed 与 Collaborative 协调模式切换评测",
                "",
                "## 指标",
                "",
                "| 指标 | fixed | collaborative |",
                "| --- | ---: | ---: |",
                f"| 用例通过率 | {fixed['case_pass_rate']:.2%} | "
                f"{collaborative['case_pass_rate']:.2%} |",
                f"| 硬约束违反数 | {fixed['hard_constraint_violations']} | "
                f"{collaborative['hard_constraint_violations']} |",
                f"| 无证据事实率 | {fixed['ungrounded_fact_rate']:.2%} | "
                f"{collaborative['ungrounded_fact_rate']:.2%} |",
                f"| P50 延迟(ms) | {fixed['latency_ms']['p50']} | "
                f"{collaborative['latency_ms']['p50']} |",
                f"| P95 延迟(ms) | {fixed['latency_ms']['p95']} | "
                f"{collaborative['latency_ms']['p95']} |",
                f"| Tool/领域执行代理次数 | {fixed['tool_calls']} | "
                f"{collaborative['tool_calls']} |",
                f"| 降级率 | {fixed['degradation_rate']:.2%} | "
                f"{collaborative['degradation_rate']:.2%} |",
                f"| Bad case 命中率 | {fixed['bad_case_hit_rate']:.2%} | "
                f"{collaborative['bad_case_hit_rate']:.2%} |",
                "",
                "## 切换门槛",
                "",
                "| 门槛 | 结果 |",
                "| --- | --- |",
                gate_lines,
                "",
                f"**切换结论：{'APPROVED' if report['cutover_approved'] else 'BLOCKED'}**",
                "",
                "Fixed 删除结论：**DEFERRED**。当前保留显式回退，等待提交备份和"
                "生产零调用观察证据。",
                "",
                "复现命令：",
                "",
                "```powershell",
                "D:\\Anaconda\\envs\\rag\\python.exe "
                "scripts\\compare_coordination_modes.py",
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "reports",
    )
    args = parser.parse_args()
    report = CoordinationModeEvaluator().run()
    write_reports(report, args.output_dir)
    print(json.dumps(report["gates"], ensure_ascii=False, indent=2))
    return 0 if report["cutover_approved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
