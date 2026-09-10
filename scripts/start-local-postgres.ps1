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
$ready = $false
if (Test-Path -LiteralPath "$PostgresBin\pg_isready.exe") {
    & "$PostgresBin\pg_isready.exe" -h 127.0.0.1 -p $Port -t 2 2>$null | Out-Null
    $ready = $LASTEXITCODE -eq 0
}
$PSNativeCommandUseErrorActionPreference = $true
if ($ready) { $running = $true }
if ($running -and -not $ready) {
    $pidPath = Join-Path $cluster 'postmaster.pid'
    $serverPid = $null
    if (Test-Path -LiteralPath $pidPath) {
        $serverPid = [int](Get-Content -LiteralPath $pidPath -TotalCount 1)
    }
    if ($null -eq (Get-Process -Id $serverPid -ErrorAction SilentlyContinue)) {
        # pg_ctl can report the retained PID file as running after an interrupted
        # local process. Remove only this checkout's proven-stale PID marker.
        Remove-Item -LiteralPath $pidPath -Force
        $running = $false
    }
}
if ($running) {
    $activePort = (Get-Content -LiteralPath (Join-Path $cluster 'postmaster.pid'))[3]
    if ($activePort -ne [string]$Port) {
        throw "This checkout's PostgreSQL is running on port $activePort; requested $Port. No configuration changed."
    }
}
if (-not $running) {
    # Do not let pg_ctl's Windows wait mode block the complete local launcher.
    # Start is bounded, then readiness is checked independently on the exact
    # host/port used by the API configuration.
    $PSNativeCommandUseErrorActionPreference = $false
    & "$PostgresBin\pg_ctl.exe" start -D $cluster -l "$env:FINAI_RUNTIME_ROOT\artifacts\postgres.log" -o "-h 127.0.0.1 -p $Port" -t 30
    $startExit = $LASTEXITCODE
    $PSNativeCommandUseErrorActionPreference = $true
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        & "$PostgresBin\pg_isready.exe" -h 127.0.0.1 -p $Port -t 2 2>$null | Out-Null
        $ready = $LASTEXITCODE -eq 0
        if (-not $ready) { Start-Sleep -Milliseconds 250 }
    } while (-not $ready -and [DateTime]::UtcNow -lt $deadline)
    if (-not $ready) { throw "PostgreSQL did not become ready on 127.0.0.1:$Port (pg_ctl exit $startExit)." }
}
$secret = Get-Content -Raw $passwordFile
$env:FINAI_MIGRATION_DATABASE_URL = "postgresql://finai_admin:${secret}@127.0.0.1:$Port/postgres"
& "$env:VIRTUAL_ENV\Scripts\python.exe" "$PSScriptRoot\provision-local.py"
