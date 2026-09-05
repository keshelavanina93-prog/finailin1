#requires -Version 7.0
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
& "$PSScriptRoot\bootstrap-local.ps1" -SkipInstall
$taskDestination=Join-Path $env:FINAI_RUNTIME_ROOT 'tools\temporal'
New-Item -ItemType Directory -Force -Path $taskDestination | Out-Null
if((Get-Item -LiteralPath $taskDestination).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Temporal tools path cannot be a reparse point'}
$taskArchive=Join-Path $taskDestination 'temporal-1.8.3.zip'
Invoke-WebRequest 'https://github.com/temporalio/cli/releases/download/v1.8.3/temporal_cli_1.8.3_windows_amd64.zip' -OutFile $taskArchive
$taskExpected='b29a65ba26ae519dc1f3c450addbf77e4676899530ac4061f851427da8d37b05'
if((Get-FileHash -LiteralPath $taskArchive -Algorithm SHA256).Hash.ToLower() -ne $taskExpected){throw 'Temporal checksum mismatch'}
Expand-Archive -LiteralPath $taskArchive -DestinationPath $taskDestination -Force
& (Join-Path $taskDestination 'temporal.exe') --version
Write-Host 'Pinned local Temporal installed. Use g8-workflows.ps1 start. Persistent state stays on D:.'
