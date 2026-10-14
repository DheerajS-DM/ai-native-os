# run_antigravity.ps1 — PowerShell launcher for AI Native OS with Native WSLg integration

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
Write-Host "          Native WSLg Desktop Workspace Engine                  " -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

Log-Message "INFO" "Launcher session initiated. Logs writing to: $LogPath"

# 1. Check Debian WSL2
Log-Message "INFO" "Pinging Debian WSL2 environment..."
try {
    $wslCheck = wsl -d Debian -u dheeraj -- uname -s 2>&1
    Log-Message "SUCCESS" "Debian WSL2 responsive (Kernel: $wslCheck)"
} catch {
    Log-Message "ERROR" "WSL Debian failed initial ping: $_"
    exit 1
}

# 2. Sync project files from Windows into Debian
Log-Message "INFO" "Syncing project source code into Debian ~/antigravity..."
wsl -d Debian -u dheeraj -- mkdir -p /home/dheeraj/antigravity /home/dheeraj/.local/share/nexus/logs
wsl -d Debian -u dheeraj -- cp -ru "/mnt/c/Users/Dheeraj Sutram/Documents/projects/OS/AI OS idk/antigravity/." /home/dheeraj/antigravity/
wsl -d Debian -u dheeraj -- chmod +x /home/dheeraj/antigravity/start.sh

# 3. Launch AI Native OS directly on the Windows desktop via WSLg
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Launching AI Native OS on your Windows Desktop (WSLg)        " -ForegroundColor Green
Write-Host "  - AI Sidebar docked to right edge with GPU acceleration       " -ForegroundColor Green
Write-Host "  - Interactive Terminal & File Manager accessible from sidebar " -ForegroundColor Green
Write-Host "  - Dynamic Cgroups v2 memory allocation enabled                " -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""

Log-Message "INFO" "Starting AI Native OS background engine and sidebar..."
wsl -d Debian -u dheeraj -- bash -c "cd ~/antigravity && ./start.sh"
