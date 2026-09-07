#requires -Version 7.0
[CmdletBinding()]
param(
 [ValidateSet('start','stop','status')][string]$Action='status',
 [ValidatePattern('^[a-z][a-z0-9-]{0,47}$')][string]$Name='candidate',
 [string]$ApiReceipt,
 [string]$Python,
 [ValidatePattern('^g8-candidate-[a-z0-9][a-z0-9-]{0,79}$')][string]$Queue='g8-candidate-worker'
)
$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskParent=Join-Path $taskRoot '.finai/built-workers'
$taskState=Join-Path $taskParent ($Name+'.json')

function Assert-BuiltPath([string]$Path) {
 $absolute=[IO.Path]::GetFullPath($Path)
 if(-not $absolute.StartsWith('D:\',[StringComparison]::OrdinalIgnoreCase)){throw 'Worker paths must remain on D:'}
 $current=$absolute
 while($current){
  if(Test-Path -LiteralPath $current){
   $item=Get-Item -Force -LiteralPath $current
   if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Worker paths cannot traverse reparse points'}
  }
  $current=[IO.Path]::GetDirectoryName($current)
 }
 return $absolute
}
function Get-OwnedProcess($Record) {
 if(-not $Record){return $null}
 Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$Record.pid)"
}
function Test-OwnedProcess($Record,$Process) {
 return [bool]($Record -and $Process -and $Process.ExecutablePath -eq $Record.exe -and
  $Process.CommandLine -eq $Record.command -and
  (-not $Record.parent_pid -or $Process.ParentProcessId -eq $Record.parent_pid) -and
  $Process.CreationDate.ToUniversalTime() -eq ([datetime]$Record.created).ToUniversalTime())
}
function Get-OwnedTree($Record) {
 if(-not $Record){return @()}
 $pending=[Collections.Generic.Queue[object]]::new()
 $pending.Enqueue($Record)
 foreach($entry in @($Record.children)){if($entry){$pending.Enqueue($entry)}}
 $seen=@{}
 $owned=[Collections.Generic.List[object]]::new()
 while($pending.Count){
  $entry=$pending.Dequeue()
  $key=[string]$entry.pid+':'+[string]$entry.created
  if($seen.ContainsKey($key)){continue}
  $seen[$key]=$true
  $actual=Get-OwnedProcess $entry
  if(-not (Test-OwnedProcess $entry $actual)){continue}
  if($owned.Count -ge 32){throw 'Candidate worker descendant bound exceeded'}
  $owned.Add($entry)
  $depth=if($entry.depth){[int]$entry.depth}else{0}
  foreach($descendant in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$([int]$entry.pid)")){
   if($descendant.CreationDate.ToUniversalTime() -lt $actual.CreationDate.ToUniversalTime()){continue}
   if($depth -ge 8 -or -not $descendant.ExecutablePath -or -not $descendant.CommandLine){throw 'Candidate descendant ownership cannot be established'}
   $pending.Enqueue(@{pid=$descendant.ProcessId;parent_pid=$descendant.ParentProcessId;exe=$descendant.ExecutablePath;command=$descendant.CommandLine;created=$descendant.CreationDate.ToUniversalTime().ToString('o');depth=$depth+1})
  }
 }
 return $owned.ToArray()
}
function Save-BuiltRecord($Record) {
 $temporary=$taskState+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
 $Record | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 -LiteralPath $temporary
 Move-Item -Force -LiteralPath $temporary -Destination $taskState
}
function Stop-OwnedTree($Record) {
 $tree=@(Get-OwnedTree $Record)
 $children=@($tree | Where-Object pid -ne $Record.pid)
 if($Record -is [Collections.IDictionary]){$Record.children=$children}
 else {$Record | Add-Member -NotePropertyName children -NotePropertyValue $children -Force}
 Save-BuiltRecord $Record
 foreach($entry in @($tree | Sort-Object -Property depth -Descending)){
  if(Test-OwnedProcess $entry (Get-OwnedProcess $entry)){Stop-Process -Id $entry.pid -Force}
 }
 $deadline=[DateTime]::UtcNow.AddSeconds(10)
 do {
  $remaining=@($tree | Where-Object {Test-OwnedProcess $_ (Get-OwnedProcess $_)})
  if(-not $remaining.Count){return}
  Start-Sleep -Milliseconds 100
 } while([DateTime]::UtcNow -lt $deadline)
 throw 'Owned candidate worker tree did not exit within the bounded stop timeout'
}
function Show-BuiltStatus($Record) {
 $process=Get-OwnedProcess $Record
 $owned=Test-OwnedProcess $Record $process
 $tree=@(Get-OwnedTree $Record)
 [pscustomobject]@{
  Name=$Name; State=if($owned){'RUNNING'}elseif($process){'OWNERSHIP_CHANGED'}elseif($tree.Count){'DESCENDANTS_RUNNING'}elseif($Record){'STOPPED'}else{'NOT_MANAGED'}
  Owned=($tree.Count -gt 0); OwnedProcessCount=$tree.Count; Observation='PROCESS_LIVENESS_ONLY'; ExecutionProven=$false; ReleaseAccepted=$false
  TaskQueue=if($Record){$Record.task_queue}else{$null}
  LaunchReceipt=if($Record){$Record.launch_receipt}else{$null}
 }
}
$null=Assert-BuiltPath $taskState
if($Action -eq 'status'){
 $record=if(Test-Path -LiteralPath $taskState){Get-Content -Raw -Encoding utf8 -LiteralPath $taskState | ConvertFrom-Json}else{$null}
 Show-BuiltStatus $record
 return
}
New-Item -ItemType Directory -Force -Path $taskParent | Out-Null
$taskLock=[IO.File]::Open((Join-Path $taskParent ($Name+'.lock')),'OpenOrCreate','ReadWrite','None')
$priorQueue=$env:FINAI_TEMPORAL_TASK_QUEUE
$priorTemp=$env:TEMP
$priorTmp=$env:TMP
try {
 $record=if(Test-Path -LiteralPath $taskState){Get-Content -Raw -Encoding utf8 -LiteralPath $taskState | ConvertFrom-Json}else{$null}
 $process=Get-OwnedProcess $record
 $owned=Test-OwnedProcess $record $process
 if($process -and -not $owned){throw 'Candidate worker process ownership changed; refusing mutation'}
 if($Action -eq 'stop'){
  if($record){Stop-OwnedTree $record}
  Show-BuiltStatus $record
  return
 }
 if(-not $owned -and @(Get-OwnedTree $record).Count){throw 'Retained worker descendants still run; stop the owned tree before restart'}
 if($owned){
  if($record.task_queue -ne $Queue){throw 'Running candidate uses another queue; stop it first'}
  $existingLaunchPath=Assert-BuiltPath $record.launch_receipt
  $existingLaunchHash=(Get-FileHash -Algorithm SHA256 -LiteralPath $existingLaunchPath).Hash.ToLowerInvariant()
  if($existingLaunchHash -cne $record.launch_receipt_sha256){throw 'Retained worker launch receipt failed integrity verification'}
  $existingLaunch=Get-Content -Raw -Encoding utf8 -LiteralPath $existingLaunchPath | ConvertFrom-Json
  if(($ApiReceipt -and (Assert-BuiltPath $ApiReceipt) -ne $existingLaunch.api_build_receipt) -or
     ($Python -and (Assert-BuiltPath $Python) -ne $existingLaunch.python)){
   throw 'Running candidate uses another artifact or Python; stop it first'
  }
  Show-BuiltStatus $record
  return
 }
 if(-not $ApiReceipt -or -not $Python){throw 'Start requires explicit API build receipt and installed Python'}
 $ApiReceipt=Assert-BuiltPath $ApiReceipt
 $Python=Assert-BuiltPath $Python
 & "$PSScriptRoot/load-local.ps1"
 $env:FINAI_TEMPORAL_TASK_QUEUE=$Queue
 $taskProbeCache=Join-Path $taskParent 'probe-cache'
 $null=Assert-BuiltPath $taskProbeCache
 $prepared=& $Python -B -I -X "pycache_prefix=$taskProbeCache" "$PSScriptRoot/prepare-built-worker.py" --api-receipt $ApiReceipt --python $Python --queue $Queue --parent $taskParent
 if($LASTEXITCODE -ne 0){throw 'Candidate worker artifact verification failed'}
 $launchPath=Assert-BuiltPath ([string]$prepared)
 $launch=Get-Content -Raw -Encoding utf8 -LiteralPath $launchPath | ConvertFrom-Json
 $null=Assert-BuiltPath $launch.cwd
 $env:TEMP=Join-Path $launch.cwd 'tmp'; $env:TMP=$env:TEMP
 $arguments='-B -I -X "pycache_prefix='+ (Join-Path $launch.cwd 'cache') +'" -m finai_api.workflow_worker'
 $child=Start-Process -FilePath $Python -ArgumentList $arguments -WorkingDirectory $launch.cwd -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $launch.cwd 'worker.out.log') -RedirectStandardError (Join-Path $launch.cwd 'worker.err.log')
 $actual=Get-CimInstance Win32_Process -Filter "ProcessId=$($child.Id)"
 if(-not $actual){throw 'Candidate worker exited before ownership could be retained'}
 $record=@{pid=$child.Id;parent_pid=$actual.ParentProcessId;depth=0;exe=$actual.ExecutablePath;command=$actual.CommandLine;created=$actual.CreationDate.ToUniversalTime().ToString('o');task_queue=$Queue;launch_receipt=$launchPath;launch_receipt_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $launchPath).Hash.ToLowerInvariant();children=@()}
 try {
  Save-BuiltRecord $record
  Start-Sleep -Milliseconds 500
  $record.children=@(Get-OwnedTree $record | Where-Object pid -ne $record.pid)
  Save-BuiltRecord $record
 } catch {
  Stop-OwnedTree $record
  throw
 }
 Show-BuiltStatus $record
} finally {
 $env:FINAI_TEMPORAL_TASK_QUEUE=$priorQueue
 $env:TEMP=$priorTemp
 $env:TMP=$priorTmp
 $taskLock.Dispose()
}
