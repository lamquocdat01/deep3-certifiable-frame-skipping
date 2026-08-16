# idf_do.ps1 — run any idf.py command with ESP-IDF exported, from this project.
# Usage:  powershell -ExecutionPolicy Bypass -File idf_do.ps1 build
#         powershell -ExecutionPolicy Bypass -File idf_do.ps1 -p COM4 flash
# Each call is self-contained because export.ps1 only affects the current shell.
param([Parameter(ValueFromRemainingArguments = $true)] $IdfArgs)
$ErrorActionPreference = 'Stop'
$idfPath = 'C:\esp\esp-idf'
if (-not (Test-Path (Join-Path $idfPath 'export.ps1'))) {
    Write-Error "ESP-IDF not found at $idfPath. Install first."
}
. (Join-Path $idfPath 'export.ps1') | Out-Null
Set-Location $PSScriptRoot
Write-Host "idf.py $($IdfArgs -join ' ')" -ForegroundColor Cyan
& idf.py @IdfArgs
exit $LASTEXITCODE
