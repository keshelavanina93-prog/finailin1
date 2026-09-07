#requires -Version 7.0
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'load-local.ps1')
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskUv = Join-Path $taskRoot '.finai\tools\uv\uv.exe'
if (-not (Test-Path -LiteralPath $taskUv)) { throw 'Provision the reviewed uv executable on D: first.' }
$taskUvVersion = & $taskUv --version
if ($taskUvVersion -notmatch '^uv 0\.10\.8(?:\s|$)') { throw 'Lock regeneration requires reviewed uv 0.10.8.' }
$taskWork = Join-Path $taskRoot '.finai\dependency-lock'
New-Item -ItemType Directory -Force -Path $taskWork | Out-Null
& $taskPython -c "import sys,platform; assert sys.version_info[:3]==(3,13,14) and sys.platform=='win32' and platform.machine()=='AMD64', 'Windows AMD64 Python3.13.14 is required'"
$taskInstalled = & $taskPython -m pip list --format=json | ConvertFrom-Json
$taskPins = @($taskInstalled | Where-Object name -ne 'finai-api' | ForEach-Object { "$($_.name)==$($_.version)" })
[IO.File]::WriteAllLines((Join-Path $taskWork 'installed.txt'), $taskPins, [Text.UTF8Encoding]::new($false))
# Build tooling is explicitly selected, not an unconstrained upgrade of the tested environment.
$taskBuildPins = @('hatchling==1.27.0','trove-classifiers==2025.1.15.22','editables==0.5')
[IO.File]::WriteAllLines((Join-Path $taskWork 'tooling.txt'), $taskBuildPins, [Text.UTF8Encoding]::new($false))
Push-Location $taskRoot
try {
    & $taskUv pip compile services/api/pyproject.toml --extra dev `
        (Join-Path $taskWork 'installed.txt') (Join-Path $taskWork 'tooling.txt') `
        --constraints (Join-Path $taskWork 'installed.txt') --generate-hashes --no-build `
        --python $taskPython --python-version 3.13.14 --python-platform x86_64-pc-windows-msvc `
        --no-header --output-file services/api/requirements-local.lock --quiet
    $taskLock = Join-Path $taskRoot 'services/api/requirements-local.lock'
    $taskHeader = "# Target: Windows AMD64, CPython 3.13.14. Runtime + dev + local build tooling.`n" +
        "# Captured installed versions; separately selected hatchling 1.27.0 / trove-classifiers 2025.1.15.22 / editables 0.5.`n" +
        "# Regenerate explicitly with scripts/lock-local-python.ps1 (uv 0.10.8). Not a Linux lock.`n"
    [IO.File]::WriteAllText($taskLock, $taskHeader + [IO.File]::ReadAllText($taskLock), [Text.UTF8Encoding]::new($false))
    Write-Host 'Captured tested installed dependency versions; added separately pinned local build tooling.'
} finally { Pop-Location }
