[CmdletBinding()]
param(
    [string]$PostgresBin = 'D:\PG18\pgsql\bin',
    [ValidateRange(1024,65535)][int]$Port = 55439
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
& "$PSScriptRoot\bootstrap-local.ps1" -SkipInstall
$cluster = Join-Path $env:FINAI_DATA_DIR 'postgres-native'
$passwordFile = Join-Path $env:FINAI_RUNTIME_ROOT 'postgres-password'
if (-not (Test-Path $passwordFile)) {
    [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)) |
        Set-Content -NoNewline $passwordFile
}
if (-not (Test-Path (Join-Path $cluster 'PG_VERSION'))) {
    & "$PostgresBin\initdb.exe" -D $cluster -U finai_admin --auth=scram-sha-256 --pwfile=$passwordFile --encoding=UTF8 --locale=C
}
$PSNativeCommandUseErrorActionPreference = $false
& "$PostgresBin\pg_ctl.exe" status -D $cluster 2>$null | Out-Null
$running = $LASTEXITCODE -eq 0
$PSNativeCommandUseErrorActionPreference = $true
if ($running) {
    $activePort = (Get-Content -LiteralPath (Join-Path $cluster 'postmaster.pid'))[3]
    if ($activePort -ne [string]$Port) {
        throw "This checkout's PostgreSQL is running on port $activePort; requested $Port. No configuration changed."
    }
}
if (-not $running) {
    & "$PostgresBin\pg_ctl.exe" start -D $cluster -l "$env:FINAI_RUNTIME_ROOT\artifacts\postgres.log" -o "-h 127.0.0.1 -p $Port" -w
}
$secret = Get-Content -Raw $passwordFile
$env:FINAI_MIGRATION_DATABASE_URL = "postgresql://finai_admin:${secret}@127.0.0.1:$Port/postgres"
& "$env:VIRTUAL_ENV\Scripts\python.exe" "$PSScriptRoot\provision-local.py"
