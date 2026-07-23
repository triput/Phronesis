# ==============================================================================
# File: packaging/windows/Uninstall-Phronesis.ps1
# Description: VN-B01 cleanup — stop local server, remove AppData data, optional .venv
# Component: Packaging / Windows
# Version: 1.0 (Gold Master)
# Created: 2026-07-21
# Last Update: 2026-07-21
# ==============================================================================
# Does NOT delete the source checkout. Does NOT touch Postgres / DATABASE_URL installs.
# Usage: double-click Uninstall-Phronesis.cmd or: powershell -File Uninstall-Phronesis.ps1
# Flags: -Force (skip UNINSTALL prompt)  -RemoveVenv (also delete repo .venv)

param(
    [switch]$Force,
    [switch]$RemoveVenv
)

$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$DataDir = Join-Path $env:LOCALAPPDATA "Phronesis"
$Port = 8765
$VenvDir = Join-Path $RepoRoot ".venv"

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Stop-PhronesisListeners {
    $stopped = @{}
    try {
        $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        foreach ($c in $conns) {
            $procId = $c.OwningProcess
            if ($procId -and $procId -gt 0 -and -not $stopped.ContainsKey($procId)) {
                Write-Host "Stopping PID $procId"
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                $stopped[$procId] = $true
            }
        }
    } catch { }
    if ($stopped.Count -eq 0) {
        $lines = @(netstat -ano 2>$null | Select-String ":$Port\s+.*LISTENING")
        foreach ($line in $lines) {
            $parts = @(($line.ToString() -split "\s+") | Where-Object { $_ -ne "" })
            if ($parts.Count -lt 1) { continue }
            $procId = $parts[-1]
            if ($procId -match "^\d+$" -and -not $stopped.ContainsKey([int]$procId)) {
                Write-Host "Stopping PID $procId"
                Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
                $stopped[[int]$procId] = $true
            }
        }
    }
    if ($stopped.Count -eq 0) {
        Write-Host "Nothing listening on $Port (ok)."
    }
}

Write-Host ""
Write-Host "Phronesis Windows cleanup" -ForegroundColor Yellow
Write-Host "Repo (kept): $RepoRoot"
Write-Host "Data (removed): $DataDir"
Write-Host ""
Write-Host "This removes local SQLite, .env, and logs under AppData."
Write-Host "Export a backup from Settings first if you need the data."
Write-Host "Source tree is NOT deleted."
Write-Host ""

if (-not $Force) {
    $confirm = Read-Host "Type UNINSTALL to continue"
    if ($confirm.Trim().ToUpperInvariant() -ne "UNINSTALL") {
        Write-Host "Aborted." -ForegroundColor DarkYellow
        exit 0
    }
}

Write-Step "Stopping process listening on port $Port (best-effort)"
Stop-PhronesisListeners
Start-Sleep -Seconds 1

Write-Step "Removing AppData data directory"
if (Test-Path $DataDir) {
    Remove-Item -LiteralPath $DataDir -Recurse -Force -ErrorAction Stop
    Write-Host "Removed $DataDir" -ForegroundColor Green
} else {
    Write-Host "No data directory at $DataDir (already clean)."
}

$doVenv = $RemoveVenv.IsPresent
if (-not $doVenv -and -not $Force) {
    $ans = Read-Host "Also remove repo .venv? [y/N]"
    if ($ans.Trim().ToLowerInvariant() -in @("y", "yes")) {
        $doVenv = $true
    }
}

if ($doVenv) {
    Write-Step "Removing virtualenv"
    if (Test-Path $VenvDir) {
        Remove-Item -LiteralPath $VenvDir -Recurse -Force -ErrorAction Stop
        Write-Host "Removed $VenvDir" -ForegroundColor Green
    } else {
        Write-Host "No .venv at $VenvDir"
    }
} else {
    Write-Host ""
    Write-Host "Left .venv in place (geek/dev reuse)."
}

Write-Host ""
Write-Host "Cleanup complete." -ForegroundColor Green
if (-not $Force) {
    Read-Host "Press Enter to exit"
}
