# Rotate Emtifize AI private DEMO pairing tokens.
# Run only AFTER stopping both bridge Python processes.
param([switch]$ConfirmRotation)
$ErrorActionPreference = "Stop"
$botDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $ConfirmRotation) {
    throw "Stop the bridge, then run: powershell -File scripts/rotate_pairing.ps1 -ConfirmRotation"
}

$processes = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'")
foreach ($process in $processes) {
    if ($process.CommandLine -and
            $process.CommandLine -match '(serve_status|run_live)\.py' -and
            $process.CommandLine -like "*$botDir*") {
        throw "Bridge still active (PID $($process.ProcessId)). Stop it safely before rotation."
    }
}

$files = @(
    (Join-Path $botDir 'runtime\read-token.dpapi'),
    (Join-Path $botDir 'runtime\control-token.dpapi')
)
foreach ($file in $files) {
    if (Test-Path $file) {
        Remove-Item -LiteralPath $file -Force -ErrorAction Stop
    }
}
Write-Host "Pairing secrets cleared. Restart bridge to create new encrypted tokens and a fresh QR." -ForegroundColor Green
Write-Host "Previously paired phones will receive 401 and must scan the new QR."
