[CmdletBinding()]
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
& (Join-Path $PSScriptRoot 'assert-d-drive.ps1') -RepositoryRoot $repositoryRoot -RepositoryOnly

$runtimeRoot = Join-Path $repositoryRoot '.finai'
$directories = @{
    Temp = Join-Path $runtimeRoot 'tmp'
    Cache = Join-Path $runtimeRoot 'cache'
    UvCache = Join-Path $runtimeRoot 'cache\uv'
    PipCache = Join-Path $runtimeRoot 'cache\pip'
    PnpmHome = Join-Path $runtimeRoot 'pnpm'
    PnpmStore = Join-Path $runtimeRoot 'pnpm-store'
    Data = Join-Path $runtimeRoot 'data'
    Artifacts = Join-Path $runtimeRoot 'artifacts'
    Worktrees = Join-Path $runtimeRoot 'worktrees'
}

$directories.Values | ForEach-Object {
    New-Item -ItemType Directory -Force -Path $_ | Out-Null
}

$env:FINAI_RUNTIME_ROOT = $runtimeRoot
$env:TEMP = $directories.Temp
$env:TMP = $directories.Temp
$env:XDG_CACHE_HOME = $directories.Cache
$env:UV_CACHE_DIR = $directories.UvCache
$env:PIP_CACHE_DIR = $directories.PipCache
$env:PNPM_HOME = $directories.PnpmHome
$env:PNPM_STORE_DIR = $directories.PnpmStore
$env:FINAI_DATA_DIR = $directories.Data
$env:FINAI_ARTIFACTS_DIR = $directories.Artifacts
$env:VIRTUAL_ENV = Join-Path $repositoryRoot '.venv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $runtimeRoot 'python'
$env:UV_TOOL_DIR = Join-Path $runtimeRoot 'tools'
$env:npm_config_cache = Join-Path $runtimeRoot 'cache\npm'
$env:npm_config_userconfig = Join-Path $runtimeRoot 'npmrc'
$env:COREPACK_HOME = Join-Path $runtimeRoot 'cache\corepack'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $runtimeRoot 'cache\playwright'
$env:PYTHONPYCACHEPREFIX = Join-Path $runtimeRoot 'cache\pycache'
$env:NEXT_TELEMETRY_DISABLED = '1'
$env:TURBO_TELEMETRY_DISABLED = '1'

& (Join-Path $PSScriptRoot 'assert-d-drive.ps1') -RepositoryRoot $repositoryRoot

if (-not $SkipInstall) {
    Push-Location $repositoryRoot
    try {
        $pinnedBase = Join-Path $runtimeRoot 'python\cpython-3.13.14-windows-x86_64'
        $basePython = Join-Path $pinnedBase 'python.exe'
        $python = Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
        function Assert-PythonPath([string]$Path) {
            $cursor = [IO.Path]::GetFullPath($Path)
            if (-not $cursor.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Python runtime paths must remain on D:.' }
            while ($cursor) {
                if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -Force -LiteralPath $cursor).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Python runtime cannot traverse a reparse point: $cursor" }
                $parent = [IO.Directory]::GetParent($cursor)
                $cursor = if ($parent) { $parent.FullName } else { $null }
            }
        }
        function Assert-PinnedInterpreter([string]$Executable, [bool]$ExistingEnvironment) {
            Assert-PythonPath $Executable
            $probe = "import encodings,json,struct,sys,sysconfig; print(json.dumps({'version':list(sys.version_info[:3]),'platform':sys.platform,'bits':struct.calcsize('P')*8,'base':sys.base_prefix,'paths':[sys.executable,sys.prefix,sys.base_prefix,sysconfig.get_path('stdlib'),encodings.__file__,*sys.path]}))"
            $observed = (& $Executable -I -B -c $probe) | ConvertFrom-Json
            if ($LASTEXITCODE -ne 0) { throw 'Python runtime inspection failed before dependency installation.' }
            $matches = ($observed.version -join '.') -eq '3.13.14' -and $observed.platform -eq 'win32' -and $observed.bits -eq 64 -and [string]::Equals($observed.base, $pinnedBase, [StringComparison]::OrdinalIgnoreCase)
            foreach ($observedPath in $observed.paths) {
                if ($observedPath -and -not ([IO.Path]::GetFullPath($observedPath)).StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) { $matches = $false }
            }
            if (-not $matches) {
                if ($ExistingEnvironment) { throw 'Existing .venv does not use the pinned D:-only CPython 3.13.14 base and standard library. Stop its dependent services, preserve the environment, and explicitly migrate it using scripts/install-packaged-python.ps1 before retrying bootstrap. No environment was rebound or removed. Use -SkipInstall only for routine legacy configuration loading.' }
                throw 'Pinned interpreter version, architecture, base prefix or standard-library paths failed validation.'
            }
            foreach ($observedPath in $observed.paths) { if ($observedPath) { Assert-PythonPath $observedPath } }
        }
        Assert-PythonPath $pinnedBase
        Assert-PythonPath $env:VIRTUAL_ENV
        if (Test-Path -LiteralPath $env:VIRTUAL_ENV) {
            if (-not (Test-Path -LiteralPath $python)) { throw 'Existing .venv is incomplete; preserve and explicitly migrate it before installation. Bootstrap will not overwrite it.' }
            Assert-PinnedInterpreter $python $true
        }
        if (-not (Test-Path -LiteralPath $basePython)) {
            & (Join-Path $PSScriptRoot 'install-packaged-python.ps1')
        }
        Assert-PinnedInterpreter $basePython $false
        if (-not (Test-Path -LiteralPath $env:VIRTUAL_ENV)) {
            & $basePython -I -B -m venv $env:VIRTUAL_ENV
        }
        Assert-PinnedInterpreter $python $true
        pnpm install --store-dir $directories.PnpmStore --frozen-lockfile

        & $python -m pip install --cache-dir $directories.PipCache --require-hashes `
            --only-binary=:all: --no-deps -r 'services/api/requirements-local.lock'
        # Project source is intentionally editable; external/build dependencies are already locked.
        & $python -m pip install --cache-dir $directories.PipCache --no-deps `
            --no-build-isolation -e 'services/api'
    }
    finally {
        Pop-Location
    }
}

Write-Host 'FinAI local environment is ready.'
Write-Host "Runtime state: $runtimeRoot"
Write-Host "Python venv: $env:VIRTUAL_ENV"
Write-Host "pnpm store: $($directories.PnpmStore)"
