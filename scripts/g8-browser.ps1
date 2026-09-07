#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('start', 'close', 'screenshot', 'snapshot', 'paths')]
    [string]$Action = 'paths',
    [ValidateRange(1024, 65535)][int]$WebPort = 3062
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\load-local.ps1"
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$browserRoot = Join-Path $env:FINAI_RUNTIME_ROOT 'browser-verification'
$paths = [ordered]@{
    profile = Join-Path $browserRoot 'profile'
    sockets = Join-Path $browserRoot 'sockets'
    downloads = Join-Path $browserRoot 'downloads'
    screenshots = Join-Path $browserRoot 'screenshots'
    config = Join-Path $browserRoot 'agent-browser.json'
}

# Check every existing ancestor before creating directories or writing configuration.
foreach ($path in $paths.Values) {
    $absolute = [IO.Path]::GetFullPath($path)
    if (-not $absolute.StartsWith($repositoryRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Browser verification files must remain inside the canonical D: checkout.'
    }
    $candidate = $absolute
    while ($candidate) {
        if ((Test-Path -LiteralPath $candidate) -and
            ((Get-Item -Force -LiteralPath $candidate).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Browser verification cannot use a reparse point: '$candidate'."
        }
        $candidate = Split-Path -Parent $candidate
    }
}
foreach ($name in @('profile', 'sockets', 'downloads', 'screenshots')) {
    New-Item -ItemType Directory -Force -Path $paths[$name] | Out-Null
}

# A versioned entry point supplies configuration on every invocation. Do not rely
# on a user's default profile or the CLI's temporary screenshot directory.
$configuration = [ordered]@{
    profile = $paths.profile
    downloadPath = $paths.downloads
    screenshotDir = $paths.screenshots
    session = 'g8-local-verification'
}
$configuration | ConvertTo-Json | Set-Content -LiteralPath $paths.config -Encoding utf8
$env:AGENT_BROWSER_CONFIG = $paths.config
$env:AGENT_BROWSER_SOCKET_DIR = $paths.sockets
$env:AGENT_BROWSER_DOWNLOAD_PATH = $paths.downloads
$env:AGENT_BROWSER_SCREENSHOT_DIR = $paths.screenshots

if ($Action -eq 'paths') {
    $paths | ConvertTo-Json
    return
}
$executable = Join-Path $env:FINAI_RUNTIME_ROOT 'tools\browser\node_modules\agent-browser\bin\agent-browser-win32-x64.exe'
if (-not (Test-Path -LiteralPath $executable)) {
    throw "The D: browser verification tool is not installed at '$executable'."
}
$arguments = @('--config', $paths.config, '--session', 'g8-local-verification')
switch ($Action) {
    'start' { $arguments += @('open', "http://127.0.0.1:$WebPort") }
    'close' { $arguments += 'close' }
    'screenshot' { $arguments += 'screenshot' }
    'snapshot' { $arguments += @('snapshot', '-i') }
}
& $executable @arguments
if ($LASTEXITCODE -ne 0) { throw "Browser verification command failed with exit code $LASTEXITCODE." }
