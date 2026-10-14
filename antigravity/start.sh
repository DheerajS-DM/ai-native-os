#!/usr/bin/env bash
# start.sh — Native WSLg launcher for AI Native OS
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

LOG_DIR="$HOME/.local/share/nexus/logs"
mkdir -p "$LOG_DIR"
START_LOG="$LOG_DIR/start.log"

log() {
    local level="$1"
    shift
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [$level] [start.sh:$$] $*"
    echo "$msg"
    echo "$msg" >> "$START_LOG"
}

log "INFO" "=================================================="
log "INFO" "  AI Native OS — by Dheeraj and Dhruv"
log "INFO" "  Native WSLg Desktop Workspace Engine"
log "INFO" "  Startup script initiated from: $DIR"
log "INFO" "=================================================="

# Ensure native WSLg display integration
export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
if [ -d "/mnt/wslg/runtime-dir" ]; then
    export XDG_RUNTIME_DIR="/mnt/wslg/runtime-dir"
fi
export GDK_BACKEND=x11,wayland
export QT_QPA_PLATFORM=xcb

# Environment diagnostics
log "INFO" "Environment Diagnostics:"
log "INFO" "  USER:        $USER (UID: $(id -u), GID: $(id -g))"
log "INFO" "  DISPLAY:     $DISPLAY"
log "INFO" "  WAYLAND:     $WAYLAND_DISPLAY"
log "INFO" "  RUNTIME_DIR: $XDG_RUNTIME_DIR"
log "INFO" "  PYTHON3:     $(which python3 2>/dev/null || echo 'not found') ($(python3 --version 2>&1 || true))"

# Check for model files
MODEL_FILE="$HOME/models/gemma-3n-e2b-it-q4_k_m.gguf"
MMPROJ_FILE="$HOME/models/gemma-3n-e2b-it-mmproj.gguf"
LLAMA_BIN="$HOME/llama.cpp/build/bin/llama-server"

log "INFO" "Checking required binaries and model weights..."
if [ ! -f "$LLAMA_BIN" ]; then
    log "ERROR" "llama-server binary not found at $LLAMA_BIN. Run 'make llama' first."
    exit 1
fi
log "INFO" "Found llama-server binary at $LLAMA_BIN"

if [ ! -f "$MODEL_FILE" ]; then
    log "ERROR" "Model weights not found at $MODEL_FILE. Run 'make model' first."
    exit 1
fi
log "INFO" "Found model file at $MODEL_FILE ($(du -h "$MODEL_FILE" | cut -f1))"

# Compile and initialize Cgroups Allocator
if [ ! -f "$DIR/allocator" ] || [ "$DIR/allocator.c" -nt "$DIR/allocator" ]; then
    log "INFO" "Compiling Cgroups v2 allocator..."
    gcc -O2 -Wall "$DIR/allocator.c" -o "$DIR/allocator" 2>&1 || log "WARNING" "Failed compiling allocator.c"
fi

if [ -f "$DIR/allocator" ]; then
    log "INFO" "Initializing Cgroups v2 resource allocator (70% RAM ceiling)..."
    if sudo -n true 2>/dev/null; then
        sudo "$DIR/allocator" 70 >> "$START_LOG" 2>&1 || true
    else
        "$DIR/allocator" 70 >> "$START_LOG" 2>&1 || true
    fi
fi

# Cgroup process attachment helper
assign_cgroup() {
    local pid="$1"
    local name="$2"
    local cg_procs="/sys/fs/cgroup/nexus/cgroup.procs"
    if [ -d "/sys/fs/cgroup/nexus" ]; then
        if sudo -n true 2>/dev/null; then
            if echo "$pid" | sudo tee "$cg_procs" >/dev/null 2>&1; then
                log "INFO" "Attached $name (PID: $pid) to cgroup /sys/fs/cgroup/nexus"
            else
                log "WARNING" "Could not attach $name (PID: $pid) to $cg_procs via sudo"
            fi
        elif [ -w "$cg_procs" ]; then
            if echo "$pid" > "$cg_procs" 2>/dev/null; then
                log "INFO" "Attached $name (PID: $pid) to cgroup /sys/fs/cgroup/nexus"
            else
                log "WARNING" "Could not attach $name (PID: $pid) to $cg_procs"
            fi
        else
            log "WARNING" "Cgroup $cg_procs not writable by $USER"
        fi
    fi
}

MMPROJ_OPT=""
if [ -s "$MMPROJ_FILE" ]; then
    MMPROJ_OPT="--mmproj $MMPROJ_FILE"
    log "INFO" "Multimodal vision projector enabled: $MMPROJ_FILE ($(du -h "$MMPROJ_FILE" | cut -f1))"
fi

# Check if llama-server is already running
if curl -s -m 1 http://127.0.0.1:8080/health >/dev/null 2>&1; then
    log "INFO" "[1/3] llama-server is already running and healthy on http://127.0.0.1:8080"
    LLAMA_PID=$(pgrep -f "llama-server" | head -n 1)
else
    log "INFO" "[1/3] Starting Gemma-3n llama-server with CUDA acceleration..."
    "$LLAMA_BIN" \
        --model "$MODEL_FILE" \
        $MMPROJ_OPT \
        --host 127.0.0.1 \
        --port 8080 \
        --ctx-size 8192 \
        --threads 4 \
        --n-gpu-layers 99 \
        --metrics > /tmp/llama-server.log 2>&1 &
    LLAMA_PID=$!
    assign_cgroup "$LLAMA_PID" "llama-server"
    log "INFO" "llama-server launched in background (PID: $LLAMA_PID, log: /tmp/llama-server.log)"

    # Wait for server health
    log "INFO" "Waiting for llama-server HTTP endpoint to become healthy..."
    HEALTHY=0
    for i in {1..35}; do
        HEALTH_RESP=$(curl -s -m 2 http://127.0.0.1:8080/health 2>&1 || true)
        METRICS_RESP=$(curl -s -m 2 http://127.0.0.1:8080/metrics 2>&1 || true)
        if [ -n "$HEALTH_RESP" ] || [ -n "$METRICS_RESP" ]; then
            log "INFO" "llama-server is healthy after ${i}s. (Health probe: ${HEALTH_RESP:-HTTP 200 OK})"
            HEALTHY=1
            break
        fi
        if ! kill -0 $LLAMA_PID 2>/dev/null; then
            log "ERROR" "llama-server process died unexpectedly during startup. Log output:"
            tail -n 30 /tmp/llama-server.log | while IFS= read -r line; do log "ERROR" "  $line"; done
            exit 1
        fi
        sleep 1
    done

    if [ $HEALTHY -eq 0 ]; then
        log "ERROR" "llama-server failed health probe after 35s. Terminating PID $LLAMA_PID."
        tail -n 30 /tmp/llama-server.log | while IFS= read -r line; do log "ERROR" "  $line"; done
        kill $LLAMA_PID 2>/dev/null
        exit 1
    fi
fi

log "INFO" "[2/3] Starting Nexus agent socket server..."
python3 socket_server.py >> "$START_LOG" 2>&1 &
AGENT_PID=$!
assign_cgroup "$AGENT_PID" "socket_server"
log "INFO" "Agent socket server started (PID: $AGENT_PID)"

SOCKET_READY=0
for i in {1..15}; do
    if [ -S "/tmp/nexus.sock" ]; then
        log "INFO" "Socket server unix domain socket ready at /tmp/nexus.sock (took ${i}s)"
        SOCKET_READY=1
        break
    fi
    if ! kill -0 $AGENT_PID 2>/dev/null; then
        log "ERROR" "Agent socket server process died unexpectedly."
        tail -n 25 "$LOG_DIR/socket_server.log" 2>/dev/null | while IFS= read -r line; do log "ERROR" "  $line"; done
        kill $LLAMA_PID 2>/dev/null
        exit 1
    fi
    sleep 1
done

if [ $SOCKET_READY -eq 0 ]; then
    log "ERROR" "Socket server failed to initialize /tmp/nexus.sock after 15s. Exiting."
    kill $LLAMA_PID $AGENT_PID 2>/dev/null
    exit 1
fi

log "INFO" "[3/3] Starting PyQt6 sidebar UI on native desktop display ($DISPLAY)..."
python3 sidebar.py >> "$START_LOG" 2>&1 &
SIDEBAR_PID=$!
assign_cgroup "$SIDEBAR_PID" "sidebar"
log "INFO" "PyQt6 Sidebar process started (PID: $SIDEBAR_PID)"

log "INFO" "--------------------------------------------------"
log "INFO" "AI Native OS Workspace successfully started!"
log "INFO" "  - llama-server: PID ${LLAMA_PID:-<external>}"
log "INFO" "  - socket_server: PID $AGENT_PID"
log "INFO" "  - sidebar UI:    PID $SIDEBAR_PID"
log "INFO" "The AI Sidebar is now running on your desktop."
log "INFO" "Press Ctrl+C to stop all services."
log "INFO" "--------------------------------------------------"

shutdown() {
    log "INFO" "Shutdown signal caught! Terminating background processes..."
    kill $SIDEBAR_PID $AGENT_PID 2>/dev/null || true
    rm -f /tmp/nexus.sock 2>/dev/null
    log "INFO" "AI Native OS session ended cleanly."
    exit 0
}

trap shutdown INT TERM EXIT
wait
