$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\bootstrap-local.ps1" -SkipInstall
$guard = "$PSScriptRoot\assert-d-drive.ps1"
$original = $env:TEMP
try {
    foreach ($invalid in @('', 'C:\Temp', 'D:\FinAI\finailinear1\..\outside')) {
        $env:TEMP = $invalid
        $denied = $false
        try { & $guard } catch { $denied = $true }
        if (-not $denied) { throw "Guard accepted invalid TEMP: '$invalid'" }
    }
} finally { $env:TEMP = $original }
& $guard
Write-Host 'D:-only guard tests passed: unset, C:, traversal, valid bootstrap.'
