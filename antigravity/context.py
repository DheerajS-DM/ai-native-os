"""context.py — SQLite context store with preloaded system instructions."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import List, Dict

from logger import get_logger

log = get_logger("context")

DB_PATH = Path.home() / ".local/share/nexus/context.db"

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS system_instructions (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            role    TEXT NOT NULL DEFAULT 'system',
            content TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            role      TEXT NOT NULL,
            content   TEXT NOT NULL,
            timestamp REAL NOT NULL
        );
    """)
    conn.commit()
    return conn

# ── Preloaded instructions ───────────────────────────────

DEFAULT_INSTRUCTIONS = [
    (0, """You are Nexus, an AI assistant natively integrated into Debian Linux, built by Dheeraj and Dhruv.
You help the user manage their system, answer questions, and run shell commands.
You MUST ask the user for confirmation before executing any command that modifies or deletes files.
You respond concisely, accurately, and clearly."""),

    (1, """SAFETY RULES — you must follow these at all times:
- NEVER run commands that modify system directories: /usr, /bin, /sbin, /lib, /etc, /boot, /var, /sys, /proc, /dev
- NEVER run recursive delete (rm -rf) on any path
- NEVER run mkfs, dd to /dev/*, fdisk, parted, or any disk-formatting command
- NEVER flush iptables, disable systemd services, or modify boot config
- For ANY file deletion or modification, show the user the exact command and wait for confirmation
- You may freely run read-only commands: ls, cat, head, tail, grep, find, df, free, ps, uptime, sensors, etc."""),

    (2, """COMMAND FORMAT:
When you need to run a shell command, output it inside a <cmd> tag:
    <cmd>ls -la /home</cmd>
When a command requires user confirmation (any write/delete), use <cmd confirm>:
    <cmd confirm>rm ~/old_file.txt</cmd>
Output at most ONE command per response. Explain what it does before the tag."""),
]

def seed_instructions() -> None:
    """Insert default instructions if the table is empty (first boot)."""
    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM system_instructions").fetchone()[0]
    log.info("Checking system instructions in %s (current count: %d)", DB_PATH, count)
    if count == 0:
        conn.executemany(
            "INSERT INTO system_instructions (priority, content) VALUES (?, ?)",
            DEFAULT_INSTRUCTIONS,
        )
        conn.commit()
        log.info("[context] Seeded %d system instructions into SQLite DB.", len(DEFAULT_INSTRUCTIONS))
    conn.close()

def get_instructions() -> List[Dict[str, str]]:
    conn = _connect()
    rows = conn.execute(
        "SELECT role, content FROM system_instructions ORDER BY priority ASC"
    ).fetchall()
    conn.close()
    log.debug("Fetched %d system instruction rows from SQLite", len(rows))
    return [{"role": r, "content": c} for r, c in rows]

# ── Conversation history ─────────────────────────────────

def append(role: str, content: str) -> None:
    t0 = time.perf_counter()
    conn = _connect()
    conn.execute(
        "INSERT INTO messages (role, content, timestamp) VALUES (?, ?, ?)",
        (role, content, time.time())
    )
    conn.commit()
    conn.close()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    log.debug("Appended '%s' message to context DB (len: %d) in %.2fms", role, len(content), elapsed_ms)

def get_recent(n: int = 60) -> List[Dict[str, str]]:
    t0 = time.perf_counter()
    conn = _connect()
    rows = conn.execute(
        "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    log.debug("Retrieved %d recent messages in %.2fms", len(rows), elapsed_ms)
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def clear_conversation() -> None:
    conn = _connect()
    conn.execute("DELETE FROM messages")
    conn.commit()
    conn.close()
    log.info("Cleared all conversation history from messages table.")

def build_prompt(user_message: str) -> List[Dict[str, str]]:
    """Build the full message list: instructions + history + new user message."""
    if user_message:
        append("user", user_message)
    instr = get_instructions()
    history = get_recent(60)
    log.info("Built prompt context: %d instructions + %d history turns", len(instr), len(history))
    return instr + history
