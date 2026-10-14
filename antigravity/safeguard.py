"""safeguard.py — Path-aware, confirmation-gated command filter."""

from __future__ import annotations

import re
import shlex
from enum import Enum
from dataclasses import dataclass
from typing import Tuple

from logger import get_logger

log = get_logger("safeguard")

class Verdict(Enum):
    ALLOW   = "allow"          # Execute immediately
    CONFIRM = "confirm"        # Ask user first, then execute
    BLOCK   = "block"          # Never execute
    LOCKED  = "locked"         # Too many violations, session locked

@dataclass
class SafeguardState:
    violations: int = 0
    LOCK_THRESHOLD: int = 5

    def record_violation(self) -> None:
        self.violations += 1
        log.warning("Safeguard violation recorded (count: %d/%d)", self.violations, self.LOCK_THRESHOLD)

    def is_locked(self) -> bool:
        return self.violations >= self.LOCK_THRESHOLD

    def reset(self) -> None:
        log.info("Safeguard state reset (violations reset from %d to 0)", self.violations)
        self.violations = 0

# ── Protected system paths ───────────────────────────────

SYSTEM_PATHS = (
    "/usr", "/bin", "/sbin", "/lib", "/lib64",
    "/etc", "/boot", "/var", "/sys", "/proc", "/dev",
    "/snap", "/root",
)

READ_ONLY_COMMANDS = {
    "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep",
    "find", "locate", "which", "whereis", "file", "stat", "readlink",
    "echo", "printf", "date", "cal", "whoami", "id", "hostname",
    "uname", "uptime", "free", "df", "du", "lsblk", "lscpu",
    "ps", "top", "htop", "pgrep", "pwd", "env", "printenv",
    "man", "help", "type", "history", "sensors",
}

ALWAYS_BLOCKED_PATTERNS = [
    r"\brm\s+.*(-[a-zA-Z]*r|--recursive)", # rm -r, rm -rf, rm -fr, rm --recursive
    r"\bmkfs\b",                       # format filesystem
    r"\bdd\s+.*of=/dev/",             # dd to raw device
    r"\bfdisk\b", r"\bparted\b",      # partition tools
    r"\bshred\b",                      # secure erase
    r":\(\)\s*\{",                     # fork bomb
    r"\b(shutdown|reboot|halt|poweroff)\b",
    r"\biptables\s+-F\b",             # flush firewall
    r"\bsystemctl\s+(disable|mask)\s+",
    r">\s*/dev/sd[a-z]",              # write to raw disk
    r"\bchmod\s+(-R\s+)?777\s+/",     # world-writable from root
]

WRITE_COMMANDS = {
    "rm", "mv", "cp", "touch", "mkdir", "rmdir", "chmod", "chown",
    "tee", "sed", "awk", "truncate", "install", "ln", "unlink"
}

def _get_first_token(cmd: str) -> str:
    try:
        return shlex.split(cmd)[0].split("/")[-1]
    except (ValueError, IndexError):
        return ""

def _targets_system_path(cmd: str) -> bool:
    """Check if any argument or redirection in the command references a protected system path."""
    for sp in SYSTEM_PATHS:
        # Match standalone path or subpath boundary (e.g. /etc, /etc/, /etc/passwd)
        pattern = rf"(?:^|[\s\"'<>=|;&`]){re.escape(sp)}(?:[/\"'\s;|<>&`$]|$)"
        if re.search(pattern, cmd):
            log.debug("Command '%s' matched protected system path '%s'", cmd, sp)
            return True
    return False

def check(cmd: str, state: SafeguardState) -> Tuple[Verdict, str]:
    """
    Evaluate a command. Returns (Verdict, reason).
    """
    cmd = cmd.strip()
    log.debug("Evaluating safeguard check for command: '%s' (current violations: %d)", cmd, state.violations)
    if not cmd:
        return Verdict.BLOCK, "Empty command."

    if state.is_locked():
        log.warning("Command evaluation rejected: session is LOCKED (%d violations)", state.violations)
        return Verdict.LOCKED, (
            f"Command execution is locked after {state.LOCK_THRESHOLD} safety violations. "
            "Send an unlock request to reset."
        )

    # 1. Always-blocked patterns (regardless of path)
    for pattern in ALWAYS_BLOCKED_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            state.record_violation()
            log.warning("Command '%s' matched hard-blocked pattern '%s'", cmd, pattern)
            return Verdict.BLOCK, f"Hard-blocked: matches safety pattern `{pattern}`"

    first = _get_first_token(cmd)
    has_redirect = bool(re.search(r"[><]", cmd))
    has_chain_or_pipe = bool(re.search(r"[;&|`$\(]", cmd))

    # 2. Block any command that modifies or redirects into protected system paths
    targets_sys = _targets_system_path(cmd)
    if targets_sys:
        # Allow purely read-only commands without output redirection on system paths (e.g., cat /etc/hosts)
        if first in READ_ONLY_COMMANDS and not has_redirect:
            if has_chain_or_pipe:
                log.info("Command '%s' is a complex/piped system query -> CONFIRM", cmd)
                return Verdict.CONFIRM, "Complex/piped system query — user confirmation required."
            log.info("Command '%s' is a safe read-only system query -> ALLOW", cmd)
            return Verdict.ALLOW, "Read-only system query."
        state.record_violation()
        log.warning("Command '%s' attempted to modify system path -> BLOCK", cmd)
        return Verdict.BLOCK, "Cannot modify system-protected paths."

    # 3. Read-only commands without redirection or chaining → always allow
    if first in READ_ONLY_COMMANDS and not (has_redirect or has_chain_or_pipe):
        log.info("Command '%s' is a pure read-only command -> ALLOW", cmd)
        return Verdict.ALLOW, "Read-only command."

    # 4. Write/delete commands in user-space → require confirmation
    if first in WRITE_COMMANDS or has_redirect:
        log.info("Command '%s' modifies user files -> CONFIRM", cmd)
        return Verdict.CONFIRM, f"Command `{cmd}` modifies files — user confirmation required."

    # 5. Piped / chained commands → require confirmation
    if has_chain_or_pipe:
        log.info("Command '%s' contains pipes/chaining -> CONFIRM", cmd)
        return Verdict.CONFIRM, "Complex/piped command — user confirmation required."

    # 6. Unknown commands → require confirmation (safest default)
    log.info("Command '%s' (token: '%s') is unknown -> CONFIRM", cmd, first)
    return Verdict.CONFIRM, f"Command `{first}` requires user confirmation."
