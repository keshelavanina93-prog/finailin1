[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$RepositoryOnly
)

$ErrorActionPreference = 'Stop'
$resolvedRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$expectedRoot = 'D:\FinAI\finailinear1'

if ([Environment]::OSVersion.Platform -ne 'Win32NT') {
    Write-Host 'D:-only guard skipped on non-Windows runner.'
    exit 0
}

if (-not $resolvedRoot.StartsWith('D:\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "FinAI local development is D:-only. Repository resolved to '$resolvedRoot'."
}

if (-not $resolvedRoot.Equals($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    # Admit registered worktrees of this repository, not arbitrary D: checkouts.
    $commonDirectory = & git -C $resolvedRoot rev-parse --path-format=absolute --git-common-dir 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $commonDirectory -or
        -not [IO.Path]::GetFullPath([string]$commonDirectory).Equals(
            (Join-Path $expectedRoot '.git'), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Repository must be the canonical checkout or one of its registered D: worktrees."
    }
    $registeredWorktrees = & git -C $expectedRoot -c core.quotePath=false worktree list --porcelain
    if ($LASTEXITCODE -ne 0) { throw 'Cannot verify registered worktrees.' }
    $registered = @($registeredWorktrees | Where-Object { $_.StartsWith('worktree ') } |
        ForEach-Object { [IO.Path]::GetFullPath($_.Substring(9)) })
    if (-not ($registered | Where-Object { $_.Equals($resolvedRoot, [StringComparison]::OrdinalIgnoreCase) })) {
        throw "Repository is not a registered canonical worktree: '$resolvedRoot'."
    }
}

if ($RepositoryOnly) {
    foreach ($path in @($resolvedRoot, (Join-Path $resolvedRoot '.finai'), (Join-Path $resolvedRoot '.venv'))) {
        $candidate = $path
        while ($candidate) {
            if (Test-Path -LiteralPath $candidate) {
                $item = Get-Item -Force -LiteralPath $candidate
                if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                    throw "Reparse-point checkout/runtime is not permitted: '$candidate'."
                }
            }
            $candidate = Split-Path -Parent $candidate
        }
    }
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
    'FINAI_DATA_DIR'
    'FINAI_ARTIFACTS_DIR'
    'VIRTUAL_ENV'
    'PNPM_STORE_DIR'
    'UV_PYTHON_INSTALL_DIR'
    'UV_TOOL_DIR'
    'npm_config_cache'
    'npm_config_userconfig'
    'COREPACK_HOME'
    'PLAYWRIGHT_BROWSERS_PATH'
    'PYTHONPYCACHEPREFIX'
)

foreach ($name in $guardedNames) {
    $value = [Environment]::GetEnvironmentVariable($name, 'Process')
    if (-not $value) { throw "$name is unset. Run bootstrap-local.ps1 first." }
    $absolute = [IO.Path]::GetFullPath($value)
    if (-not $absolute.StartsWith($resolvedRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$name must remain within this checkout; received '$value'."
    }
    $candidate = $absolute
    while ($candidate) {
        if (Test-Path -LiteralPath $candidate) {
            $item = Get-Item -Force -LiteralPath $candidate
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Reparse-point storage is not permitted: '$candidate'."
            }
        }
        $candidate = Split-Path -Parent $candidate
    }
}

Write-Host "D:-only guard passed for $resolvedRoot"
