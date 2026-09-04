[CmdletBinding()]
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
& (Join-Path $PSScriptRoot 'assert-d-drive.ps1') -RepositoryRoot $repositoryRoot -RepositoryOnly

$runtimeRoot = Join-Path $repositoryRoot '.finai'
$directories = @{
    Temp = Join-Path $runtimeRoot 'tmp'
    Cache = Join-Path $runtimeRoot 'cache'
    UvCache = Join-Path $runtimeRoot 'cache\uv'
    PipCache = Join-Path $runtimeRoot 'cache\pip'
    PnpmHome = Join-Path $runtimeRoot 'pnpm'
    PnpmStore = Join-Path $runtimeRoot 'pnpm-store'
    Data = Join-Path $runtimeRoot 'data'
    Artifacts = Join-Path $runtimeRoot 'artifacts'
    Worktrees = 'D:\FinAI\worktrees'
}

$directories.Values | ForEach-Object {
    New-Item -ItemType Directory -Force -Path $_ | Out-Null
}

$env:FINAI_RUNTIME_ROOT = $runtimeRoot
$env:TEMP = $directories.Temp
$env:TMP = $directories.Temp
$env:XDG_CACHE_HOME = $directories.Cache
$env:UV_CACHE_DIR = $directories.UvCache
$env:PIP_CACHE_DIR = $directories.PipCache
$env:PNPM_HOME = $directories.PnpmHome
$env:PNPM_STORE_DIR = $directories.PnpmStore
$env:FINAI_DATA_DIR = $directories.Data
$env:FINAI_ARTIFACTS_DIR = $directories.Artifacts
$env:VIRTUAL_ENV = Join-Path $repositoryRoot '.venv'

& (Join-Path $PSScriptRoot 'assert-d-drive.ps1') -RepositoryRoot $repositoryRoot

if (-not $SkipInstall) {
    Push-Location $repositoryRoot
    try {
        pnpm install --store-dir $directories.PnpmStore --no-frozen-lockfile

        if (-not (Test-Path -LiteralPath $env:VIRTUAL_ENV)) {
            python -m venv $env:VIRTUAL_ENV
        }

        $python = Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
        & $python -m pip install --cache-dir $directories.PipCache --upgrade pip
        & $python -m pip install --cache-dir $directories.PipCache -e 'services/api[dev]'
    }
    finally {
        Pop-Location
    }
}

Write-Host 'FinAI local environment is ready.'
Write-Host "Runtime state: $runtimeRoot"
Write-Host "Python venv: $env:VIRTUAL_ENV"
Write-Host "pnpm store: $($directories.PnpmStore)"
