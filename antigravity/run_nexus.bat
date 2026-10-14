@echo off
title AI Native OS - Workspace Launcher
color 0B

set "LOGFILE=%USERPROFILE%\.antigravity_launcher.log"
echo [%date% %time%] [INFO] Launching AI Native OS via WSLg launcher... >> "%LOGFILE%"

echo ================================================================
echo           AI Native OS — by Dheeraj and Dhruv
echo           Native WSLg Desktop Workspace Engine
echo ================================================================
echo.

:: 1. Verify WSL Debian status
echo [*] Checking Debian WSL2 environment...
wsl -d Debian -u dheeraj -- uname -s >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Debian WSL2 is not responding. Starting WSL...
    wsl -d Debian -u dheeraj -- echo "WSL initialized"
)

:: 2. Sync project files from Windows to Debian
echo [*] Syncing latest project files into Debian ~/antigravity...
wsl -d Debian -u dheeraj -- bash -c "SRC=\$(wslpath '%~dp0'); mkdir -p ~/antigravity ~/.local/share/nexus/logs && cp -ru \"\$SRC/.\" ~/antigravity/ && chmod +x ~/antigravity/start.sh"

echo.
echo ================================================================
echo   Launching AI Native OS on your Windows Desktop (WSLg)
echo   - AI Sidebar docked with GPU acceleration
echo   - Interactive Terminal and File Manager accessible via Sidebar
echo   - Dynamic Cgroups v2 resource allocator enabled
echo ================================================================
echo.

:: 3. Launch background services and sidebar directly on desktop
wsl -d Debian -u dheeraj -- bash -c "cd ~/antigravity && ./start.sh"

pause
