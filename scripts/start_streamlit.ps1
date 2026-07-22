$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
& (Join-Path $PSScriptRoot "check_environment.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$NamedCondaPython = Join-Path (Split-Path (Get-Command python).Source -Parent) "envs\rag\python.exe"
$PythonCommand = if ($env:PROJECT_PYTHON -and (Test-Path $env:PROJECT_PYTHON)) {
    $env:PROJECT_PYTHON
} elseif ($env:CONDA_PREFIX -and (Test-Path (Join-Path $env:CONDA_PREFIX "python.exe"))) {
    Join-Path $env:CONDA_PREFIX "python.exe"
} elseif (Test-Path (Join-Path $ProjectRoot ".venv\Scripts\python.exe")) {
    Join-Path $ProjectRoot ".venv\Scripts\python.exe"
} elseif (Test-Path $NamedCondaPython) {
    $NamedCondaPython
} else {
    (Get-Command python).Source
}
if (-not $env:FRONTEND_API_BASE_URL) {
    $env:FRONTEND_API_BASE_URL = "http://127.0.0.1:8000"
}
$Port = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { "8501" }

Set-Location $ProjectRoot
& $PythonCommand -m streamlit run frontend\streamlit_app.py --server.port $Port
