# ==============================================================================
# File: packaging/windows/Install-StartShortcut.ps1
# Description: Create Desktop / Start Menu shortcuts for Phronesis with brand icon
# Component: Packaging / Windows
# Version: 1.0 (Gold Master)
# Created: 2026-07-31
# Last Update: 2026-07-31
# ==============================================================================
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File Install-StartShortcut.ps1
#   powershell -File Install-StartShortcut.ps1 -DesktopOnly
#   powershell -File Install-StartShortcut.ps1 -StartMenuOnly

param(
    [switch]$DesktopOnly,
    [switch]$StartMenuOnly
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LauncherCmd = Join-Path $ScriptDir "Start-Phronesis.cmd"
$IconPath = Join-Path $ScriptDir "phronesis.ico"

if (-not (Test-Path $LauncherCmd)) {
    throw "Launcher not found: $LauncherCmd"
}
if (-not (Test-Path $IconPath)) {
    throw "Icon not found: $IconPath — run: python tool/generate_brand_assets.py"
}

$installDesktop = -not $StartMenuOnly
$installStartMenu = -not $DesktopOnly

function New-PhronesisShortcut {
    param(
        [string]$ShortcutPath,
        [string]$Description
    )
    $dir = Split-Path -Parent $ShortcutPath
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($ShortcutPath)
    $link.TargetPath = $LauncherCmd
    $link.WorkingDirectory = $ScriptDir
    $link.IconLocation = "$IconPath,0"
    $link.Description = $Description
    $link.Save()
    Write-Host "Shortcut: $ShortcutPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "Phronesis — install Start shortcuts (DEF-001)" -ForegroundColor Cyan
Write-Host "Launcher: $LauncherCmd"
Write-Host "Icon:     $IconPath"
Write-Host ""

if ($installDesktop) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    New-PhronesisShortcut `
        -ShortcutPath (Join-Path $desktop "Phronesis.lnk") `
        -Description "Start Phronesis (Organon cockpit)"
}

if ($installStartMenu) {
    $programs = [Environment]::GetFolderPath("Programs")
    $startFolder = Join-Path $programs "Phronesis"
    New-PhronesisShortcut `
        -ShortcutPath (Join-Path $startFolder "Phronesis.lnk") `
        -Description "Start Phronesis (Organon cockpit)"
}

Write-Host ""
Write-Host "Done. Double-click the shortcut to launch Waitress on http://127.0.0.1:8765/" -ForegroundColor Cyan
