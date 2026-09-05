& "$PSScriptRoot\bootstrap-local.ps1" -SkipInstall
$configuration = Get-Content -Raw "$env:FINAI_RUNTIME_ROOT\local.json" | ConvertFrom-Json -AsHashtable
foreach ($name in $configuration.Keys) {
    [Environment]::SetEnvironmentVariable($name, $configuration[$name], 'Process')
}
