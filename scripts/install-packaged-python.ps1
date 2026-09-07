#requires -Version 7.0
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$installRoot = Join-Path $repositoryRoot '.finai\python\cpython-3.13.14-windows-x86_64'
$artifactRoot = Join-Path $repositoryRoot '.finai\artifacts\python'
$expectedHash = 'f73b6535281b58eee6bcfb3403af2bcfac711ea1463d8340c47c3047248eddf7'
$archiveUrl = 'https://www.python.org/ftp/python/3.13.14/python-3.13.14-amd64.zip'
$manifestUrl = 'https://www.python.org/ftp/python/3.13.14/windows-3.13.14.json'
function Assert-LocalPath([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    if (-not $cursor.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Python paths must remain on D:.' }
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -Force -LiteralPath $cursor).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse path refused: $cursor" }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        $cursor = if ($parent) { $parent.FullName } else { $null }
    }
}
Assert-LocalPath $repositoryRoot
Assert-LocalPath $installRoot
Assert-LocalPath $artifactRoot
if (Test-Path -LiteralPath $installRoot) { throw 'Interpreter target already exists; refusing to overwrite it.' }
New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null
$manifestPath = Join-Path $artifactRoot ('windows-3.13.14-' + [guid]::NewGuid().ToString('N') + '.json')
Invoke-WebRequest -Uri $manifestUrl -OutFile $manifestPath -TimeoutSec 120
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$entry = @($manifest.versions | Where-Object { $_.id -eq 'pythoncore-3.13-64' })
if ($entry.Count -ne 1 -or $entry[0].'sort-version' -ne '3.13.14' -or $entry[0].url -ne $archiveUrl -or $entry[0].hash.sha256 -ne $expectedHash) { throw 'Official manifest differs from the pinned archive.' }
$archivePath = Join-Path $artifactRoot ('python-3.13.14-amd64-' + $expectedHash + '.zip')
Assert-LocalPath $archivePath
if (-not (Test-Path -LiteralPath $archivePath)) {
    $partial = Join-Path $artifactRoot ('download-' + [guid]::NewGuid().ToString('N') + '.partial')
    Invoke-WebRequest -Uri $archiveUrl -OutFile $partial -TimeoutSec 600
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) { throw 'Downloaded archive failed pinned hash verification.' }
    Move-Item -LiteralPath $partial -Destination $archivePath
}
if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) { throw 'Retained archive hash differs from the pin.' }
Add-Type -AssemblyName System.IO.Compression
$zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
try {
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    [long]$expanded = 0
    if ($zip.Entries.Count -gt 30000) { throw 'Archive inventory exceeds its bound.' }
    foreach ($item in $zip.Entries) {
        $name = $item.FullName.TrimEnd('/')
        if (-not $name -or $name.Contains('\') -or $name.Contains(':') -or $name.StartsWith('/') -or -not $seen.Add($name)) { throw 'Unsafe or duplicate ZIP path.' }
        foreach ($part in $name.Split('/')) {
            if ($part -in @('', '.', '..') -or $part.EndsWith('.') -or $part.EndsWith(' ') -or $part -match '[\x00-\x1f]' -or $part -match '^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)') { throw 'Unsafe ZIP path component.' }
        }
        $mode = ($item.ExternalAttributes -shr 16) -band 0xF000
        if ($mode -ne 0 -and $mode -ne 0x8000 -and $mode -ne 0x4000) { throw 'Linked or special ZIP entries refused.' }
        $expanded += $item.Length
        if ($expanded -gt 1500000000) { throw 'Archive expansion exceeds installation bound.' }
    }
    New-Item -ItemType Directory -Path $installRoot | Out-Null
    foreach ($item in $zip.Entries) {
        $destination = [IO.Path]::GetFullPath((Join-Path $installRoot $item.FullName))
        if (-not $destination.StartsWith($installRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'ZIP extraction escapes installation.' }
        Assert-LocalPath $destination
        if ($item.FullName.EndsWith('/')) { New-Item -ItemType Directory -Path $destination -Force | Out-Null; continue }
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
        $inputStream = $item.Open()
        try {
            $outputStream = [IO.File]::Open($destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
        } finally { $inputStream.Dispose() }
    }
} finally { $zip.Dispose() }
$python = Join-Path $installRoot 'python.exe'
$license = Join-Path $installRoot 'LICENSE.txt'
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $license)) { throw 'Full interpreter or retained license is missing.' }
$probe = @'
import encodings,json,pathlib,struct,sys,sysconfig
paths={'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'stdlib':sysconfig.get_path('stdlib'),'encodings':encodings.__file__}
assert sys.version_info[:3] == (3,13,14)
assert struct.calcsize('P') == 8
assert all(pathlib.Path(p).resolve().drive.upper() == 'D:' for p in [*paths.values(),*sys.path] if p)
print(json.dumps({'version':sys.version,'architecture_bits':64,'paths':paths,'sys_path':sys.path}))
'@
$observed = (& $python -I -B -c $probe) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Interpreter verification failed.' }
if (-not [string]::Equals($observed.paths.base_prefix, $installRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Interpreter base prefix differs from the installation.' }
$receiptPath = Join-Path $artifactRoot ('installation-' + $expectedHash + '.json')
Assert-LocalPath $receiptPath
if (Test-Path -LiteralPath $receiptPath) { throw 'Installation receipt exists; refusing overwrite.' }
@{
    contract='g8-packaged-python/1'; status='PINNED_INTERPRETER_VERIFIED'; version='3.13.14'; architecture='windows-x86_64'
    archive_url=$archiveUrl; archive_path=$archivePath; archive_sha256=$expectedHash
    official_manifest_url=$manifestUrl; official_manifest_path=$manifestPath; official_manifest_sha256=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    executable=$python; executable_sha256=(Get-FileHash -LiteralPath $python -Algorithm SHA256).Hash.ToLowerInvariant()
    license=$license; license_sha256=(Get-FileHash -LiteralPath $license -Algorithm SHA256).Hash.ToLowerInvariant()
    observed=$observed; recorded_at=[datetime]::UtcNow.ToString('o'); system_registration_changed=$false; release_accepted=$false
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding utf8
@{executable=$python;receipt=$receiptPath;version='3.13.14';status='PINNED_INTERPRETER_VERIFIED'} | ConvertTo-Json
