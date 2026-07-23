[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pattern = "ReactAgent|LegacyReactAgentAdapter|LazyLegacyExecutor|RecipeAgentHarness|agent\.react_agent|agent[\\/]tools|agent[\\/]routing|agent\.tools|agent\.routing|app\.py"
$excludeGlobs = @(
    "!.git/**",
    "!archive/**",
    "!storage/**",
    "!**/__pycache__/**",
    "!reports/*.json"
)

Push-Location $projectRoot
try {
    $arguments = @("-n", "--no-heading", "--hidden")
    foreach ($glob in $excludeGlobs) {
        $arguments += @("--glob", $glob)
    }
    $arguments += @($pattern, ".")
    $references = @(& rg @arguments)
    if ($LASTEXITCODE -gt 1) {
        throw "rg failed with exit code $LASTEXITCODE"
    }

    $forbidden = @()
    $counts = @{}
    Write-Output "Legacy reference inventory (line-level)"
    foreach ($reference in $references) {
        $parts = $reference -split ":", 3
        if ($parts.Count -lt 3) { continue }
        $path = $parts[0].TrimStart(".", "\", "/").Replace("\", "/")
        $line = $parts[1]
        $content = $parts[2].Trim()

        if ($path -eq "recipe_assistant/agents/harness.py" -or $path.StartsWith("agent/")) {
            $category = "legacy-module-retained"
        } elseif ($path.StartsWith("tests/baseline/") -or $path.StartsWith("test/") -or $path -eq "tests/unit/test_harness.py") {
            $category = "legacy-test-retained"
        } elseif ($path -eq "scripts/compare_legacy_vs_v2.py") {
            $category = "independent-regression"
        } elseif ($path.StartsWith("tests/")) {
            $category = "test-or-guard"
        } elseif ($path.StartsWith("docs/") -or $path -eq "README.md" -or $path.EndsWith(".md")) {
            $category = "documentation"
        } elseif ($content.StartsWith("#") -or $content.StartsWith("//")) {
            $category = "comment"
        } elseif ($path -eq "app.py") {
            $category = "legacy-entry-retained"
        } elseif ($path.StartsWith("recipe_assistant/") -or $path.StartsWith("frontend/")) {
            $category = "runtime-review"
        } else {
            $category = "tooling-or-evidence"
        }

        if (-not $counts.ContainsKey($category)) { $counts[$category] = 0 }
        $counts[$category]++
        Write-Output ("[{0}] {1}:{2}: {3}" -f $category, $path, $line, $content)

        $isNormalRuntime = (
            ($path.StartsWith("recipe_assistant/") -or $path.StartsWith("frontend/")) -and
            $path -ne "recipe_assistant/agents/harness.py"
        )
        $isExecutableLegacyReference = $content -match "LegacyReactAgentAdapter|LazyLegacyExecutor|RecipeAgentHarness|agent\.react_agent|from agent|import agent"
        if ($isNormalRuntime -and $isExecutableLegacyReference) {
            $forbidden += "${path}:${line}"
        }
    }

    Write-Output ""
    Write-Output "Category summary"
    foreach ($key in ($counts.Keys | Sort-Object)) {
        Write-Output ("{0}: {1}" -f $key, $counts[$key])
    }
    Write-Output ("Total references: {0}" -f $references.Count)
    Write-Output ("Forbidden normal-runtime references: {0}" -f $forbidden.Count)
    if ($forbidden.Count -gt 0) {
        $forbidden | ForEach-Object { Write-Error "Forbidden runtime reference: $_" }
        exit 1
    }
    Write-Output "Legacy runtime isolation scan passed."
} finally {
    Pop-Location
}
