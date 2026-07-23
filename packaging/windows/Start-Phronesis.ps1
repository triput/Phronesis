# ==============================================================================
# File: packaging/windows/Start-Phronesis.ps1
# Description: VN-B01 one-step Windows launch — venv, AppData SQLite, Waitress, browser
# Component: Packaging / Windows
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================
# Requires: Python 3.11+ on PATH (py launcher preferred). Embeddable CPython is a later wave.
# Usage: double-click Start-Phronesis.cmd or: powershell -File Start-Phronesis.ps1
# Self-heals stale .venv (e.g. copied/moved from another repo path).

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
Set-Location $RepoRoot

$DataDir = Join-Path $env:LOCALAPPDATA "Phronesis"
$HostAddr = "127.0.0.1"
$Port = 8765
$Url = "http://${HostAddr}:${Port}/"

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Find-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += @{ Exe = "py"; Args = @("-3.12") }
        $candidates += @{ Exe = "py"; Args = @("-3.11") }
        $candidates += @{ Exe = "py"; Args = @("-3") }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates += @{ Exe = "python"; Args = @() }
    }
    foreach ($c in $candidates) {
        try {
            $ver = & $c.Exe @($c.Args + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")) 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver) {
                $parts = $ver.Trim().Split(".")
                $maj = [int]$parts[0]; $min = [int]$parts[1]
                if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 11)) {
                    return $c
                }
            }
        } catch { }
    }
    return $null
}

Write-Step "Phronesis Windows launcher (VN-B01)"
Write-Host "Repo: $RepoRoot"
Write-Host "Data: $DataDir"

$py = Find-Python
if (-not $py) {
    Write-Host ""
    Write-Host "Python 3.11+ was not found on PATH." -ForegroundColor Red
    Write-Host "Install from https://www.python.org/downloads/ (check 'Add python.exe to PATH'), then re-run."
    Write-Host "Embeddable runtime packaging is planned for a later Windows package wave."
    Read-Host "Press Enter to exit"
    exit 1
}

$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

function Test-VenvHealthy {
    param([string]$PythonExe, [string]$ExpectedRoot)
    if (-not (Test-Path $PythonExe)) { return $false }
    try {
        $probe = & $PythonExe -c "import sys; print(sys.prefix)" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $probe) { return $false }
        $prefix = (Resolve-Path $probe.Trim()).Path
        $expected = (Resolve-Path $ExpectedRoot).Path
        # Stale venv from another checkout (e.g. LifeOS_Django) → rebuild
        if ($prefix -ne $expected) {
            Write-Host "Stale venv points at '$prefix' (expected '$expected')." -ForegroundColor Yellow
            return $false
        }
        & $PythonExe -m pip --version 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

if (-not (Test-VenvHealthy -PythonExe $VenvPython -ExpectedRoot $VenvDir)) {
    if (Test-Path $VenvDir) {
        Write-Step "Removing broken/stale virtualenv"
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    }
    Write-Step "Creating virtualenv (.venv)"
    & $py.Exe @($py.Args + @("-m", "venv", $VenvDir))
    if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv" }
    if (-not (Test-Path $VenvPython)) { throw "venv created but python.exe missing" }
}

Write-Step "Ensuring dependencies"
# Use python -m pip (avoids broken pip.exe launchers with hardcoded old paths)
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "logs") | Out-Null

$EnvFile = Join-Path $DataDir ".env"
$Example = Join-Path $RepoRoot ".env.example"
if (-not (Test-Path $EnvFile)) {
    Write-Step "Creating $EnvFile"
    $secret = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })
    if (Test-Path $Example) {
        $text = Get-Content $Example -Raw
        $text = $text -replace "SECRET_KEY=.*", "SECRET_KEY=$secret"
        $text = $text -replace "DEBUG=True", "DEBUG=False"
        if ($text -notmatch "ALLOWED_HOSTS=") {
            $text += "`nALLOWED_HOSTS=localhost,127.0.0.1`n"
        }
        Set-Content -Path $EnvFile -Value $text -Encoding UTF8
    } else {
        $fallbackEnv = @"
SECRET_KEY=$secret
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1
"@
        Set-Content -Path $EnvFile -Value $fallbackEnv -Encoding UTF8
    }
}

$env:PHRONESIS_DATA_DIR = $DataDir
# Never inherit a shell/checkout DATABASE_URL — AppData SQLite is the standalone DB
# unless %LOCALAPPDATA%\Phronesis\.env explicitly sets DATABASE_URL.
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue

Write-Step "Running migrations (AppData SQLite)"
& $VenvPython (Join-Path $RepoRoot "manage.py") migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "migrate failed" }

Write-Step "Checking owner account"
$ownerPy = @"
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'phronesis_django.settings')
import django
django.setup()
from django.conf import settings
from phronesis_app.services.owner import owner_exists
engine = settings.DATABASES['default'].get('ENGINE', '')
name = settings.DATABASES['default'].get('NAME', '')
print(f'db={engine} name={name}')
print('yes' if owner_exists() else 'no')
"@
$ownerOut = & $VenvPython -c $ownerPy
$ownerLines = @($ownerOut | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
Write-Host ($ownerLines -join "`n")
$ownerCheck = $ownerLines | Select-Object -Last 1
if ($ownerCheck -eq "no") {
    Write-Host "No owner yet - creating default owner." -ForegroundColor Yellow
    Write-Host "  username: owner" -ForegroundColor Yellow
    Write-Host "  password: owner" -ForegroundColor Yellow
    Write-Host "Change the password after first login (or: manage.py create_owner --force)."
    & $VenvPython (Join-Path $RepoRoot "manage.py") create_owner --username owner --password owner --email owner@localhost
    if ($LASTEXITCODE -ne 0) { throw "create_owner failed" }
} else {
    Write-Host "Owner already exists in AppData DB (login with your existing credentials)."
}

Write-Step "Starting Waitress on $Url (Ctrl+C to stop)"
Start-Process $Url
& $VenvPython (Join-Path $RepoRoot "manage.py") run_local --host $HostAddr --port $Port
