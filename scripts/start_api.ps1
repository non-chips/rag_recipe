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
$HostAddress = if ($env:API_HOST) { $env:API_HOST } else { "127.0.0.1" }
$Port = if ($env:API_PORT) { $env:API_PORT } else { "8000" }

Set-Location $ProjectRoot
& $PythonCommand -m uvicorn recipe_assistant.main:app --host $HostAddress --port $Port
