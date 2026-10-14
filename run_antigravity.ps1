# run_antigravity.ps1 — PowerShell launcher for AI Native OS with deep telemetry

$LogPath = "$env:USERPROFILE\.antigravity_launcher.log"

function Log-Message {
    param([string]$Level, [string]$Message)
    $Timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $LogLine = "[$Timestamp] [$Level] $Message"
    Add-Content -Path $LogPath -Value $LogLine -ErrorAction SilentlyContinue
    switch ($Level) {
        "INFO"    { Write-Host "[$Timestamp] [*] $Message" -ForegroundColor Cyan }
        "SUCCESS" { Write-Host "[$Timestamp] [OK] $Message" -ForegroundColor Green }
        "WARN"    { Write-Host "[$Timestamp] [!] $Message" -ForegroundColor Yellow }
        "ERROR"   { Write-Host "[$Timestamp] [-] $Message" -ForegroundColor Red }
    }
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "          AI Native OS — by Dheeraj and Dhruv                   " -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

Log-Message "INFO" "Launcher session initiated. Logs writing to: $LogPath"

# 1. Check Debian WSL2
Log-Message "INFO" "Pinging Debian WSL2 environment..."
try {
    $wslCheck = wsl -d Debian -u root -- uname -s 2>&1
    Log-Message "SUCCESS" "Debian WSL2 responsive (Kernel: $wslCheck)"
} catch {
    Log-Message "WARN" "WSL Debian failed initial ping: $_"
}

# 2. Reset X11 locks, sockets, and ensure xrdp is running on port 3390
Log-Message "INFO" "Preparing pristine X11 display socket and restarting xrdp on port 3390..."
$xrdpPrep = wsl -d Debian -u root -- bash -c "/etc/init.d/xrdp stop; pkill -9 xfce4; pkill -9 Xorg; pkill -9 dbus; rm -f /tmp/.X*-lock /tmp/.X11-unix/X10 /tmp/.ICE-unix/*; rm -rf /home/*/.cache/sessions/*; mount -o remount,rw /tmp/.X11-unix 2>/dev/null; chmod 1777 /tmp/.X11-unix 2>/dev/null; mkdir -p /tmp/.ICE-unix; chmod 1777 /tmp/.ICE-unix; /etc/init.d/xrdp start 2>&1"
Log-Message "INFO" "xrdp service output: $xrdpPrep"

# Verify port 3390 is listening in WSL
$portCheck = wsl -d Debian -u root -- ss -tlpn sport = :3390 2>&1
Log-Message "SUCCESS" "Port 3390 status: $portCheck"

# 3. Sync project files from Windows into Debian
Log-Message "INFO" "Syncing project source code into Debian ~/antigravity..."
wsl -d Debian -u dheeraj -- mkdir -p /home/dheeraj/antigravity /home/dheeraj/.local/share/antigravity/logs
wsl -d Debian -u dheeraj -- cp -ru "/mnt/c/Users/Dheeraj Sutram/Documents/projects/OS/AI OS idk/antigravity/." /home/dheeraj/antigravity/
wsl -d Debian -u dheeraj -- chmod +x /home/dheeraj/antigravity/start.sh

Log-Message "INFO" "Configuring isolated XFCE .xsession script..."
wsl -d Debian -u dheeraj -- bash -c "tr -d '\r' < ~/antigravity/dot_xsession.sh > ~/.xsession && chmod +x ~/.xsession"
Log-Message "SUCCESS" ".xsession initialized."

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Connecting to Debian XFCE4 Desktop (localhost:3390)" -ForegroundColor Green
Write-Host "  Credentials: username = dheeraj | password = dheeraj" -ForegroundColor Green
Write-Host "  Diagnostic logs:" -ForegroundColor Gray
Write-Host "    - Windows launcher log: $LogPath" -ForegroundColor Gray
Write-Host "    - Linux master log:     ~/.local/share/antigravity/logs/antigravity_master.log" -ForegroundColor Gray
Write-Host "    - Linux X session log:  ~/.local/share/antigravity/logs/xsession.log" -ForegroundColor Gray
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""

# 4. Open Remote Desktop
Log-Message "INFO" "Launching Windows Remote Desktop Connection (mstsc.exe)..."
Start-Process "mstsc.exe" -ArgumentList "/v:127.0.0.1:3390"
Log-Message "SUCCESS" "Remote Desktop launched successfully."
