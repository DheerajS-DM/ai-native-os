# read_logs.ps1 — Windows PowerShell log reader for AI Native OS
param(
    [int]$Lines = 30,
    [switch]$Follow,
    [string]$Target = ""
)

$WinLog = "$env:USERPROFILE\.antigravity_launcher.log"

function Show-Header {
    param([string]$Title, [string]$Path, [bool]$Exists = $true)
    Write-Host "================================================================" -ForegroundColor DarkCyan
    Write-Host "  $Title" -ForegroundColor White
    if ($Path) {
        if ($Exists) {
            Write-Host "  Source: $Path" -ForegroundColor DarkGray
        } else {
            Write-Host "  Source: $Path (Empty or not yet created)" -ForegroundColor Red
        }
    }
    Write-Host "================================================================" -ForegroundColor DarkCyan
}

function Show-WinLog {
    $hasLog = Test-Path $WinLog
    Show-Header "Windows Launcher Log" $WinLog $hasLog
    if ($hasLog) {
        Get-Content -Path $WinLog -Tail $Lines
    } else {
        Write-Host "(No launcher entries found)" -ForegroundColor DarkGray
    }
    Write-Host ""
}

function Show-WSLLog {
    param([string]$Title, [string]$WSLPath)
    $null = wsl -d Debian -u root -- test -s "$WSLPath"
    $exists = ($LASTEXITCODE -eq 0)
    Show-Header $Title $WSLPath $exists
    if ($exists) {
        wsl -d Debian -u root -- tail -n $Lines "$WSLPath"
    } else {
        Write-Host "(No log entries found in WSL)" -ForegroundColor DarkGray
    }
    Write-Host ""
}

if ($Follow) {
    Show-Header "Live Tail: Antigravity Master Log" "~/.local/share/antigravity/logs/antigravity_master.log" $true
    wsl -d Debian -u dheeraj -- bash -c "mkdir -p ~/.local/share/antigravity/logs && touch ~/.local/share/antigravity/logs/antigravity_master.log && tail -f ~/.local/share/antigravity/logs/antigravity_master.log"
    exit 0
}

if ($Target -ne "") {
    switch ($Target.ToLower()) {
        "launcher"  { Show-WinLog }
        "xsession"  { Show-WSLLog "X11 and XFCE Session Log" "/home/dheeraj/.local/share/antigravity/logs/xsession.log"; Show-WSLLog "XFCE Debug Log" "/home/dheeraj/xfce_debug.log" }
        "start"     { Show-WSLLog "Startup Script Log" "/home/dheeraj/.local/share/antigravity/logs/start.log" }
        "llama"     { Show-WSLLog "llama-server CUDA Log" "/tmp/llama-server.log" }
        "socket"    { Show-WSLLog "Socket Server Log" "/home/dheeraj/.local/share/antigravity/logs/socket_server.log" }
        "sidebar"   { Show-WSLLog "Sidebar PyQt6 UI Log" "/home/dheeraj/.local/share/antigravity/logs/sidebar.log" }
        "safeguard" { Show-WSLLog "Safeguard Security Log" "/home/dheeraj/.local/share/antigravity/logs/safeguard.log" }
        "master"    { Show-WSLLog "Unified Master Log" "/home/dheeraj/.local/share/antigravity/logs/antigravity_master.log" }
        "xrdp"      { Show-WSLLog "XRDP Display Server Log" "/var/log/xrdp.log"; Show-WSLLog "XRDP Sesman Log" "/var/log/xrdp-sesman.log" }
        default {
            Write-Host "Unknown target: $Target" -ForegroundColor Red
            Write-Host "Available targets: launcher, xsession, start, llama, socket, sidebar, safeguard, master, xrdp" -ForegroundColor Yellow
        }
    }
    exit 0
}

Write-Host "================================================================" -ForegroundColor Green
Write-Host "        AI Native OS -- Complete Diagnostic Log Report          " -ForegroundColor Green
Write-Host "        $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')               " -ForegroundColor Gray
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""

# 1. Windows Host Launcher
Show-WinLog

# 2. X11 / XFCE Desktop
Show-WSLLog "1. X11 and XFCE Desktop Session (xsession.log)" "/home/dheeraj/.local/share/antigravity/logs/xsession.log"
Show-WSLLog "2. XFCE Debug Output (xfce_debug.log)" "/home/dheeraj/xfce_debug.log"

# 3. Startup Orchestrator and llama-server
Show-WSLLog "3. Service Startup Orchestrator (start.log)" "/home/dheeraj/.local/share/antigravity/logs/start.log"
Show-WSLLog "4. Local Inference llama-server (llama-server.log)" "/tmp/llama-server.log"

# 4. Agent Socket and Sidebar
Show-WSLLog "5. Antigravity Socket Server (socket_server.log)" "/home/dheeraj/.local/share/antigravity/logs/socket_server.log"
Show-WSLLog "6. PyQt6 Sidebar UI (sidebar.log)" "/home/dheeraj/.local/share/antigravity/logs/sidebar.log"

# 5. Security and Allocator
Show-WSLLog "7. Safeguard Filter Audit (safeguard.log)" "/home/dheeraj/.local/share/antigravity/logs/safeguard.log"
Show-WSLLog "8. Cgroup Allocator Log (antigravity-allocator.log)" "/tmp/antigravity-allocator.log"

# 6. XRDP Remote Desktop
Show-WSLLog "9. XRDP Session Manager (xrdp-sesman.log)" "/var/log/xrdp-sesman.log"
Show-WSLLog "10. XRDP Display Server (xrdp.log)" "/var/log/xrdp.log"

# 7. Unified Master Log
Show-WSLLog "11. Antigravity Master Log (antigravity_master.log)" "/home/dheeraj/.local/share/antigravity/logs/antigravity_master.log"

Write-Host "Diagnostic report complete." -ForegroundColor Green
