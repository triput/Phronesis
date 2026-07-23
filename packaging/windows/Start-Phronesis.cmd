@echo off
REM VN-B01 — one-step Windows launcher (double-click)
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Phronesis.ps1" %*
endlocal
