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
$controlToken = & $python -c "import secrets; print(secrets.token_urlsafe(48))"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($controlToken)) {
    throw "Could not generate separate demo control token."
}
$env:BOT_DEMO_CONTROL_TOKEN = $controlToken
$env:BOT_STATUS_PATH = (Join-Path $botDir 'runtime\engine_status.json')
$env:BOT_DEMO_ACCOUNT_PATH = (Join-Path $botDir 'runtime\demo_account.json')
$env:BOT_REMOTE_PAUSE_PATH = (Join-Path $botDir 'runtime\remote_pause.flag')
# Start fail-safe: DEMO signal simulation stays paused until explicit
# separate-token phone RESUME. This never modifies KILL_SWITCH.
& $python -c "from src.monitoring.demo_controls import pause_demo; pause_demo()"
if ($LASTEXITCODE -ne 0) { throw "Could not set safe default PAUSED mode." }

New-Item -ItemType Directory -Path (Join-Path $botDir 'runtime') -Force | Out-Null
$logDir = Join-Path $botDir 'runtime\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$api = $null
$worker = $null
try {
    $quotedApiPath = '"' + (Join-Path $PSScriptRoot 'serve_status.py') + '"'
    $quotedWorkerPath = '"' + (Join-Path $PSScriptRoot 'run_live.py') + '"'
    $api = Start-Process -FilePath $python `
        -ArgumentList "$quotedApiPath --port $Port" `
        -WorkingDirectory $botDir -PassThru `
        -RedirectStandardOutput (Join-Path $logDir 'demo-api-out.log') `
        -RedirectStandardError (Join-Path $logDir 'demo-api-error.log')

    $worker = Start-Process -FilePath $python `
        -ArgumentList "$quotedWorkerPath --dry-run --require-demo" `
        -WorkingDirectory $botDir -PassThru `
        -RedirectStandardOutput (Join-Path $logDir 'demo-worker-out.log') `
        -RedirectStandardError (Join-Path $logDir 'demo-worker-error.log')

    # Importing pandas and initializing MT5 may take significantly longer
    # than four seconds on Windows. Poll for a current-session heartbeat.
    $waitStartedAt = [DateTimeOffset]::UtcNow
    $deadline = $waitStartedAt.AddSeconds(90)
    $response = $null
    $lastError = $null
    $ready = $false
    Write-Host 'Waiting for the demo worker and its first fresh heartbeat...' -ForegroundColor Cyan
    do {
        Start-Sleep -Seconds 2
        $api.Refresh()
        $worker.Refresh()
        if ($api.HasExited -or $worker.HasExited) {
            throw "API or worker exited while starting. Check runtime\logs\demo-*-error.log and logs\bot.log."
        }
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/status" `
                -Headers @{Authorization = "Bearer $token"} -TimeoutSec 3
            $lastError = $null
            $observedTime = [DateTimeOffset]::MinValue
            if (-not [string]::IsNullOrWhiteSpace($response.updated_at)) {
                $observedTime = [DateTimeOffset]::Parse(
                    $response.updated_at,
                    [System.Globalization.CultureInfo]::InvariantCulture
                )
            }
            $ready = (
                $response.stale -eq $false -and
                $response.mode -eq 'dry_run' -and
                $response.trading_enabled -eq $false -and
                $response.state -in @('running', 'paused') -and
                $observedTime -ge $waitStartedAt
            )
            if ($response.mode -eq 'live_configuration') {
                throw "SAFETY_STOP: unexpected live configuration; refusing phone pairing."
            }
        } catch {
            if ($_.Exception.Message -like '*SAFETY_STOP*') { throw }
            $lastError = $_.Exception.Message
        }
    } while (-not $ready -and [DateTimeOffset]::UtcNow -lt $deadline)

    if (-not $ready) {
        $stateSummary = if ($null -eq $response) {
            'No status response'
        } else {
            "state=$($response.state) mode=$($response.mode) stale=$($response.stale) updated_at=$($response.updated_at)"
        }
        throw "No fresh demo-only heartbeat after 90 seconds ($stateSummary). Check runtime\logs\demo-worker-error.log and logs\bot.log. Last API error: $lastError"
    }

    @(@{process = 'api'; pid = $api.Id}, @{process = 'worker'; pid = $worker.Id}) |
        ConvertTo-Json | Set-Content -Path (Join-Path $botDir 'runtime\demo-bridge-pids.json')

    Write-Host ''
    Write-Host 'SUCCESS: MT5 DEMO -> Python dry-run worker -> authenticated local status API' -ForegroundColor Green
    Write-Host "API state: $($response.state); mode: $($response.mode); last heartbeat: $($response.updated_at)"
    $demoReady = $false
    for ($attempt = 0; $attempt -lt 10 -and -not $demoReady; $attempt++) {
        try {
            $demo = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/demo-account" `
                -Headers @{Authorization = "Bearer $token"} -TimeoutSec 4
            $demoReady = ($demo.available -eq $true -and
                          $demo.stale -eq $false -and
                          $demo.account_type -eq 'demo')
        } catch {
            Write-Warning "Broker demo account readback not ready yet."
        }
        if (-not $demoReady) { Start-Sleep -Seconds 2 }
    }
    if ($demoReady) {
        Write-Host 'READ-ONLY DEMO PORTFOLIO: Available (balance/equity/positions/history)' -ForegroundColor Green
    } else {
        Write-Warning 'Demo portfolio not ready. Check MT5 connection and logs; amounts remain hidden in the app.'
    }
    Write-Host ''
    Write-Host 'READ-ONLY PAIRING TOKEN (PRIVATE — DO NOT SHARE OR SCREENSHOT):' -ForegroundColor Yellow
    Write-Host $token
    Write-Host ''
    Write-Host 'DEMO PAUSE/RESUME CONTROL TOKEN (PRIVATE — DIFFERENT TOKEN):' -ForegroundColor Yellow
    Write-Host $controlToken
    Write-Host ''
    Write-Host 'Default: PAUSED. No market orders are ever sent by this demo dry-run worker.' -ForegroundColor Cyan
    Write-Host 'To get a private HTTPS address with Tailscale, install/login on PC and Android, then in Administrator PowerShell run:'
    Write-Host "    tailscale serve --bg $Port"
    Write-Host '    tailscale serve status'
    Write-Host 'Open Emtifize AI -> Control center, enter the HTTPS URL and both separate tokens.'
    Write-Host 'Control scope: pause/resume signal simulation only. All trade orders remain disabled.'
    Write-Host 'To shut down the worker/API and stop Tailscale Serve, see docs/DEMO_PHONE_PAIRING.md.'
} catch {
    if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
    if ($worker -and -not $worker.HasExited) { Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item (Join-Path $botDir 'runtime\demo-bridge-pids.json') -Force -ErrorAction SilentlyContinue
    throw
}
