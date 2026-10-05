# =========================================================
# Deployment script for ASCOM Alpaca Bridge to Home Assistant
# Copies custom_components/ascom_alpaca_bridge to /config/custom_components/ via SCP
# and restarts Home Assistant Core via SSH ("ha core restart").
#
# Settings come from deployconf.secrets (template: deployconf):
#   SSH_URL   host or host:port of the SSH add-on (required, no fallback)
#   SSH_USER  SSH user (default: root)
#   SSH_PW    SSH password (optional, plain text - use only for test systems)
# HA_* entries in the file are not used by this script.
# Without SSH_PW, scp and ssh ask for the password interactively.
#
# Usage:
#   .\deploy.ps1            deploy
#   .\deploy.ps1 -DryRun    show target, auth mode and steps, do not connect
# =========================================================

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# SSH_ASKPASS needs an executable file. This helper is a tiny .cmd that prints the
# password from an environment variable, so the password itself is never written to disk.
function New-AskPassHelper {
    $name = "ha-deploy-askpass-" + [guid]::NewGuid().ToString("N") + ".cmd"
    $path = Join-Path ([System.IO.Path]::GetTempPath()) $name
    $command = '@powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); [Console]::Out.WriteLine($env:HA_DEPLOY_PASSWORD)"'
    [System.IO.File]::WriteAllText($path, $command + "`r`n", (New-Object System.Text.ASCIIEncoding))
    return $path
}

# Splits "host", "host:port" or "ssh://host:port" into host and port (default 22).
function ConvertFrom-SshUrl {
    param([string]$Url)
    $text = ($Url.Trim() -replace '^ssh://', '').TrimEnd('/')
    $sshHost = $text
    $port = 22
    if ($text -match '^([^:]+):(\d+)$') {
        $sshHost = $matches[1]
        $port = [int]$matches[2]
    }
    if ($sshHost -notmatch '^[A-Za-z0-9._-]+$') {
        throw "Invalid host '$sshHost' in SSH_URL (expected host or host:port)"
    }
    if ($port -lt 1 -or $port -gt 65535) {
        throw "Invalid port $port in SSH_URL"
    }
    return [pscustomobject]@{ SshHost = $sshHost; Port = $port }
}

# --- 1. CONFIGURATION & SECRETS ---
$SSH_URL = ""
$SSH_USER = "root"
$SSH_PW = ""
$REMOTE_PATH = "/config/custom_components/"
$LOCAL_FOLDER = "custom_components/ascom_alpaca_bridge"

# Load settings from deployconf.secrets
$secretsFile = Join-Path $PSScriptRoot "deployconf.secrets"
if (-not (Test-Path $secretsFile)) {
    Write-Host "[!] Error: $secretsFile not found. Copy deployconf to deployconf.secrets and fill in SSH_URL." -ForegroundColor Red
    exit 1
}
Get-Content $secretsFile -Encoding UTF8 | ForEach-Object {
    if ($_ -match "^\s*([^#=]+)\s*=\s*(.*)\s*$") {
        $key = $matches[1].Trim()
        $value = $matches[2].Trim()
        if ($key -eq "SSH_URL") { $SSH_URL = $value }
        if ($key -eq "SSH_USER" -and $value -ne "") { $SSH_USER = $value }
        if ($key -eq "SSH_PW") { $SSH_PW = $value }
    }
}

# Validation
if ($SSH_URL -eq "") {
    Write-Host "[!] Error: SSH_URL not found in $secretsFile (example: SSH_URL=192.168.1.10:22)" -ForegroundColor Red
    exit 1
}
try {
    $target = ConvertFrom-SshUrl $SSH_URL
} catch {
    Write-Host "[!] Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
$SSH_HOST = $target.SshHost
$SSH_PORT = $target.Port

if (-not (Test-Path (Join-Path $PSScriptRoot $LOCAL_FOLDER))) {
    Write-Host "[!] Error: $LOCAL_FOLDER not found next to deploy.ps1" -ForegroundColor Red
    exit 1
}

$authMode = if ($SSH_PW -ne "") { "password from deployconf.secrets (SSH_PW)" } else { "interactive (you will be asked for the password)" }

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "[*] Target: ${SSH_USER}@${SSH_HOST}:${SSH_PORT}" -ForegroundColor Cyan
Write-Host "[*] Path:   $REMOTE_PATH" -ForegroundColor Cyan
Write-Host "[*] Auth:   $authMode" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

if ($DryRun) {
    Write-Host "[*] Dry run: no connection is made. Would:" -ForegroundColor Yellow
    Write-Host "    1. upload $LOCAL_FOLDER to $REMOTE_PATH"
    Write-Host "    2. restart Home Assistant Core (ssh: ha core restart)"
    exit 0
}

# --- 2. BUILD COMMANDS ---
# Options shared by scp and ssh. -c fixes MAC errors on some systems.
$sshOptions = @("-c", "aes256-gcm@openssh.com")
if ($SSH_PW -ne "") {
    # One attempt only (a wrong password fails fast), accept new host keys but reject changed ones
    $sshOptions += @("-o", "NumberOfPasswordPrompts=1", "-o", "StrictHostKeyChecking=accept-new", "-o", "PreferredAuthentications=password,keyboard-interactive")
}

# scp: -r recursive, -O legacy protocol, -P port
$scpArgs = @("-r", "-O") + $sshOptions
if ($SSH_PORT -ne 22) { $scpArgs += @("-P", "$SSH_PORT") }
$scpArgs += @($LOCAL_FOLDER, "${SSH_USER}@${SSH_HOST}:${REMOTE_PATH}")

# ssh: -p port
$sshArgs = @() + $sshOptions
if ($SSH_PORT -ne 22) { $sshArgs += @("-p", "$SSH_PORT") }
$sshArgs += @("${SSH_USER}@${SSH_HOST}", "ha core restart")

# --- 3. EXECUTE DEPLOYMENT ---
Write-Host "Starting deployment to Home Assistant ($SSH_HOST)..." -ForegroundColor Cyan
if ($SSH_PW -eq "") {
    Write-Host "(You will be prompted for your password for the upload and again for the restart.)" -ForegroundColor Yellow
}

$askPassHelper = $null
$scpExitCode = 1
$sshExitCode = 0
Push-Location $PSScriptRoot
try {
    if ($SSH_PW -ne "") {
        $askPassHelper = New-AskPassHelper
        $env:SSH_ASKPASS = $askPassHelper
        $env:SSH_ASKPASS_REQUIRE = "force"
        $env:HA_DEPLOY_PASSWORD = $SSH_PW
    }

    & scp @scpArgs
    $scpExitCode = $LASTEXITCODE

    if ($scpExitCode -eq 0) {
        Write-Host "Successfully uploaded ascom_alpaca_bridge to Home Assistant." -ForegroundColor Green
        Write-Host "Restarting Home Assistant Core..." -ForegroundColor Cyan
        & ssh @sshArgs
        $sshExitCode = $LASTEXITCODE
    }
} finally {
    Pop-Location
    Remove-Item Env:SSH_ASKPASS, Env:SSH_ASKPASS_REQUIRE, Env:HA_DEPLOY_PASSWORD -ErrorAction SilentlyContinue
    if ($askPassHelper -and (Test-Path $askPassHelper)) { Remove-Item $askPassHelper -Force }
}

# --- 4. RESULT EVALUATION ---
if ($scpExitCode -eq 0) {
    if ($sshExitCode -ne 0) {
        Write-Host "Warning: the restart command returned exit code $sshExitCode. Restart Home Assistant manually if needed." -ForegroundColor Yellow
    }
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "1. Wait a moment for HA to come back online."
    Write-Host "2. Go to Settings -> Devices & Services -> Add Integration -> ASCOM Alpaca Bridge."
} else {
    Write-Host "Deployment failed. Check SSH_URL, SSH_USER and SSH_PW in deployconf.secrets and the HA SSH add-on settings." -ForegroundColor Red
}
