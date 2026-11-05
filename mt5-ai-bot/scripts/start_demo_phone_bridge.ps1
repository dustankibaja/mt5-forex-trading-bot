# Safe, single-operator Windows setup for read-only phone status monitoring.
# Requires Python venv, MT5 demo account, and optional Tailscale on PC/phone.
# Does not place ANY orders, does not configure a publicly accessible service.
param(
    [int] $Port = 8787
)

$ErrorActionPreference = 'Stop'
$botDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $botDir
$python = Join-Path $botDir '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    throw "Python environment missing. From mt5-ai-bot: py -3.11 -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

Write-Host 'Checking connected MT5 broker account type...' -ForegroundColor Cyan
& $python (Join-Path $PSScriptRoot 'demo_preflight.py')
if ($LASTEXITCODE -ne 0) {
    throw "Demo account verification failed. Open MT5 and sign in to a DEMO account."
}

$token = & $python -c "import secrets; print(secrets.token_urlsafe(48))"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) {
    throw "Could not generate pairing token."
}
$env:BOT_STATUS_READ_TOKEN = $token
$env:BOT_STATUS_PATH = (Join-Path $botDir 'runtime\engine_status.json')

New-Item -ItemType Directory -Path (Join-Path $botDir 'runtime') -Force | Out-Null
$logDir = Join-Path $botDir 'runtime\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$api = $null
$worker = $null
try {
    $api = Start-Process -FilePath $python `
        -ArgumentList @((Join-Path $PSScriptRoot 'serve_status.py'), '--port', "$Port") `
        -WorkingDirectory $botDir -PassThru `
        -RedirectStandardOutput (Join-Path $logDir 'demo-api-out.log') `
        -RedirectStandardError (Join-Path $logDir 'demo-api-error.log')

    $worker = Start-Process -FilePath $python `
        -ArgumentList @((Join-Path $PSScriptRoot 'run_live.py'), '--dry-run', '--require-demo') `
        -WorkingDirectory $botDir -PassThru `
        -RedirectStandardOutput (Join-Path $logDir 'demo-worker-out.log') `
        -RedirectStandardError (Join-Path $logDir 'demo-worker-error.log')

    Start-Sleep -Seconds 4
    $api.Refresh()
    $worker.Refresh()
    if ($api.HasExited -or $worker.HasExited) {
        throw "API or worker exited early. Check log files under runtime\logs."
    }
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/status" `
        -Headers @{Authorization = "Bearer $token"} -TimeoutSec 6
    if ($response.stale -or $response.mode -ne 'dry_run') {
        throw "Engine heartbeat was not fresh dry-run; refusing phone pairing."
    }

    @(@{process = 'api'; pid = $api.Id}, @{process = 'worker'; pid = $worker.Id}) |
        ConvertTo-Json | Set-Content -Path (Join-Path $botDir 'runtime\demo-bridge-pids.json')

    Write-Host ''
    Write-Host 'SUCCESS: MT5 DEMO -> Python dry-run worker -> authenticated local status API' -ForegroundColor Green
    Write-Host "API state: $($response.state); mode: $($response.mode); last heartbeat: $($response.updated_at)"
    Write-Host ''
    Write-Host 'PHONE PAIRING TOKEN (PRIVATE — DO NOT SHARE OR SCREENSHOT):' -ForegroundColor Yellow
    Write-Host $token
    Write-Host ''
    Write-Host 'To get a private HTTPS address with Tailscale, install/login on PC and Android, then in Administrator PowerShell run:'
    Write-Host "    tailscale serve --bg $Port"
    Write-Host '    tailscale serve status'
    Write-Host 'Open Emtifize AI Demo -> DEMO DATA ONLY -> Trading engine, then enter the HTTPS URL and token.'
    Write-Host 'This v1 app can view engine status, not place trades or show broker balances.'
    Write-Host 'To shut down the worker/API and stop Tailscale Serve, see docs/DEMO_PHONE_PAIRING.md.'
} catch {
    if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
    if ($worker -and -not $worker.HasExited) { Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item (Join-Path $botDir 'runtime\demo-bridge-pids.json') -Force -ErrorAction SilentlyContinue
    throw
}
