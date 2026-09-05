[CmdletBinding()]
param([ValidateSet('Operator','Reviewer')][string]$Role = 'Operator')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$configuration = Get-Content -Raw "$root\.finai\local.json" | ConvertFrom-Json -AsHashtable
$grants = $configuration.FINAI_ACCESS_TOKENS | ConvertFrom-Json -AsHashtable
$permission = if ($Role -eq 'Reviewer') { 'review' } else { 'ingest' }
foreach ($entry in $grants.GetEnumerator()) {
    if ($entry.Value.permissions -contains $permission) {
        Set-Clipboard -Value $entry.Key
        Write-Host "$Role access key copied. Paste it into the workspace sign-in form."
        return
    }
}
throw 'No matching identity configured. Run scripts/configure-workspace.py first.'
