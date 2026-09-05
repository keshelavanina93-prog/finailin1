#requires -Version 7.0
[CmdletBinding()]
param([int]$ApiPort = 18061, [int]$WebPort = 13061)
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot 'g8-runtime.ps1'
$statePath = Join-Path (Split-Path -Parent $PSScriptRoot) '.finai\supervisor\processes.json'
if (Test-Path $statePath) {
    $previous = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if (@($previous.services | Where-Object service -in @('api', 'web')).Count -gt 0) { throw 'Smoke requires no existing managed API/web runtime. Existing services were preserved.' }
}
$originalPorts = @(Get-NetTCPConnection -State Listen -LocalPort 8061,3061 -ErrorAction SilentlyContinue | Select-Object LocalPort,OwningProcess)
$originalState = $null
try {
    & $runtime start -Service api -ApiPort $ApiPort -WebPort $WebPort -HealthTimeoutSeconds 15 | Out-Null
    $originalState = Get-Content -Raw -LiteralPath $statePath
    & $runtime start -Service web -ApiPort $ApiPort -WebPort $WebPort -HealthTimeoutSeconds 15 | Out-Null
    $originalState = Get-Content -Raw -LiteralPath $statePath
    $before = $originalState | ConvertFrom-Json
    if (@($before.services | Where-Object service -in @('api', 'web')).Count -ne 2) { throw 'Expected two managed application services.' }
    & $runtime start -Service api -ApiPort $ApiPort -WebPort $WebPort -HealthTimeoutSeconds 15 | Out-Null
    & $runtime start -Service web -ApiPort $ApiPort -WebPort $WebPort -HealthTimeoutSeconds 15 | Out-Null
    $after = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if (($before.services.processId -join ',') -ne ($after.services.processId -join ',')) { throw 'Idempotent start changed PIDs.' }
    # Deliberately invalidate one identity; stop must refuse without touching it.
    ($after.services | Where-Object service -eq 'api').createdAt = '2000-01-01T00:00:00.0000000Z'
    $after | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statePath -Encoding utf8
    $rejected = $false
    try { & $runtime stop -Service api | Out-Null } catch { $rejected = $_.Exception.Message -like '*Ownership changed*' }
    if (-not $rejected) { throw 'Expected ownership mismatch rejection.' }
    foreach ($record in $before.services) {
        if (-not (Get-Process -Id $record.processId -ErrorAction SilentlyContinue)) { throw 'Ownership refusal stopped a process.' }
    }
} finally {
    if ($null -ne $originalState) {
        Set-Content -LiteralPath $statePath -Value $originalState -Encoding utf8
        & $runtime stop -Service web | Out-Null
        & $runtime stop -Service api | Out-Null
    }
}
if (@(Get-NetTCPConnection -State Listen -LocalPort $ApiPort,$WebPort -ErrorAction SilentlyContinue).Count -gt 0) { throw 'Managed listener remained after stop.' }
foreach ($listener in $originalPorts) {
    if (-not (Get-NetTCPConnection -State Listen -LocalPort $listener.LocalPort -ErrorAction SilentlyContinue | Where-Object OwningProcess -eq $listener.OwningProcess)) {
        throw 'An independent default-port listener changed during verification.'
    }
}
Write-Host 'PASS: healthy start, idempotent start, ownership refusal, owned-tree stop, and preservation of independent listeners.'
