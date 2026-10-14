@echo off
title AI Native OS - Nexus Launcher
color 0B

set "LOGFILE=%USERPROFILE%\.nexus_launcher.log"
echo [%date% %time%] [INFO] Launching Nexus AI Native OS batch launcher... >> "%LOGFILE%"

echo ================================================================
echo           AI Native OS (Nexus) -- by Dheeraj and Dhruv
echo ================================================================
echo.

:: 1. Verify WSL Debian status
echo [*] Checking Debian WSL2 environment...
echo [%date% %time%] [INFO] Checking Debian WSL2 environment... >> "%LOGFILE%"
wsl -d Debian -u root -- uname -s >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Debian WSL2 is not responding. Starting WSL...
    echo [%date% %time%] [WARN] Debian WSL2 was not running, initializing... >> "%LOGFILE%"
    wsl -d Debian -u root -- echo "WSL initialized"
)

:: 2. Ensure X11 socket directory is writable and xrdp is running on port 3390
echo [*] Preparing X11 display socket and xrdp (Port 3390)...
echo [%date% %time%] [INFO] Starting xrdp and configuring X11/ICE sockets... >> "%LOGFILE%"
wsl -d Debian -u root -- bash -c "mount -o remount,rw /tmp/.X11-unix 2>/dev/null; chmod 1777 /tmp/.X11-unix 2>/dev/null; mkdir -p /tmp/.ICE-unix; chmod 1777 /tmp/.ICE-unix; /etc/init.d/xrdp status >/dev/null 2>&1 || /etc/init.d/xrdp start"

:: 3. Sync project files from Windows to Debian
echo [*] Syncing latest Nexus files into Debian...
wsl -d Debian -u dheeraj -- bash -c "SRC=\$(wslpath '%~dp0'); mkdir -p ~/nexus ~/.local/share/nexus/logs && cp -ru \"\$SRC/.\" ~/nexus/ && chmod +x ~/nexus/start.sh && tr -d '\r' < ~/nexus/dot_xsession.sh > ~/.xsession && chmod +x ~/.xsession"

echo.
echo ================================================================
echo   Opening Debian XFCE4 Desktop via Remote Desktop Connection
echo.
echo   Login Details:
echo     - Host:      localhost:3390
echo     - Username:  dheeraj
echo     - Password:  dheeraj
echo.
echo   Diagnostics & Logs:
echo     - Windows Launcher Log: %LOGFILE%
echo     - Master Linux Log:     ~/.local/share/nexus/logs/nexus_master.log
echo     - X11 Session Log:      ~/.local/share/nexus/logs/xsession.log
echo ================================================================
echo.

:: 4. Launch Windows Remote Desktop Connection
echo [%date% %time%] [INFO] Starting mstsc.exe /v:localhost:3390 >> "%LOGFILE%"
start mstsc /v:localhost:3390

echo [OK] Remote Desktop window launched.
echo.
echo Press any key to exit this launcher window...
pause >nul
