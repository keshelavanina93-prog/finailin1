#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('start', 'status', 'stop')][string]$Action = 'status',
    [ValidateRange(1024, 65535)][int]$ApiPort = 8061,
    [ValidateRange(1024, 65535)][int]$WebPort = 3061,
    [string]$PostgresBin = 'D:\PG18\pgsql\bin'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
& "$PSScriptRoot\assert-d-drive.ps1" -RepositoryRoot $repositoryRoot -RepositoryOnly
$runtimeRoot = Join-Path $repositoryRoot '.finai'
$cluster = Join-Path $runtimeRoot 'data\postgres-native'
if ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($PostgresBin)) -ne 'D:\') {
    throw 'PostgreSQL tools must remain on D:.'
}

function Test-Postgres {
    if (-not (Test-Path -LiteralPath "$PostgresBin\pg_ctl.exe")) { return $false }
    $PSNativeCommandUseErrorActionPreference = $false
    & "$PostgresBin\pg_ctl.exe" status -D $cluster 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Get-SystemStatus {
    $postgresRunning = Test-Postgres
    $postgresReady = $false
    if ($postgresRunning -and (Test-Path -LiteralPath "$PostgresBin\pg_isready.exe")) {
        $PSNativeCommandUseErrorActionPreference = $false
        & "$PostgresBin\pg_isready.exe" -h 127.0.0.1 -p 55439 -t 2 2>$null | Out-Null
        $postgresReady = $LASTEXITCODE -eq 0
    }
    [pscustomobject]@{ service = 'postgres'; running = $postgresRunning; healthy = $postgresReady; retainedOnStop = $true }
    $statePath = Join-Path $runtimeRoot 'supervisor\processes.json'
    $records = @()
    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        if ($state.repository -ne $repositoryRoot) { throw 'Application supervisor state belongs to another repository.' }
        $records = @($state.services)
    }
    foreach ($name in @('minio', 'api', 'web')) {
        $record = @($records | Where-Object { $_.service -eq $name })
        $owned = $false
        $healthy = $false
        if ($record.Count -gt 1) { throw "Duplicate $name supervisor records; inspect the existing supervisor state." }
        if ($record.Count -eq 1) {
            $record = $record[0]
            $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.processId)"
            $owned = $null -ne $process -and $process.ExecutablePath -eq $record.executable -and
                $process.CommandLine -eq $record.commandLine -and
                $process.CreationDate.ToUniversalTime() -eq ([datetime]$record.createdAt).ToUniversalTime()
            if ($owned) {
                try { $healthy = (Invoke-WebRequest -Uri $record.healthUrl -TimeoutSec 2 -SkipHttpErrorCheck).StatusCode -eq 200 }
                catch { $healthy = $false }
            }
        }
        [pscustomobject]@{ service = $name; running = $owned; healthy = $healthy }
    }
    & "$PSScriptRoot\g8-workflows.ps1" -Action status
}

# Status only reads retained ownership records and probes health. It must not
# bootstrap directories, provision databases, or rewrite supervisor state.
if ($Action -eq 'status') { Get-SystemStatus; return }
& "$PSScriptRoot\bootstrap-local.ps1" -SkipInstall
$lockPath = Join-Path $runtimeRoot 'system.lock'
if ((Test-Path -LiteralPath $lockPath) -and ((Get-Item -Force -LiteralPath $lockPath).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'System lock cannot be a reparse point.'
}
try { $systemLock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None') }
catch { throw 'Another G8 system command is active, or its lock is inaccessible.' }
try {
    if ($Action -eq 'start') {
        if (-not (Test-Postgres)) { & "$PSScriptRoot\start-local-postgres.ps1" -PostgresBin $PostgresBin | Out-Null }
        & "$PSScriptRoot\g8-runtime.ps1" -Action start -Service minio -ApiPort $ApiPort -WebPort $WebPort | Out-Null
        & "$PSScriptRoot\g8-workflows.ps1" -Action start -Service temporal | Out-Null
        & "$PSScriptRoot\g8-runtime.ps1" -Action start -Service api -ApiPort $ApiPort -WebPort $WebPort | Out-Null
        & "$PSScriptRoot\g8-workflows.ps1" -Action start -Service worker | Out-Null
        & "$PSScriptRoot\g8-runtime.ps1" -Action start -Service web -ApiPort $ApiPort -WebPort $WebPort | Out-Null
    } else {
        & "$PSScriptRoot\g8-runtime.ps1" -Action stop -Service web -ApiPort $ApiPort -WebPort $WebPort | Out-Null
        & "$PSScriptRoot\g8-workflows.ps1" -Action stop -Service worker | Out-Null
        & "$PSScriptRoot\g8-runtime.ps1" -Action stop -Service api -ApiPort $ApiPort -WebPort $WebPort | Out-Null
        & "$PSScriptRoot\g8-workflows.ps1" -Action stop -Service temporal | Out-Null
        & "$PSScriptRoot\g8-runtime.ps1" -Action stop -Service minio -ApiPort $ApiPort -WebPort $WebPort | Out-Null
    }
    $status = @(Get-SystemStatus)
    $status
    if ($Action -eq 'start') {
        foreach ($row in $status) {
            if (-not $row.running -or
                ($row.service -in @('postgres', 'minio', 'api', 'web') -and -not $row.healthy) -or
                ($row.service -eq 'temporal' -and -not $row.TemporalReachable)) {
                throw "G8 startup is incomplete: $($row.service). Inspect its existing supervisor logs; retained services have been preserved."
            }
        }
    }
} finally { $systemLock.Dispose() }
