[CmdletBinding()]
param([ValidateSet('api','web')][string]$Service = 'web', [int]$ApiPort = 8061, [int]$WebPort = 3061)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
& "$PSScriptRoot\load-local.ps1"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repositoryRoot
if ($Service -eq 'api') {
    & "$env:VIRTUAL_ENV\Scripts\python.exe" -m uvicorn finai_api.main:app --host 127.0.0.1 --port $ApiPort
} else {
    $env:FINAI_API_URL = "http://127.0.0.1:$ApiPort"
    $standalone = Join-Path $repositoryRoot 'apps\web\.next\standalone\apps\web'
    if (-not (Test-Path "$standalone\server.js")) { throw 'Run pnpm build before starting the workspace.' }
    Copy-Item -LiteralPath "$repositoryRoot\apps\web\.next\static" -Destination "$standalone\.next" -Recurse -Force
    if (Test-Path "$repositoryRoot\apps\web\public") {
        Copy-Item -LiteralPath "$repositoryRoot\apps\web\public" -Destination $standalone -Recurse -Force
    }
    $env:PORT = [string]$WebPort
    $env:HOSTNAME = '127.0.0.1'
    node "$standalone\server.js"
}
