@echo off
REM VN-B01 companion — clean up AppData install footprint
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Uninstall-Phronesis.ps1" %*
endlocal
