"""agent.py — Stateful agent loop with confirmation protocol and tool execution."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
import requests
from enum import Enum, auto
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Callable, Any, List

import context
import safeguard
from safeguard import Verdict, SafeguardState
from logger import get_logger, setup_global_exception_handler

setup_global_exception_handler("agent")
log = get_logger("agent")

LLAMA_URL = "http://127.0.0.1:8080/v1/chat/completions"
MAX_TOOL_STEPS = 5  # Max chained command executions per user turn

class State(Enum):
    IDLE             = auto()
    THINKING         = auto()
    AWAITING_CONFIRM = auto()
    EXECUTING        = auto()
    REPORTING        = auto()

@dataclass
class AgentSession:
    state: State = State.IDLE
    guard_state: Optional[SafeguardState] = None
    pending_command: Optional[str] = None
    step_count: int = 0

    def __post_init__(self):
        if self.guard_state is None:
            self.guard_state = SafeguardState()

# ── LLM interface ────────────────────────────────────────

def _query_llm(messages: list[dict]) -> Tuple[str, dict]:
    """Send messages to llama-server. Returns (reply_text, usage_dict)."""
    t0 = time.perf_counter()
    msg_count = len(messages)
    log.debug("Sending %d messages to llama-server at %s...", msg_count, LLAMA_URL)
    try:
        resp = requests.post(
            LLAMA_URL,
            json={
                "model": "gemma-3n-e2b",
                "messages": messages,
                "max_tokens": 1536,
                "temperature": 0.6,
                "stop": ["</cmd>"],  # Catch tag closure
            },
            timeout=180,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        reply = choice["message"].get("content", "") or ""
        usage = data.get("usage", {})
        finish_reason = choice.get("finish_reason", "unknown")

        log.info(
            "LLM query completed in %.2fms | Finish: %s | Prompt tokens: %s, Completion: %s",
            elapsed_ms,
            finish_reason,
            usage.get("prompt_tokens", "?"),
            usage.get("completion_tokens", "?"),
        )
        log.debug("LLM raw reply (len: %d): %.200s...", len(reply), reply)

        # Re-append stop token if it caused the finish
        if finish_reason == "stop" and "<cmd" in reply and "</cmd>" not in reply:
            reply += "</cmd>"

        return reply, usage
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        log.error("LLM query failed after %.2fms: %s", elapsed_ms, e, exc_info=True)
        return f"[LLM error: {e}]", {}

def _extract_command(reply: str) -> Tuple[Optional[str], bool]:
    """
    Extract command from <cmd>...</cmd> or <cmd confirm>...</cmd>.
    Returns (command_str, needs_confirmation).
    """
    m = re.search(r"<cmd(?:\s+confirm(?:=\S+)?)?>(.*?)</cmd>", reply, re.DOTALL | re.IGNORECASE)
    if not m:
        log.debug("No <cmd> block detected in reply.")
        return None, False
    needs_confirm = bool(re.search(r"<cmd\s+confirm", reply, re.IGNORECASE))
    cmd = m.group(1).strip()
    log.info("Extracted command from reply: '%s' (LLM requested confirm: %s)", cmd, needs_confirm)
    return cmd, needs_confirm

# ── Command execution ────────────────────────────────────

def _run_command(command: str) -> str:
    t0 = time.perf_counter()
    work_dir = str(Path.home())
    log.info("Executing shell command: '%s' (cwd: %s)", command, work_dir)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=work_dir,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        out = result.stdout.strip()
        err = result.stderr.strip()
        log.info(
            "Command '%s' finished in %.2fms with returncode %d (stdout len: %d, stderr len: %d)",
            command,
            elapsed_ms,
            result.returncode,
            len(out),
            len(err),
        )
        if result.returncode != 0 and err:
            err_msg = f"[exit {result.returncode}] {err}"
            out = f"{out}\n{err_msg}" if out else err_msg
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        log.warning("Command '%s' timed out after %.2fms (60s limit)", command, elapsed_ms)
        return "⚠ Command timed out after 60 seconds."
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        log.error("Command '%s' execution error after %.2fms: %s", command, elapsed_ms, e, exc_info=True)
        return f"⚠ Execution failed: {e}"

# ── Main processing loop ────────────────────────────────

async def process_message(
    user_text: str,
    session: AgentSession,
    send_fn: Callable[[dict], Any],
    confirm_fn: Callable[[], Any],
    media: Optional[List[dict]] = None,
) -> None:
    """
    Process a user message through the agent state machine.

    send_fn(msg: dict)       — send a message to the sidebar
    confirm_fn() -> bool     — await user confirmation (async)
    """
    session.state = State.THINKING
    session.step_count = 0
    log.info("Starting agent turn for query: %.100s...", user_text)

    # Build prompt messages
    if media and len(media) > 0:
        log.info("Building multimodal message with %d media items", len(media))
        content_items = [{"type": "text", "text": user_text}]
        for idx, item in enumerate(media):
            if item.get("type") == "image":
                b64 = item.get("data", "")
                log.debug("Attaching image #%d (b64 length: %d)", idx + 1, len(b64))
                content_items.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                })
        context.append("user", f"[Multimodal message] {user_text}")
        messages = context.get_instructions() + context.get_recent(60)
        messages[-1]["content"] = content_items
    else:
        messages = context.build_prompt(user_text)

    while session.step_count < MAX_TOOL_STEPS:
        session.step_count += 1
        log.info("Agent Step [%d/%d] in state: %s", session.step_count, MAX_TOOL_STEPS, session.state.name)

        # Query LLM
        reply, usage = _query_llm(messages)
        context.append("assistant", reply)

        # Send reply text to sidebar
        await send_fn({
            "type": "reply",
            "text": reply,
            "usage": usage,
        })

        # Check for command
        cmd, llm_wants_confirm = _extract_command(reply)
        if cmd is None:
            log.info("No tool command requested. Ending turn.")
            session.state = State.IDLE
            return

        # Safeguard validation
        verdict, reason = safeguard.check(cmd, session.guard_state)
        log.info("Safeguard verdict for '%s': %s (Reason: %s)", cmd, verdict.value, reason)

        if verdict in (Verdict.BLOCK, Verdict.LOCKED):
            log.warning("Command '%s' BLOCKED by safeguard: %s", cmd, reason)
            await send_fn({"type": "blocked", "command": cmd, "reason": reason})
            context.append("system", f"Command `{cmd}` was blocked: {reason}")
            session.state = State.IDLE
            return

        if verdict == Verdict.CONFIRM or llm_wants_confirm:
            session.state = State.AWAITING_CONFIRM
            session.pending_command = cmd
            log.info("Requesting interactive confirmation from user for command: '%s'", cmd)
            await send_fn({
                "type": "confirm",
                "command": cmd,
                "reason": reason,
            })
            approved = await confirm_fn()
            session.pending_command = None
            log.info("User confirmation result for '%s': %s", cmd, "APPROVED" if approved else "REJECTED")
            if not approved:
                context.append("system", f"User rejected command: `{cmd}`")
                await send_fn({"type": "info", "text": "Command cancelled by user."})
                session.state = State.IDLE
                return

        # Execute
        session.state = State.EXECUTING
        await send_fn({"type": "executing", "command": cmd})
        output = _run_command(cmd)

        session.state = State.REPORTING
        await send_fn({"type": "cmd_result", "command": cmd, "output": output})

        # Feed command output back to LLM context for evaluation/follow-up
        context.append("system", f"Command `{cmd}` output:\n{output}")
        messages = context.build_prompt("")  # Empty user text, get refreshed context

    # Reached limit
    log.warning("Reached maximum allowed chained tool steps (%d). Terminating loop.", MAX_TOOL_STEPS)
    await send_fn({"type": "info", "text": f"Reached max {MAX_TOOL_STEPS} command steps."})
    session.state = State.IDLE
