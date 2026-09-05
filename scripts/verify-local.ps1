[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
& (Join-Path $PSScriptRoot 'bootstrap-local.ps1') -SkipInstall
if (Test-Path "$env:FINAI_RUNTIME_ROOT\local.json") {
    & "$PSScriptRoot\load-local.ps1"
} else {
    throw 'PostgreSQL configuration missing. Run scripts\start-local-postgres.ps1 first.'
}

Push-Location $repositoryRoot
try {
    & "$PSScriptRoot\test-d-drive.ps1"
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
