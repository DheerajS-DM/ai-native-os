@echo off
title AI Native OS - Diagnostic Log Inspector
color 0A

powershell.exe -ExecutionPolicy Bypass -File "%~dp0read_logs.ps1"

echo.
echo Press any key to exit...
pause >nul
