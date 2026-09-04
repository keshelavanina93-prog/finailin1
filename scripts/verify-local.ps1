[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
& (Join-Path $PSScriptRoot 'bootstrap-local.ps1') -SkipInstall

Push-Location $repositoryRoot
try {
    $python = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Python environment is missing. Run .\scripts\bootstrap-local.ps1 first.'
    }

    & $python -m ruff check services/api
    & $python -m mypy services/api/src
    & $python -m pytest services/api/tests
    pnpm verify
}
finally {
    Pop-Location
}
