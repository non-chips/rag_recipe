"""Read-only CLI for inspecting recent Agent traces and Bad Case candidates."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "storage" / "recipe_assistant.db"


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _connect(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {database}")
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _trace_summary(row: sqlite3.Row) -> dict[str, Any]:
    events = _json_value(row["events_json"], [])
    llm_events = [
        event
        for event in events
        if event.get("type") == "llm_call"
        or event.get("event_type") == "LLM_COMPLETED"
    ]
    final_events = [
        event
        for event in events
        if event.get("event_type")
        in {"FINAL_ACCEPTED", "BAD_CASE_CANDIDATE"}
    ]
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "route": row["route"],
        "input": row["normalized_input"],
        "latency_ms": row["latency_ms"],
        "token_usage": _json_value(row["token_usage_json"], {}),
        "llm_calls": len(llm_events),
        "llm_fallbacks": sum(
            event.get("llm_used") is False
            or (event.get("metadata") or {}).get("llm_used") is False
            for event in llm_events
        ),
        "final_status": (
            final_events[-1].get("event_type") if final_events else "UNKNOWN"
        ),
        "created_at": row["created_at"],
    }


def list_traces(connection: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, run_id, route, normalized_input, events_json,
               latency_ms, token_usage_json, created_at
        FROM agent_run_traces
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_trace_summary(row) for row in rows]


def get_trace(
    connection: sqlite3.Connection,
    run_id: str,
) -> dict[str, Any] | None:
    if run_id == "latest":
        row = connection.execute(
            "SELECT * FROM agent_run_traces ORDER BY id DESC LIMIT 1"
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT * FROM agent_run_traces WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    for field, fallback in {
        "events_json": [],
        "tasks_json": [],
        "artifacts_json": [],
        "sources_json": [],
        "token_usage_json": {},
    }.items():
        result[field.removesuffix("_json")] = _json_value(
            result.pop(field),
            fallback,
        )
    return result


def list_bad_cases(
    connection: sqlite3.Connection,
    limit: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, status, score, normalized_request, trigger_types_json,
               first_run_id, latest_run_id, occurrence_count,
               created_at, updated_at
        FROM bad_case_candidates
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    values = []
    for row in rows:
        item = dict(row)
        item["trigger_types"] = _json_value(
            item.pop("trigger_types_json"),
            [],
        )
        values.append(item)
    return values


def _print_trace_table(traces: list[dict[str, Any]]) -> None:
    print(f"\n最近 Trace（{len(traces)} 条）")
    if not traces:
        print("  暂无 Trace。")
        return
    for trace in traces:
        text = str(trace["input"]).replace("\n", " ")
        if len(text) > 44:
            text = f"{text[:41]}..."
        print(
            f"  #{trace['id']} {trace['run_id']} "
            f"[{trace['route']}] {trace['final_status']} "
            f"{trace['latency_ms']:.1f}ms"
        )
        print(
            f"     LLM={trace['llm_calls']} "
            f"fallback={trace['llm_fallbacks']}  {text}"
        )


def _print_bad_case_table(cases: list[dict[str, Any]]) -> None:
    print(f"\nBad Case（{len(cases)} 条）")
    if not cases:
        print("  暂无 Bad Case。")
        return
    for case in cases:
        text = str(case["normalized_request"]).replace("\n", " ")
        if len(text) > 52:
            text = f"{text[:49]}..."
        print(
            f"  #{case['id']} [{case['status']}] "
            f"score={case['score']:.3f} occurrences={case['occurrence_count']}"
        )
        print(
            f"     run={case['latest_run_id']} "
            f"triggers={case['trigger_types']}  {text}"
        )


def _write_json(value: Any, output: Path | None) -> None:
    serialized = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if output is None:
        print(serialized)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")
    print(f"已写入：{output.resolve()}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="快速查看 Agent trace 与 Bad Case（只读 SQLite）。"
    )
    parser.add_argument(
        "--view",
        choices=("summary", "trace", "badcase"),
        default="summary",
    )
    parser.add_argument(
        "--run-id",
        default="latest",
        help="--view trace 时使用；默认为 latest。",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args()
    if args.limit < 1:
        raise SystemExit("--limit 必须大于 0")

    try:
        with _connect(args.database.resolve()) as connection:
            if args.view == "trace":
                value = get_trace(connection, args.run_id)
                if value is None:
                    print(f"未找到 run_id={args.run_id} 的 Trace。", file=sys.stderr)
                    return 2
                _write_json(value, args.output)
                return 0

            if args.view == "badcase":
                cases = list_bad_cases(connection, args.limit)
                if args.as_json or args.output:
                    _write_json(cases, args.output)
                else:
                    _print_bad_case_table(cases)
                return 0

            result = {
                "traces": list_traces(connection, args.limit),
                "bad_cases": list_bad_cases(connection, args.limit),
            }
            if args.as_json or args.output:
                _write_json(result, args.output)
            else:
                _print_trace_table(result["traces"])
                _print_bad_case_table(result["bad_cases"])
            return 0
    except (OSError, sqlite3.Error) as exc:
        print(f"诊断读取失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
