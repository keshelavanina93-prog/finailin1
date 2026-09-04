[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$RepositoryOnly
)

$ErrorActionPreference = 'Stop'
$resolvedRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$expectedRoot = 'D:\FinAI\finailinear1'

if (-not $IsWindows) {
    Write-Host 'D:-only guard skipped on non-Windows runner.'
    exit 0
}

if (-not $resolvedRoot.StartsWith('D:\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "FinAI local development is D:-only. Repository resolved to '$resolvedRoot'."
}

if (-not $resolvedRoot.Equals($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "FinAI canonical checkout must be '$expectedRoot'. Repository resolved to '$resolvedRoot'."
}

if ($RepositoryOnly) {
    Write-Host "D:-only repository guard passed for $resolvedRoot"
    exit 0
}

$guardedNames = @(
    'TEMP',
    'TMP',
    'XDG_CACHE_HOME',
    'UV_CACHE_DIR',
    'PIP_CACHE_DIR',
    'PNPM_HOME',
    'FINAI_RUNTIME_ROOT'
)

foreach ($name in $guardedNames) {
    $value = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ($value -and -not $value.StartsWith('D:\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$name must resolve to D: for FinAI local development; received '$value'."
    }
}

Write-Host "D:-only guard passed for $resolvedRoot"
