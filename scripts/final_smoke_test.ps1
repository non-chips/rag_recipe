[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Candidates = @()
if ($env:PROJECT_PYTHON) { $Candidates += $env:PROJECT_PYTHON }
if ($env:CONDA_PREFIX) { $Candidates += (Join-Path $env:CONDA_PREFIX "python.exe") }
$Candidates += (Join-Path $ProjectRoot ".venv\Scripts\python.exe")
$Candidates += "D:\Anaconda\envs\rag\python.exe"
$ResolvedPython = Get-Command python -ErrorAction SilentlyContinue
if ($ResolvedPython) { $Candidates += $ResolvedPython.Source }

$PythonCommand = $null
foreach ($Candidate in ($Candidates | Select-Object -Unique)) {
    if (-not (Test-Path $Candidate)) { continue }
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & $Candidate -c "import fastapi, pytest, sqlalchemy, pydantic" 2>$null
    $Usable = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $PreviousPreference
    if ($Usable) {
        $PythonCommand = $Candidate
        break
    }
}
if (-not $PythonCommand) {
    throw "No Python interpreter with the required smoke-test packages was found"
}

$Cases = @(
    @{ Name = "health_and_resources"; Node = "tests/contract/test_resource_api.py::test_lifespan_health_and_basic_resource_round_trip" },
    @{ Name = "chat_sse"; Node = "tests/e2e/test_chat_api.py::test_chat_sse_persists_session_messages_and_trace" },
    @{ Name = "session_profile_trace"; Node = "tests/integration/test_chat_service.py::test_chat_service_creates_and_restores_session_with_profile_history_and_trace" },
    @{ Name = "recipe_knowledge"; Node = "tests/e2e/test_recipe_qa_flow.py::test_recipe_question_runs_through_real_knowledge_expert" },
    @{ Name = "recommendation_constraints"; Node = "tests/e2e/test_weather_recommendation_flow.py::test_weather_recommendation_filters_allergens_and_supplements_evidence" },
    @{ Name = "weather_degradation"; Node = "tests/e2e/test_weather_recommendation_flow.py::test_weather_failure_does_not_block_safe_recommendations" },
    @{ Name = "nutrition_report"; Node = "tests/integration/test_nutrition_report.py::test_nutrition_expert_publishes_source_aware_json_report" },
    @{ Name = "query_consume_guard"; Node = "tests/contract/test_resource_api.py::test_meal_confirmation_rejects_query_events" },
    @{ Name = "feedback"; Node = "tests/integration/test_feedback_api.py::test_feedback_api_submits_recovers_and_updates_idempotently" },
    @{ Name = "bad_case_review"; Node = "tests/e2e/test_bad_case_review_flow.py::test_developer_review_to_verified_preserves_full_audit_chain" },
    @{ Name = "retrieval_degradation"; Node = "tests/unit/test_retrieval_service.py::test_hybrid_retrieval_degrades_when_graph_and_bm25_fail" },
    @{ Name = "tool_governance"; Node = "tests/unit/test_tool_governance.py::test_validation_and_service_failures_are_traced" },
    @{ Name = "v2_startup_isolation"; Node = "tests/integration/test_v2_startup_without_legacy.py::test_v2_container_startup_does_not_load_or_register_legacy" },
    @{ Name = "mcp_recipe_search"; Node = "tests/integration/test_mcp_tools.py::test_recipe_search_matches_local_tool_service_semantics" },
    @{ Name = "v2_only_configuration"; Node = "tests/integration/test_runtime_mode_switch.py::test_v2_is_the_only_runtime_mode" }
)

$Results = @()
$TotalWatch = [System.Diagnostics.Stopwatch]::StartNew()
Push-Location $ProjectRoot
try {
    foreach ($Case in $Cases) {
        $Watch = [System.Diagnostics.Stopwatch]::StartNew()
        & $PythonCommand -m pytest $Case.Node -q
        $ExitCode = $LASTEXITCODE
        $Watch.Stop()
        $Passed = $ExitCode -eq 0
        $Results += [ordered]@{
            name = $Case.Name
            node = $Case.Node
            passed = $Passed
            duration_ms = [math]::Round($Watch.Elapsed.TotalMilliseconds, 3)
        }
        if (-not $Passed) {
            throw "Smoke case failed: $($Case.Name)"
        }
        Write-Host "[OK] $($Case.Name)" -ForegroundColor Green
    }

    $DataScript = @'
import json
import sqlite3
from pathlib import Path

from recipe_assistant.core.config import Settings

root = Path.cwd()
db_path = root / "storage" / "recipe_assistant.db"
connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
required_tables = {
    "chat_sessions", "chat_messages", "user_profiles", "recipe_interactions",
    "interaction_feedback", "bad_case_candidates", "agent_run_traces",
}
tables = {
    row[0]
    for row in connection.execute(
        "select name from sqlite_master where type='table'"
    )
}
missing = sorted(required_tables - tables)
if missing:
    raise SystemExit(f"missing SQLite tables: {missing}")

counts = {
    table: connection.execute(f"select count(*) from {table}").fetchone()[0]
    for table in sorted(required_tables)
}
interaction_types = dict(
    connection.execute(
        "select event_type, count(*) from recipe_interactions group by event_type"
    ).fetchall()
)
invalid_types = sorted(set(interaction_types) - {"QUERY", "COOK", "CONSUME"})
if invalid_types:
    raise SystemExit(f"invalid interaction types: {invalid_types}")
connection.close()

chroma_root = root / "storage" / "chroma_db"
chroma_files = [path for path in chroma_root.rglob("*") if path.is_file()]
if not chroma_files:
    raise SystemExit("Chroma index files are missing")

nutrition_path = root / "data" / "nutrition" / "recipes.json"
nutrition_payload = json.loads(nutrition_path.read_text(encoding="utf-8"))
if not isinstance(nutrition_payload, (list, dict)):
    raise SystemExit("nutrition catalog has an invalid root type")
nutrition_count = len(
    nutrition_payload.get("recipes", [])
    if isinstance(nutrition_payload, dict)
    else nutrition_payload
)

settings = Settings(_env_file=None)
graph_sources = [
    root / "graph" / "graph_retriever.py",
    root / "graph" / "neo4j_client.py",
    root / "graph" / "graph_builder.py",
]
if not all(path.is_file() for path in graph_sources):
    raise SystemExit("Neo4j adapter or rebuild source is missing")

print(json.dumps({
    "sqlite": {
        "path": str(db_path),
        "required_tables_present": True,
        "row_counts": counts,
        "interaction_types": interaction_types,
        "query_consume_semantics": "QUERY remains a distinct event type; API guard smoke passed",
    },
    "chroma": {
        "path": str(chroma_root),
        "file_count": len(chroma_files),
        "bytes": sum(path.stat().st_size for path in chroma_files),
    },
    "nutrition": {
        "path": str(nutrition_path),
        "recipe_count": nutrition_count,
        "structure_valid": True,
        "coverage_status": "available" if nutrition_count else "empty_requires_import",
    },
    "neo4j": {
        "enabled": settings.neo4j_enabled,
        "adapter_and_rebuild_sources_present": True,
        "live_connectivity_checked": False,
        "reason": "disabled by default; Task20 has no external database dump",
    },
}, ensure_ascii=False))
'@
    $DataValidation = ($DataScript | & $PythonCommand - | ConvertFrom-Json)
    if ($LASTEXITCODE -ne 0) {
        throw "Read-only data validation failed"
    }
    Write-Host "[OK] SQLite/Chroma/Nutrition/Neo4j read-only validation" -ForegroundColor Green
} finally {
    Pop-Location
    $TotalWatch.Stop()
}

$Report = [ordered]@{
    schema_version = 1
    task = "task_25"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    python = $PythonCommand
    smoke = [ordered]@{
        total = $Cases.Count
        passed = @($Results | Where-Object { $_.passed }).Count
        failed = @($Results | Where-Object { -not $_.passed }).Count
        duration_ms = [math]::Round($TotalWatch.Elapsed.TotalMilliseconds, 3)
        cases = $Results
    }
    data_validation = $DataValidation
}
$ReportPath = Join-Path $ProjectRoot "reports\final_performance.json"
$Report | ConvertTo-Json -Depth 10 | Set-Content -Path $ReportPath -Encoding utf8
Write-Host "Final 15-flow smoke and data validation passed." -ForegroundColor Green
