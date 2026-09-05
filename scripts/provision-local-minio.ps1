#requires -Version 7.0
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
& "$PSScriptRoot\load-local.ps1"
& "$PSScriptRoot\assert-d-drive.ps1"
$adminPath = Join-Path $env:FINAI_RUNTIME_ROOT 'minio-admin.json'
$configurationPath = Join-Path $env:FINAI_RUNTIME_ROOT 'local.json'
$mc = Join-Path $env:FINAI_RUNTIME_ROOT 'tools\minio\mc.exe'
if (-not (Test-Path $mc)) { throw 'Run install-local-minio.ps1 first.' }
if (-not (Test-Path -LiteralPath $adminPath)) {
    @{ accessKey = ('g8admin' + [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(8)).ToLowerInvariant()); secretKey = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant() } |
        ConvertTo-Json | Set-Content -LiteralPath $adminPath -Encoding utf8
}
# Remove broad inherited access from local credential files; retain the current user and SYSTEM.
foreach ($credentialPath in @($adminPath, $configurationPath)) {
    $acl = Get-Acl -LiteralPath $credentialPath
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User, 'FullControl', 'Allow'))
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-18'), 'FullControl', 'Allow'))
    Set-Acl -LiteralPath $credentialPath -AclObject $acl
}
& "$PSScriptRoot\g8-runtime.ps1" start -Service minio
$admin = Get-Content -Raw -LiteralPath $adminPath | ConvertFrom-Json
$env:MC_HOST_g8root = "http://$($admin.accessKey):$($admin.secretKey)@127.0.0.1:9061"
$env:MC_CONFIG_DIR = Join-Path $env:FINAI_RUNTIME_ROOT 'tools\minio\mc-config'
try {
    & "$env:VIRTUAL_ENV\Scripts\python.exe" "$PSScriptRoot\provision-minio-bucket.py"
    $configuration = Get-Content -Raw -LiteralPath $configurationPath | ConvertFrom-Json -AsHashtable
    if (-not $configuration.FINAI_S3_ACCESS_KEY) {
        $policyPath = Join-Path $env:FINAI_RUNTIME_ROOT 'tools\minio\evidence-policy.json'
        @{ Version = '2012-10-17'; Statement = @(
            @{ Effect = 'Allow'; Action = @('s3:GetBucketLocation', 's3:GetBucketVersioning', 's3:ListBucket'); Resource = @('arn:aws:s3:::g8-evidence') },
            @{ Effect = 'Allow'; Action = @('s3:GetObject', 's3:GetObjectVersion', 's3:PutObject'); Resource = @('arn:aws:s3:::g8-evidence/*') }
        ) } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $policyPath -Encoding utf8
        $generated = & $mc --json admin user svcacct add g8root $admin.accessKey --policy $policyPath | ConvertFrom-Json
        if (-not $generated.accessKey -or -not $generated.secretKey) { throw 'MinIO did not return scoped credentials.' }
        $configuration.FINAI_S3_ACCESS_KEY = $generated.accessKey
        $configuration.FINAI_S3_SECRET_KEY = $generated.secretKey
    }
    $configuration.FINAI_S3_ENDPOINT = 'http://127.0.0.1:9061'
    $configuration.FINAI_S3_BUCKET = 'g8-evidence'
    $configuration.FINAI_S3_REGION = 'us-east-1'
    $configuration | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $configurationPath -Encoding utf8
} finally { Remove-Item Env:MC_HOST_g8root -ErrorAction SilentlyContinue }
Write-Host 'Local S3 bucket and scoped credentials configured. Existing evidence and runtime services preserved.'
