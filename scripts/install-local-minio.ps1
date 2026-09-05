#requires -Version 7.0
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
& "$PSScriptRoot\bootstrap-local.ps1" -SkipInstall
$env:GOPATH = Join-Path $env:FINAI_RUNTIME_ROOT 'tools\go'
$env:GOCACHE = Join-Path $env:FINAI_RUNTIME_ROOT 'cache\go-build'
$env:GOMODCACHE = Join-Path $env:FINAI_RUNTIME_ROOT 'cache\go-mod'
$env:GOBIN = Join-Path $env:FINAI_RUNTIME_ROOT 'tools\minio'
$env:GOENV = 'off'
$env:GOTELEMETRY = 'off'
$env:GOMAXPROCS = '4'
# Official source commits, frozen independently of moving release aliases.
$serverCommit = '7aac2a2c5b7c882e68c1ce017d8256be2feea27f'
$clientCommit = '77f82e18b5401a65958f1619df6ebb994634bd88'
go install -p 4 "github.com/minio/minio@$serverCommit"
go install -p 4 "github.com/minio/mc@$clientCommit"
@{
    server = @{ repository = 'https://github.com/minio/minio'; commit = $serverCommit; sha256 = (Get-FileHash "$env:GOBIN\minio.exe" -Algorithm SHA256).Hash }
    client = @{ repository = 'https://github.com/minio/mc'; commit = $clientCommit; sha256 = (Get-FileHash "$env:GOBIN\mc.exe" -Algorithm SHA256).Hash }
    builtAt = [datetime]::UtcNow.ToString('o')
    go = (go version)
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$env:GOBIN\provenance.json" -Encoding utf8
Write-Host 'Pinned official MinIO server/client built under D:. Run provision-local-minio.ps1 next.'
