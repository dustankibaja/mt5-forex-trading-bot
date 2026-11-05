# Reopen a private QR window without stopping or restarting the bot.
# Decrypts DPAPI keys for THIS Windows user; never prints or writes plaintext.
param([switch]$NoQr, [switch]$ShowTokens)

$ErrorActionPreference = 'Stop'
$botDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $botDir '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Python .venv missing' }

. (Join-Path $PSScriptRoot 'pairing_keys.ps1')
$credentialPath = Join-Path $botDir 'runtime\pairing_keys.dpapi'
$keys = Get-PrivatePairingCredentials -Path $credentialPath

if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
    throw 'Tailscale CLI is not installed or not available.'
}
$status = & tailscale status --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or
    -not $status.Self -or -not $status.Self.DNSName) {
    throw 'Connect the Windows PC to your Tailscale tailnet first.'
}
$dnsName = ([string]$status.Self.DNSName).TrimEnd('.').ToLowerInvariant()
if (-not $dnsName.EndsWith('.ts.net')) {
    throw 'Tailscale did not provide a valid private ts.net DNS name.'
}

$env:EMTIFIZE_PAIR_URL = "https://$dnsName"
$env:BOT_STATUS_READ_TOKEN = $keys.read_token
$env:BOT_DEMO_CONTROL_TOKEN = $keys.control_token

Write-Host 'Private pairing host:' $env:EMTIFIZE_PAIR_URL -ForegroundColor Cyan
if ($ShowTokens) {
    Write-Warning 'THE FOLLOWING ARE PASSWORDS. Do not share them, even with ChatGPT.'
    Write-Host 'Read-only token: ' $keys.read_token -ForegroundColor Yellow
    Write-Host 'Demo-control token: ' $keys.control_token -ForegroundColor Yellow
}
Write-Host 'The QR contains the private pairing secrets. Scan it directly on your phone; never share it.' -ForegroundColor Yellow
if (-not $NoQr) {
    $scriptPath = '"' + (Join-Path $PSScriptRoot 'show_pairing_qr.py') + '"'
    # Spawn a separate GUI so the demo bridge remains running after setup.
    Start-Process -FilePath $python -ArgumentList $scriptPath -WorkingDirectory $botDir
    Write-Host 'Pairing QR window opened. If missing, install requirements and check the desktop session.'
}

# Remove plaintext secrets from this PowerShell process environment.
Remove-Item Env:\BOT_STATUS_READ_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:\BOT_DEMO_CONTROL_TOKEN -ErrorAction SilentlyContinue
