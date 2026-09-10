#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)][int]$ApiPort = 8061,
    [ValidateRange(1024, 65535)][int]$WebPort = 3061,
    [string]$PostgresBin = 'D:\PG18\pgsql\bin',
    [switch]$CreateShortcut
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
& "$PSScriptRoot\assert-d-drive.ps1" -RepositoryRoot $repositoryRoot -RepositoryOnly
& "$PSScriptRoot\bootstrap-local.ps1" -SkipInstall

if (-not (Test-Path -LiteralPath "$PostgresBin\pg_ctl.exe")) {
    throw "PostgreSQL was not found at $PostgresBin. Pass -PostgresBin for this machine."
}
& "$PSScriptRoot\start-local-postgres.ps1" -PostgresBin $PostgresBin | Out-Null
& "$env:VIRTUAL_ENV\Scripts\python.exe" "$PSScriptRoot\configure-nyxcore-local.py"
& "$PSScriptRoot\load-local.ps1"

# Build-time public configuration is local-only and contains no secret.
$env:NEXT_PUBLIC_FINAI_LOCAL_LOGIN = 'true'
$standaloneServer = Join-Path $repositoryRoot 'apps\web\.next\standalone\apps\web\server.js'
if (-not (Test-Path -LiteralPath $standaloneServer)) {
    Push-Location $repositoryRoot
    try { pnpm --filter @finai/web build }
    finally { Pop-Location }
}

& "$PSScriptRoot\g8-system.ps1" -Action start -ApiPort $ApiPort -WebPort $WebPort -PostgresBin $PostgresBin | Out-Null
$url = "http://127.0.0.1:$WebPort"
Start-Process $url

if ($CreateShortcut) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcutPath = Join-Path $desktop 'NYXCore Local Development.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = (Get-Command pwsh).Source
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\start-nyxcore-local.ps1`""
    $shortcut.WorkingDirectory = $repositoryRoot
    $shortcut.Description = 'Start the local NYXCore / G8 development workspace'
    $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
    $shortcut.Save()
    Write-Host "Desktop shortcut created: $shortcutPath"
}

Write-Host "NYXCore local workspace is running at $url"
Write-Host 'Local username: nyxcore.local'
Write-Host 'Local password: NYXcore-local-2026!'
Write-Host "Stop managed services with: $PSScriptRoot\g8-system.ps1 -Action stop"
