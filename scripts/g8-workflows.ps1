#requires -Version 7.0
[CmdletBinding()]
param([ValidateSet('start','stop','status')][string]$Action='status',
      [ValidateSet('all','temporal','worker')][string]$Service='all')
$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
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
  $process=$null; if($record){$process=Get-CimInstance Win32_Process -Filter "ProcessId=$($record.pid)"}
  $owned=$process -and $process.ExecutablePath -eq $record.exe -and $process.CommandLine -eq $record.command -and $process.CreationDate.ToUniversalTime() -eq ([datetime]$record.created).ToUniversalTime()
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
 foreach($record in $records){[pscustomobject]@{Service=$record.name;Running=[bool](Get-Process -Id $record.pid -ErrorAction SilentlyContinue);Log=$record.log}}
} finally {$taskLock.Dispose()}
