[CmdletBinding()]
param(
    [string]$DestinationRoot,
    [string]$Neo4jDumpPath,
    [switch]$IncludeEnvironmentFile
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    $DestinationRoot = Join-Path $ProjectRoot "storage\decommission_backups"
}

$DestinationRoot = [System.IO.Path]::GetFullPath($DestinationRoot)
$ChromaSource = [System.IO.Path]::GetFullPath(
    (Join-Path $ProjectRoot "storage\chroma_db")
)
if ($DestinationRoot.StartsWith($ChromaSource, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup destination must not be inside storage/chroma_db."
}

$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$SnapshotRoot = Join-Path $DestinationRoot $Timestamp
New-Item -ItemType Directory -Path $SnapshotRoot -Force | Out-Null

$CopiedSources = [System.Collections.Generic.List[string]]::new()
$MissingSources = [System.Collections.Generic.List[string]]::new()

function Copy-BackupItem {
    param(
        [Parameter(Mandatory = $true)][string]$RelativeSource,
        [Parameter(Mandatory = $true)][string]$RelativeDestination,
        [switch]$Optional
    )

    $Source = Join-Path $ProjectRoot $RelativeSource
    if (-not (Test-Path -LiteralPath $Source)) {
        if ($Optional) {
            $MissingSources.Add($RelativeSource)
            return
        }
        throw "Required backup source is missing: $RelativeSource"
    }

    $Destination = Join-Path $SnapshotRoot $RelativeDestination
    $DestinationParent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $DestinationParent -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
    $CopiedSources.Add($RelativeSource)
}

Copy-BackupItem "storage\recipe_assistant.db" "data\sqlite\recipe_assistant.db"
Copy-BackupItem "storage\recipe_assistant.db-wal" "data\sqlite\recipe_assistant.db-wal" -Optional
Copy-BackupItem "storage\recipe_assistant.db-shm" "data\sqlite\recipe_assistant.db-shm" -Optional
Copy-BackupItem "storage\chroma_db" "data\chroma_db"
Copy-BackupItem "storage\parent_documents.json" "data\parent_documents\parent_documents.json"
Copy-BackupItem "storage\recipe_md5.text" "data\ingestion\recipe_md5.text" -Optional
Copy-BackupItem "storage\child_chunk_counts.csv" "data\ingestion\child_chunk_counts.csv" -Optional
Copy-BackupItem "config" "configuration\config"
Copy-BackupItem ".env.example" "configuration\.env.example"
Copy-BackupItem "graph" "neo4j\rebuild\graph"
Copy-BackupItem "data\nutrition" "data\nutrition"

if ($IncludeEnvironmentFile) {
    Copy-BackupItem ".env" "configuration\.env" -Optional
}

$Neo4jStatus = "not-provided"
if (-not [string]::IsNullOrWhiteSpace($Neo4jDumpPath)) {
    $ResolvedDump = (Resolve-Path -LiteralPath $Neo4jDumpPath).Path
    $Neo4jDestination = Join-Path $SnapshotRoot "neo4j\dump"
    New-Item -ItemType Directory -Path $Neo4jDestination -Force | Out-Null
    Copy-Item -LiteralPath $ResolvedDump -Destination $Neo4jDestination -Recurse -Force
    $Neo4jStatus = "included"
}

$GitCommit = (& git -C $ProjectRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve the Git commit for the backup manifest."
}

$FileEntries = Get-ChildItem -LiteralPath $SnapshotRoot -File -Recurse |
    Sort-Object FullName |
    ForEach-Object {
        $RelativePath = $_.FullName.Substring($SnapshotRoot.Length).TrimStart(
            [char[]]"\/"
        )
        [ordered]@{
            path = $RelativePath
            length = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }

$Manifest = [ordered]@{
    schema_version = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    project_root = $ProjectRoot
    git_commit = $GitCommit
    neo4j_dump = $Neo4jStatus
    environment_file_requested = [bool]$IncludeEnvironmentFile
    copied_sources = @($CopiedSources)
    missing_optional_sources = @($MissingSources)
    files = @($FileEntries)
}

$ManifestPath = Join-Path $SnapshotRoot "manifest.json"
$Manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

Write-Output "Backup completed: $SnapshotRoot"
Write-Output "Manifest: $ManifestPath"
Write-Output "Neo4j dump: $Neo4jStatus"
