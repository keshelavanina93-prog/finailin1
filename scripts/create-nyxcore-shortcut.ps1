#requires -Version 7.0
[CmdletBinding()]
param([string]$PowerShell = '')

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
& "$PSScriptRoot\assert-d-drive.ps1" -RepositoryRoot $repositoryRoot -RepositoryOnly
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'NYXCore Local Development.lnk'
$shellHost = if ($PowerShell) { $PowerShell } else { (Get-Command pwsh -ErrorAction SilentlyContinue).Source }
if (-not $shellHost) { $shellHost = (Get-Command powershell).Source }
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $shellHost
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\start-nyxcore-local.ps1`""
$shortcut.WorkingDirectory = $repositoryRoot
$shortcut.Description = 'Start the local NYXCore / G8 development workspace'
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
$shortcut.Save()
Write-Host "Created $shortcutPath"
