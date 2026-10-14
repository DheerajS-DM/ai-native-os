#!/usr/bin/env bash
# read_logs.sh — Unified log reader and diagnostic inspector for AI Native OS
# Usage:
#   ./read_logs.sh          (prints recent entries from all log files)
#   ./read_logs.sh -n 50    (prints last 50 lines from each log)
#   ./read_logs.sh -f       (follow / live tail on master log)
#   ./read_logs.sh <name>   (view specific log: xsession, start, llama, socket, sidebar, safeguard, xrdp)

LINES=30
FOLLOW=0
TARGET=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--lines)
            LINES="$2"
            shift 2
            ;;
        -f|--follow)
            FOLLOW=1
            shift
            ;;
        *)
            TARGET="$1"
            shift
            ;;
    esac
done

LOG_DIR="$HOME/.local/share/nexus/logs"
MASTER_LOG="$LOG_DIR/nexus_master.log"
XSESSION_LOG="$LOG_DIR/xsession.log"
XFCE_DEBUG="$HOME/xfce_debug.log"
START_LOG="$LOG_DIR/start.log"
LLAMA_LOG="/tmp/llama-server.log"
SOCKET_LOG="$LOG_DIR/socket_server.log"
SIDEBAR_LOG="$LOG_DIR/sidebar.log"
SAFEGUARD_LOG="$LOG_DIR/safeguard.log"
STATS_LOG="$LOG_DIR/stats.log"
CONTEXT_LOG="$LOG_DIR/context.log"
ALLOCATOR_LOG="/tmp/nexus-allocator.log"
XRDP_LOG="/var/log/xrdp.log"
SESMAN_LOG="/var/log/xrdp-sesman.log"
XSESSION_ERR="$HOME/.xsession-errors"

# Colors
C_CYAN='\033[0;36m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[1;33m'
C_RED='\033[0;31m'
C_GRAY='\033[0;90m'
C_BOLD='\033[1m'
C_RESET='\033[0m'

header() {
    local title="$1"
    local file="$2"
    echo -e "${C_CYAN}================================================================${C_RESET}"
    echo -e "${C_BOLD}  $title${C_RESET}"
    if [ -n "$file" ]; then
        if [ -f "$file" ]; then
            local sz=$(du -h "$file" 2>/dev/null | cut -f1)
            local mod=$(date -r "$file" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || stat -c "%y" "$file" 2>/dev/null | cut -d'.' -f1)
            echo -e "${C_GRAY}  Path: $file | Size: $sz | Modified: $mod${C_RESET}"
        else
            echo -e "${C_GRAY}  Path: $file ${C_RED}(File not found or empty)${C_RESET}"
        fi
    fi
    echo -e "${C_CYAN}================================================================${C_RESET}"
}

print_file() {
    local title="$1"
    local path="$2"
    header "$title" "$path"
    if [ -f "$path" ] && [ -s "$path" ]; then
        if [ -r "$path" ]; then
            tail -n "$LINES" "$path"
        elif sudo -n true 2>/dev/null; then
            sudo tail -n "$LINES" "$path"
        else
            echo -e "${C_GRAY}(Permission denied to read $path without sudo)${C_RESET}"
        fi
    else
        echo -e "${C_GRAY}(No log entries found)${C_RESET}"
    fi
    echo ""
}

if [ "$FOLLOW" -eq 1 ]; then
    header "Live Tail: Nexus Master Log" "$MASTER_LOG"
    if [ ! -f "$MASTER_LOG" ]; then
        mkdir -p "$LOG_DIR"
        touch "$MASTER_LOG"
    fi
    exec tail -f "$MASTER_LOG"
fi

if [ -n "$TARGET" ]; then
    case "$TARGET" in
        master)    print_file "Nexus Master Log" "$MASTER_LOG" ;;
        xsession)  print_file "X11 / XFCE Session Log" "$XSESSION_LOG"; print_file "XFCE Debug Log" "$XFCE_DEBUG" ;;
        start)     print_file "Startup Script Log" "$START_LOG" ;;
        llama)     print_file "llama-server CUDA Log" "$LLAMA_LOG" ;;
        socket)    print_file "Socket Server Log" "$SOCKET_LOG" ;;
        sidebar)   print_file "Sidebar PyQt6 UI Log" "$SIDEBAR_LOG" ;;
        safeguard) print_file "Safeguard Security Log" "$SAFEGUARD_LOG" ;;
        stats)     print_file "Telemetry & Metrics Log" "$STATS_LOG" ;;
        context)   print_file "SQLite Context DB Log" "$CONTEXT_LOG" ;;
        allocator) print_file "C Memory Allocator Log" "$ALLOCATOR_LOG" ;;
        xrdp)      print_file "xrdp Service Log" "$XRDP_LOG"; print_file "xrdp-sesman Session Log" "$SESMAN_LOG" ;;
        errors)    print_file "Xsession Errors" "$XSESSION_ERR" ;;
        *)
            echo -e "${C_RED}Unknown log target: $TARGET${C_RESET}"
            echo -e "Available targets: master, xsession, start, llama, socket, sidebar, safeguard, stats, context, allocator, xrdp, errors"
            exit 1
            ;;
    esac
    exit 0
fi

# Default overview mode: print summary of all components
echo -e "${C_BOLD}${C_GREEN}AI Native OS — Comprehensive Diagnostic Log Report${C_RESET}"
echo -e "${C_GRAY}Generated on: $(date '+%Y-%m-%d %H:%M:%S')${C_RESET}\n"

# 1. Desktop Session & X11
print_file "1. X11 & XFCE Desktop Session (xsession.log)" "$XSESSION_LOG"
print_file "2. XFCE Debug Output (xfce_debug.log)" "$XFCE_DEBUG"

# 2. Startup Orchestrator & llama.cpp
print_file "3. Service Startup Orchestrator (start.log)" "$START_LOG"
print_file "4. Local Inference llama-server (llama-server.log)" "$LLAMA_LOG"

# 3. Agent & Socket Server
print_file "5. Nexus Socket Server (socket_server.log)" "$SOCKET_LOG"
print_file "6. PyQt6 Sidebar UI (sidebar.log)" "$SIDEBAR_LOG"

# 4. Safeguard & Allocator
print_file "7. Safeguard Filter & Safety Audit (safeguard.log)" "$SAFEGUARD_LOG"
print_file "8. Cgroup Memory Allocator (nexus-allocator.log)" "$ALLOCATOR_LOG"

# 5. Remote Desktop Display Server
print_file "9. XRDP Session Manager (xrdp-sesman.log)" "$SESMAN_LOG"
print_file "10. XRDP Display Server (xrdp.log)" "$XRDP_LOG"

# 6. Master Log Tail
print_file "11. Nexus Master Unified Log (nexus_master.log)" "$MASTER_LOG"

echo -e "${C_BOLD}${C_GREEN}Done. Use './read_logs.sh -f' to live-tail the master log or './read_logs.sh <component>' for a specific log.${C_RESET}"
