# Unit simulation only: no native process or runtime mutations.
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$syntax=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'g8-built-worker.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Supervisor syntax failed'}
foreach($definition in $syntax.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]},$false)){
 Invoke-Expression $definition.Extent.Text
}
$origin=[datetime]'2026-09-07T00:00:00Z'
$script:processes=@{
 11=[pscustomobject]@{ProcessId=11;ParentProcessId=5;ExecutablePath='D:\python.exe';CommandLine='synthetic';CreationDate=$origin}
 12=[pscustomobject]@{ProcessId=12;ParentProcessId=11;ExecutablePath='D:\base\python.exe';CommandLine='synthetic';CreationDate=$origin.AddSeconds(1)}
 13=[pscustomobject]@{ProcessId=13;ParentProcessId=11;ExecutablePath='D:\unrelated.exe';CommandLine='unrelated';CreationDate=$origin.AddSeconds(-1)}
}
$script:stopped=[Collections.Generic.List[int]]::new()
function Get-CimInstance($ClassName,$Filter){
 if($Filter -match '^ProcessId=(\d+)$'){return $script:processes[[int]$Matches[1]]}
 if($Filter -match '^ParentProcessId=(\d+)$'){
  $parent=[int]$Matches[1]
  return @($script:processes.Values | Where-Object ParentProcessId -eq $parent)
 }
 throw 'Unexpected process selection'
}
function Stop-Process($Id,[switch]$Force){$script:stopped.Add([int]$Id);$script:processes.Remove([int]$Id)}
function Save-BuiltRecord($Record){}
$record=[pscustomobject]@{pid=11;parent_pid=5;exe='D:\python.exe';command='synthetic';created=$origin.ToUniversalTime().ToString('o');depth=0}
$tree=@(Get-OwnedTree $record)
if($tree.Count -ne 2){throw 'Did not isolate exact owned descendants'}
Stop-OwnedTree $record
if(($script:stopped -join ',') -ne '12,11'){throw 'Descendants were not stopped before the owned parent'}
if(-not $script:processes.ContainsKey(13)){throw 'Unrelated process was selected'}
$script:processes[12]=[pscustomobject]@{ProcessId=12;ParentProcessId=11;ExecutablePath='D:\base\python.exe';CommandLine='synthetic';CreationDate=$origin.AddSeconds(5)}
if(@(Get-OwnedTree $record).Count){throw 'Reused PID acquired false ownership'}
Write-Output 'Owned-tree simulation passed: child-first stop, unrelated exclusion, PID reuse refusal.'
