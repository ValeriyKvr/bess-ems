@echo off
chcp 65001 >nul
echo ========================================================
echo   Зупинка BESS-EMS локальних сервісів...
echo ========================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-local.ps1"
echo.
pause
