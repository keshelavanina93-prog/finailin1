#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('start', 'status', 'stop')][string]$Action = 'status',
    [ValidateRange(1024, 65535)][int]$ApiPort = 8061,
    [ValidateRange(1024, 65535)][int]$WebPort = 3061,
    [ValidateRange(5, 120)][int]$HealthTimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
& "$PSScriptRoot\bootstrap-local.ps1" -SkipInstall
$controlRoot = Join-Path $env:FINAI_RUNTIME_ROOT 'supervisor'
New-Item -ItemType Directory -Force -Path $controlRoot | Out-Null
# Guard this directory as well as the bootstrap paths before writing state or logs.
$controlItem = Get-Item -Force -LiteralPath $controlRoot
if ($controlItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Supervisor directory cannot be a reparse point.' }
$statePath = Join-Path $controlRoot 'processes.json'
$lockPath = Join-Path $controlRoot 'runtime.lock'
foreach ($path in @($statePath, $lockPath)) {
    if ((Test-Path -LiteralPath $path) -and ((Get-Item -Force -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Supervisor state cannot use reparse points.'
    }
}
try { $runtimeLock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None') }
catch { throw 'Another G8 runtime command is active, or the runtime lock is inaccessible.' }

function Get-ProcessIdentity([int]$ProcessNumber) {
    Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessNumber" -ErrorAction Stop
}
function Test-Owned($Record) {
    $current = Get-ProcessIdentity $Record.processId
    return ($null -ne $current -and
        $current.CreationDate.ToUniversalTime() -eq ([datetime]$Record.createdAt).ToUniversalTime() -and
        $current.ExecutablePath -eq $Record.executable -and
        $current.CommandLine -eq $Record.commandLine)
}
function Write-State {
    $temporary = Join-Path $controlRoot ('state-' + [guid]::NewGuid().ToString('N') + '.tmp')
    @{ version = 1; repository = $repositoryRoot; services = @($script:records) } |
        ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $statePath -Force
}
function Test-Health([string]$Url) {
    try { return (Invoke-WebRequest -Uri $Url -TimeoutSec 2 -SkipHttpErrorCheck).StatusCode -eq 200 }
    catch { return $false }
}
function Stop-Owned($Record) {
    if (-not (Test-Owned $Record)) { throw "Cannot verify ownership of $($Record.service); no process was stopped." }
    # Snapshot descendants while the verified parent is alive. Never stop by port/name.
    $all = @(Get-CimInstance Win32_Process)
    $tree = [Collections.Generic.List[object]]::new()
    $tree.Add((Get-ProcessIdentity $Record.processId))
    for ($index = 0; $index -lt $tree.Count; $index++) {
        $parent = $tree[$index]
        foreach ($child in $all | Where-Object { $_.ParentProcessId -eq $parent.ProcessId -and $_.CreationDate -ge $parent.CreationDate }) {
            if (-not ($tree.ProcessId -contains $child.ProcessId)) { $tree.Add($child) }
        }
    }
    for ($index = $tree.Count - 1; $index -ge 0; $index--) {
        $expected = $tree[$index]
        $current = Get-ProcessIdentity $expected.ProcessId
        if ($null -ne $current -and $current.CreationDate -eq $expected.CreationDate -and
            $current.ExecutablePath -eq $expected.ExecutablePath -and $current.CommandLine -eq $expected.CommandLine) {
            Stop-Process -Id $current.ProcessId -Force -ErrorAction Stop
        }
    }
}

try {
    $script:records = @()
    if (Test-Path -LiteralPath $statePath) {
        $saved = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        if ($saved.version -ne 1 -or $saved.repository -ne $repositoryRoot) { throw 'Runtime state does not belong to this checkout.' }
        $script:records = @($saved.services)
    }
    if ($Action -eq 'stop') {
        foreach ($record in @($script:records)) {
            if (Test-Owned $record) { Stop-Owned $record }
            elseif ($null -ne (Get-ProcessIdentity $record.processId)) { throw "Ownership changed for $($record.service); refusing to stop it." }
            $script:records = @($script:records | Where-Object { $_.service -ne $record.service })
            Write-State
        }
        Write-Host 'G8 managed processes stopped. Independently started services are unchanged.'
    }
    if ($Action -eq 'start') {
        if ($ApiPort -eq $WebPort) { throw 'API and web ports must differ.' }
        & "$PSScriptRoot\load-local.ps1"
        & "$PSScriptRoot\assert-d-drive.ps1" -RepositoryRoot $repositoryRoot
        $python = Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
        $server = Join-Path $repositoryRoot 'apps\web\.next\standalone\apps\web\server.js'
        foreach ($required in @($python, $server)) {
            if (-not (Test-Path -LiteralPath $required)) { throw 'Runtime dependencies/build missing; run bootstrap-local.ps1 and pnpm build first.' }
        }
        $node = (Get-Command node.exe -ErrorAction Stop).Source
        $specs = @(
            @{ name = 'api'; port = $ApiPort; url = "http://127.0.0.1:$ApiPort/health"; executable = $python; arguments = "-m uvicorn finai_api.main:app --host 127.0.0.1 --port $ApiPort" },
            @{ name = 'web'; port = $WebPort; url = "http://127.0.0.1:$WebPort"; executable = $node; arguments = ('"' + $server + '"') }
        )
        foreach ($spec in $specs) {
            $existing = @($script:records | Where-Object { $_.service -eq $spec.name })
            if ($existing.Count -gt 1) { throw 'Duplicate runtime service records.' }
            if ($existing.Count -eq 1 -and (Test-Owned $existing[0])) {
                if ($existing[0].port -ne $spec.port) { throw 'Managed runtime uses different ports. Stop it explicitly before changing ports.' }
                if (-not (Test-Health $existing[0].healthUrl)) { throw "Managed $($spec.name) is unhealthy; inspect its logs." }
                continue
            }
            if (Get-NetTCPConnection -State Listen -LocalPort $spec.port -ErrorAction SilentlyContinue) {
                throw "Port $($spec.port) is already occupied by an unmanaged service. It has been preserved; use alternate ports."
            }
        }
        $newRecords = @()
        try {
            foreach ($spec in $specs) {
                $existing = @($script:records | Where-Object { $_.service -eq $spec.name })
                if ($existing.Count -eq 1 -and (Test-Owned $existing[0])) { continue }
                if ($spec.name -eq 'web') {
                    $standalone = Split-Path -Parent $server
                    Copy-Item -LiteralPath "$repositoryRoot\apps\web\.next\static" -Destination "$standalone\.next" -Recurse -Force
                    if (Test-Path "$repositoryRoot\apps\web\public") { Copy-Item -LiteralPath "$repositoryRoot\apps\web\public" -Destination $standalone -Recurse -Force }
                    $env:FINAI_API_URL = "http://127.0.0.1:$ApiPort"
                    $env:PORT = [string]$WebPort
                    $env:HOSTNAME = '127.0.0.1'
                }
                $runId = [guid]::NewGuid().ToString('N')
                $stdout = Join-Path $controlRoot "$($spec.name)-$runId.stdout.log"
                $stderr = Join-Path $controlRoot "$($spec.name)-$runId.stderr.log"
                $process = Start-Process -FilePath $spec.executable -ArgumentList $spec.arguments -WorkingDirectory $repositoryRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
                $identity = Get-ProcessIdentity $process.Id
                if ($null -eq $identity) { throw "$($spec.name) exited during launch; inspect logs in $controlRoot." }
                $record = [pscustomobject]@{ service = $spec.name; processId = $identity.ProcessId; createdAt = $identity.CreationDate.ToUniversalTime().ToString('o'); executable = $identity.ExecutablePath; commandLine = $identity.CommandLine; port = $spec.port; healthUrl = $spec.url; stdout = $stdout; stderr = $stderr }
                $newRecords += $record
                $script:records = @($script:records | Where-Object { $_.service -ne $spec.name }) + $record
                Write-State
                $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
                while ((Test-Owned $record) -and [DateTime]::UtcNow -lt $deadline -and -not (Test-Health $record.healthUrl)) { Start-Sleep -Milliseconds 250 }
                if (-not (Test-Owned $record) -or -not (Test-Health $record.healthUrl)) { throw "$($spec.name) did not become healthy; inspect logs in $controlRoot." }
            }
        } catch {
            foreach ($record in $newRecords) {
                if (Test-Owned $record) { Stop-Owned $record }
                $script:records = @($script:records | Where-Object { $_.processId -ne $record.processId })
            }
            Write-State
            throw
        }
    }
    foreach ($service in @('api', 'web')) {
        $record = $script:records | Where-Object { $_.service -eq $service } | Select-Object -First 1
        if ($record) {
            $owned = Test-Owned $record
            [pscustomobject]@{ service = $service; managed = $owned; healthy = ($owned -and (Test-Health $record.healthUrl)); port = $record.port; stdout = $record.stdout; stderr = $record.stderr }
        } else {
            $port = if ($service -eq 'api') { $ApiPort } else { $WebPort }
            [pscustomobject]@{ service = $service; managed = $false; port = $port; occupied = [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) }
        }
    }
} finally { $runtimeLock.Dispose() }
