# Sets KEY=VALUE in realm\.env (creates it), keeping every other line. Used by the realm .bat files.
param([string]$Key, [string]$Value)
$path = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
$lines = @()
if (Test-Path $path) { $lines = @(Get-Content $path | Where-Object { $_ -notmatch "^$Key=" }) }
$lines += "$Key=$Value"
Set-Content -Path $path -Value $lines -Encoding ascii
