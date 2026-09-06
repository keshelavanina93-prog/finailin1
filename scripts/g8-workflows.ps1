#requires -Version 7.0
[CmdletBinding()]
param([ValidateSet('start','stop','status')][string]$Action='status',
      [ValidateSet('all','temporal','worker')][string]$Service='all')
$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskRuntime=Join-Path $taskRoot '.finai'
$taskState=Join-Path $taskRuntime 'workflow-processes.json'

function Get-WorkflowProcess($Record) {
 if($null -eq $Record){return $null}
 Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$Record.pid)"
}
function Test-WorkflowOwnership($Record,$Process) {
 return [bool]($Record -and $Process -and $Process.ExecutablePath -eq $Record.exe -and
  $Process.CommandLine -eq $Record.command -and
  $Process.CreationDate.ToUniversalTime() -eq ([datetime]$Record.created).ToUniversalTime())
}
function Test-TemporalReachability {
 $connection=[Net.Sockets.TcpClient]::new()
 try {
  $pending=$connection.ConnectAsync('127.0.0.1',7233)
  return [bool]($pending.Wait(1500) -and $connection.Connected)
 } catch {return $false} finally {$connection.Dispose()}
}
function Write-WorkflowStatus($Records) {
 foreach($name in @('temporal','worker') | Where-Object {$Service -eq 'all' -or $_ -eq $Service}){
  $record=@($Records | Where-Object name -eq $name) | Select-Object -First 1
  $process=Get-WorkflowProcess $record
  $owned=Test-WorkflowOwnership $record $process
  $state=if($owned){'RUNNING'}elseif($process){'OWNERSHIP_CHANGED'}elseif($record){'STOPPED'}else{'NOT_MANAGED'}
  $reachable=if($name -eq 'temporal'){Test-TemporalReachability}else{$null}
  [pscustomobject]@{
   Service=$name;Running=$owned;Owned=$owned;ProcessPresent=[bool]$process;State=$state
   TemporalReachable=$reachable
   Observation=if($name -eq 'temporal'){'TCP_REACHABILITY_ONLY'}else{'PROCESS_LIVENESS_ONLY'}
   ExecutionProven=$false;Log=if($record){$record.log}else{$null}
  }
 }
}

# A diagnostic read must neither bootstrap directories nor acquire/create mutation state.
if($Action -eq 'status'){
 $records=@()
 if(Test-Path -LiteralPath $taskState){$records=@(Get-Content -Raw -Encoding utf8 -LiteralPath $taskState | ConvertFrom-Json)}
 Write-WorkflowStatus $records
 return
}
& "$PSScriptRoot\bootstrap-local.ps1" -SkipInstall
& "$PSScriptRoot\load-local.ps1"
$taskState=Join-Path $env:FINAI_RUNTIME_ROOT 'workflow-processes.json'
$taskLock=[IO.File]::Open((Join-Path $env:FINAI_RUNTIME_ROOT 'workflow-processes.lock'),'OpenOrCreate','ReadWrite','None')
try {
 $records=@(); if(Test-Path -LiteralPath $taskState){$records=@(Get-Content -Raw -LiteralPath $taskState | ConvertFrom-Json)}
 $specs=@(
  @{name='temporal';exe="$taskRoot\.finai\tools\temporal\temporal.exe";args="server start-dev --headless --ip 127.0.0.1 --port 7233 --db-filename `"$taskRoot\.finai\data\temporal.db`""},
  @{name='worker';exe="$taskRoot\.venv\Scripts\python.exe";args='-m finai_api.workflow_worker'}
 )
 foreach($spec in $specs | Where-Object {$Service -eq 'all' -or $_.name -eq $Service}){
  $record=$records | Where-Object name -eq $spec.name | Select-Object -First 1
  $process=Get-WorkflowProcess $record
  $owned=Test-WorkflowOwnership $record $process
  if($process -and -not $owned){throw 'Workflow process ownership changed; refusing mutation'}
  if($Action -eq 'stop'){
   if($owned){Stop-Process -Id $record.pid -Force}
   $records=@($records | Where-Object name -ne $spec.name)
  } elseif($Action -eq 'start' -and -not $owned){
   if($spec.name -eq 'temporal' -and (Get-NetTCPConnection -LocalPort 7233 -State Listen -ErrorAction SilentlyContinue)){throw 'Temporal port occupied by unmanaged service'}
   if(-not (Test-Path -LiteralPath $spec.exe)){throw "Missing workflow dependency: $($spec.name)"}
   $log=Join-Path $env:FINAI_RUNTIME_ROOT ('workflow-'+$spec.name+'-'+[guid]::NewGuid().ToString('N'))
   $p=Start-Process -FilePath $spec.exe -ArgumentList $spec.args -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$log.out.log" -RedirectStandardError "$log.err.log"
   $actual=Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)"
   $records=@($records | Where-Object name -ne $spec.name)+@{name=$spec.name;pid=$p.Id;exe=$actual.ExecutablePath;command=$actual.CommandLine;created=$actual.CreationDate.ToUniversalTime().ToString('o');log=$log}
   if($spec.name -eq 'temporal'){
    $deadline=[DateTime]::UtcNow.AddSeconds(20)
    do {Start-Sleep -Milliseconds 250; $ready=Get-NetTCPConnection -LocalPort 7233 -State Listen -ErrorAction SilentlyContinue} while(-not $ready -and [DateTime]::UtcNow -lt $deadline)
    if(-not $ready){throw 'Temporal failed to start; inspect workflow logs'}
   }
  }
  $records | ConvertTo-Json -Depth 5 -AsArray | Set-Content -LiteralPath $taskState -Encoding utf8
 }
 Write-WorkflowStatus $records
} finally {$taskLock.Dispose()}
