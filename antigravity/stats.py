"""stats.py — Collect system and inference metrics for the Nexus dashboard."""

from __future__ import annotations

import os
import subprocess
import re
import requests
from typing import Optional

from logger import get_logger

log = get_logger("stats")

CGROUP = "/sys/fs/cgroup/nexus"
LLAMA_METRICS = "http://127.0.0.1:8080/metrics"

# ── cgroup memory ────────────────────────────────────────

def _read_int(path: str) -> Optional[int]:
    try:
        with open(path) as f:
            v = f.read().strip()
            return None if v == "max" else int(v)
    except (FileNotFoundError, ValueError, PermissionError, OSError):
        return None

def get_memory() -> dict:
    cur = _read_int(f"{CGROUP}/memory.current") or 0
    mx = _read_int(f"{CGROUP}/memory.max")
    stat = {}
    stat_path = f"{CGROUP}/memory.stat"
    if os.path.exists(stat_path):
        try:
            with open(stat_path) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) == 2:
                        stat[parts[0]] = int(parts[1])
        except Exception as e:
            log.debug("Failed reading %s: %s", stat_path, e)

    if (mx is None or mx == 0) and cur == 0:
        try:
            import psutil
            vm = psutil.virtual_memory()
            res = {
                "ram_current_mb": int(vm.used // (1024 * 1024)),
                "ram_max_mb": int(vm.total // (1024 * 1024)),
                "ram_anon_mb": 0,
                "ram_swap_mb": 0,
            }
            log.debug("Read system RAM via psutil: %s", res)
            return res
        except Exception as e:
            log.debug("psutil fallback failed: %s", e)

    res = {
        "ram_current_mb": cur // (1024 * 1024),
        "ram_max_mb": (mx or 0) // (1024 * 1024),
        "ram_anon_mb": stat.get("anon", 0) // (1024 * 1024),
        "ram_swap_mb": (_read_int(f"{CGROUP}/memory.swap.current") or 0) // (1024 * 1024),
    }
    log.debug("Read cgroup RAM: %s", res)
    return res

# ── GPU / VRAM ───────────────────────────────────────────

def get_gpu() -> dict:
    """Read VRAM and GPU temp via nvidia-smi. Returns zeros if no GPU."""
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            parts = [p.strip() for p in out.stdout.strip().split(",")]
            if len(parts) >= 3:
                res = {
                    "vram_used_mb": int(parts[0]),
                    "vram_total_mb": int(parts[1]),
                    "gpu_temp_c": int(parts[2]),
                }
                log.debug("Read nvidia-smi telemetry: %s", res)
                return res
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        log.debug("nvidia-smi not available or failed: %s", e)
    return {"vram_used_mb": 0, "vram_total_mb": 0, "gpu_temp_c": 0}

# ── CPU Temperature ──────────────────────────────────────

def get_cpu_temp() -> int:
    """Read CPU temp from thermal zone (Linux sysfs). Returns 0 if unavailable."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            t = int(f.read().strip()) // 1000  # millidegrees → °C
            log.debug("Read CPU temp: %d°C", t)
            return t
    except (FileNotFoundError, ValueError, PermissionError, OSError):
        return 0

# ── Token Usage (from llama-server /metrics) ─────────────

def _parse_prom(text: str, name: str) -> int:
    m = re.search(rf"^{name}\s+(\d+(?:\.\d+)?)", text, re.MULTILINE)
    return int(float(m.group(1))) if m else 0

def get_token_stats() -> dict:
    """Scrape Prometheus metrics from llama-server."""
    try:
        resp = requests.get(LLAMA_METRICS, timeout=3)
        text = resp.text
        prompt = _parse_prom(text, "llamacpp_prompt_tokens_total")
        predict = _parse_prom(text, "llamacpp_tokens_predicted_total")
        res = {
            "tokens_prompt_total": prompt,
            "tokens_predict_total": predict,
            "tokens_total": prompt + predict,
        }
        log.debug("Scraped Prometheus token stats: %s", res)
        return res
    except Exception as e:
        log.debug("llama-server metrics scrape failed (server down?): %s", e)
        return {"tokens_prompt_total": 0, "tokens_predict_total": 0, "tokens_total": 0}

# ── Combined snapshot ────────────────────────────────────

def snapshot() -> dict:
    """One call, all stats."""
    s = {
        **get_memory(),
        **get_gpu(),
        "cpu_temp_c": get_cpu_temp(),
        **get_token_stats(),
    }
    log.debug("Snapshot complete: %s", s)
    return s
