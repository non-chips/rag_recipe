$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TempRoot = Join-Path $ProjectRoot ".tmp\windows-smoke"
New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null

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

function Wait-HttpOk {
    param([string]$Url, [int]$TimeoutSeconds = 30)
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        try {
            $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($Response.StatusCode -eq 200) { return $Response }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    throw "Timed out waiting for $Url"
}

$ApiPort = if ($env:SMOKE_API_PORT) { $env:SMOKE_API_PORT } else { "8765" }
$FrontendPort = if ($env:SMOKE_FRONTEND_PORT) { $env:SMOKE_FRONTEND_PORT } else { "8766" }
$env:DATABASE_URL = "sqlite:///$((Join-Path $TempRoot 'recipe_assistant.db').Replace('\', '/'))"
$env:FRONTEND_API_BASE_URL = "http://127.0.0.1:$ApiPort"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
$ApiProcess = $null
$FrontendProcess = $null

try {
    Set-Location $ProjectRoot
    $ApiProcess = Start-Process -FilePath $PythonCommand -ArgumentList @(
        "-m", "uvicorn", "recipe_assistant.main:app",
        "--host", "127.0.0.1", "--port", $ApiPort
    ) -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $TempRoot "api.stdout.log") `
        -RedirectStandardError (Join-Path $TempRoot "api.stderr.log")
    $Health = Wait-HttpOk "http://127.0.0.1:$ApiPort/actuator/health"
    $HealthBody = $Health.Content | ConvertFrom-Json
    if ($HealthBody.status -ne "UP") { throw "FastAPI health status is not UP" }
    Write-Host "[OK] FastAPI smoke - /actuator/health is UP" -ForegroundColor Green

    $FrontendProcess = Start-Process -FilePath $PythonCommand -ArgumentList @(
        "-m", "streamlit", "run", "frontend\streamlit_app.py",
        "--server.address", "127.0.0.1", "--server.port", $FrontendPort,
        "--server.headless", "true"
    ) -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $TempRoot "streamlit.stdout.log") `
        -RedirectStandardError (Join-Path $TempRoot "streamlit.stderr.log")
    $null = Wait-HttpOk "http://127.0.0.1:$FrontendPort/_stcore/health"
    Write-Host "[OK] Streamlit smoke - /_stcore/health is healthy" -ForegroundColor Green
    Write-Host "Windows no-container smoke passed." -ForegroundColor Green
} finally {
    foreach ($Process in @($FrontendProcess, $ApiProcess)) {
        if ($null -ne $Process -and -not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force
            $Process.WaitForExit()
        }
    }
}
