$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FailureCount = 0

function Write-CheckResult {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    if ($Passed) {
        Write-Host "[OK] $Name - $Detail" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] $Name - $Detail" -ForegroundColor Red
        $script:FailureCount++
    }
}

$PythonCandidates = New-Object System.Collections.Generic.List[string]
foreach ($EnvironmentRoot in @($env:PROJECT_PYTHON, $env:CONDA_PREFIX, $env:VIRTUAL_ENV)) {
    if (-not $EnvironmentRoot) { continue }
    $Candidate = if ($EnvironmentRoot.EndsWith(".exe")) {
        $EnvironmentRoot
    } else {
        Join-Path $EnvironmentRoot "python.exe"
    }
    if ((Test-Path $Candidate) -and -not $PythonCandidates.Contains($Candidate)) {
        $PythonCandidates.Add($Candidate)
    }
}

$ProjectVenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if ((Test-Path $ProjectVenvPython) -and -not $PythonCandidates.Contains($ProjectVenvPython)) {
    $PythonCandidates.Add($ProjectVenvPython)
}

$ResolvedPython = Get-Command python -ErrorAction SilentlyContinue
if ($ResolvedPython) {
    $CondaRoot = Split-Path $ResolvedPython.Source -Parent
    $NamedCondaPython = Join-Path $CondaRoot "envs\rag\python.exe"
    if ((Test-Path $NamedCondaPython) -and -not $PythonCandidates.Contains($NamedCondaPython)) {
        $PythonCandidates.Add($NamedCondaPython)
    }
    if (-not $PythonCandidates.Contains($ResolvedPython.Source)) {
        $PythonCandidates.Add($ResolvedPython.Source)
    }
}

$PythonCommand = $null
foreach ($Candidate in $PythonCandidates) {
    $ErrorActionPreference = "SilentlyContinue"
    & $Candidate -c "import fastapi, uvicorn, streamlit, requests, sqlalchemy, pydantic" 2>$null
    $CandidateExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($CandidateExitCode -eq 0) {
        $PythonCommand = $Candidate
        break
    }
}

$PythonDetail = if ($PythonCommand) { $PythonCommand } else { "not found" }
Write-CheckResult "Python" ([bool]$PythonCommand) $PythonDetail
if ($PythonCommand) {
    & $PythonCommand -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
    Write-CheckResult "Python version" ($LASTEXITCODE -eq 0) ((& $PythonCommand --version) -join " ")

    Write-CheckResult "Python packages" $true "FastAPI, Uvicorn, Streamlit, Requests, SQLAlchemy, Pydantic"
}

$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Write-Host "[OK] .env - found" -ForegroundColor Green
} else {
    Write-Host "[WARN] .env - not found; defaults and .env.example remain available" -ForegroundColor Yellow
}

$StoragePath = Join-Path $ProjectRoot "storage"
Write-CheckResult "Storage directory" (Test-Path $StoragePath) $StoragePath

$EmbeddingPath = Join-Path $ProjectRoot "model\embeddingmodels\bge-small-zh-v1.5"
if (Test-Path $EmbeddingPath) {
    Write-Host "[OK] Embedding model - $EmbeddingPath" -ForegroundColor Green
} else {
    Write-Host "[WARN] Embedding model - missing; disable EMBEDDING_ENABLED or configure a valid path" -ForegroundColor Yellow
}

if ($FailureCount -gt 0) {
    Write-Host "Environment check failed with $FailureCount error(s)." -ForegroundColor Red
    exit 1
}
Write-Host "Environment check passed." -ForegroundColor Green
exit 0
