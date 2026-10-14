#!/bin/bash
# dot_xsession.sh — Deeply instrumented X11/XFCE4 startup session

LOG_DIR="$HOME/.local/share/nexus/logs"
mkdir -p "$LOG_DIR"
XSESSION_LOG="$LOG_DIR/xsession.log"
DEBUG_LOG="$HOME/xfce_debug.log"

exec > >(tee -a "$XSESSION_LOG" "$DEBUG_LOG") 2>&1
set -x

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [dot_xsession:$$] $*"
}

log "=================================================="
log "  Nexus XFCE Session Bootstrapping"
log "  PID: $$, User: $USER (UID: $(id -u), GID: $(id -g))"
log "=================================================="

# Export standard XDG environment
export XDG_CONFIG_HOME=$HOME/.config
export XDG_DATA_HOME=$HOME/.local/share
export XDG_CACHE_HOME=$HOME/.cache
export XDG_RUNTIME_DIR=/run/user/$(id -u)

export XDG_CURRENT_DESKTOP=XFCE
export XDG_SESSION_DESKTOP=xfce
export XDG_SESSION_TYPE=x11
export NO_AT_BRIDGE=1

# The Wayland WSLg Poison Pill Neutralizer
export GDK_BACKEND=x11
export QT_QPA_PLATFORM=xcb
unset WAYLAND_DISPLAY
unset DBUS_SESSION_BUS_ADDRESS

log "System & Environment Diagnostics:"
log "  DISPLAY:             ${DISPLAY:-<unset>}"
log "  XDG_RUNTIME_DIR:     $XDG_RUNTIME_DIR"
log "  XDG_CONFIG_HOME:     $XDG_CONFIG_HOME"
log "  X11 Socket Check:    $(ls -la /tmp/.X11-unix/ 2>/dev/null || echo 'not found')"
log "  ICE Socket Check:    $(ls -la /tmp/.ICE-unix/ 2>/dev/null || echo 'not found')"

mkdir -p "$XDG_CONFIG_HOME/xfce4/xfconf"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR" 2>/dev/null || true

# Session exit diagnosis trap
on_session_exit() {
    local rc=$?
    log "Session termination caught! (Exit code: $rc)"
    log "Active processes at exit:"
    ps -u "$USER" -o pid,ppid,%cpu,%mem,stat,comm 2>&1 | while IFS= read -r line; do log "  $line"; done
    log "End of session log."
    exit $rc
}
trap on_session_exit EXIT INT TERM HUP

# Background heartbeat logger
(
    while true; do
        sleep 30
        log "[Heartbeat] Session active (XFCE PID: $$, uptime: $(uptime -p 2>/dev/null || echo '?'))"
    done
) &
HEARTBEAT_PID=$!

log "Handing off execution to dbus-run-session startxfce4..."
dbus-run-session -- startxfce4
SESSION_STATUS=$?

kill $HEARTBEAT_PID 2>/dev/null || true
log "startxfce4 exited with status $SESSION_STATUS"
exit $SESSION_STATUS
