param(
    [ValidateSet("summary", "trace", "badcase")]
    [string]$View = "summary",
    [string]$RunId = "latest",
    [ValidateRange(1, 1000)]
    [int]$Limit = 5,
    [switch]$Json,
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$NamedCondaPython = "D:\Anaconda\envs\rag\python.exe"
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

$Arguments = @(
    (Join-Path $PSScriptRoot "inspect_diagnostics.py"),
    "--view", $View,
    "--run-id", $RunId,
    "--limit", "$Limit"
)
if ($Json) {
    $Arguments += "--json"
}
if ($Output) {
    $Arguments += @("--output", $Output)
}

Set-Location $ProjectRoot
& $PythonCommand @Arguments
exit $LASTEXITCODE
