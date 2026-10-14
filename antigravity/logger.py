"""logger.py — Centralized, deep logging configuration for Nexus AI Native OS."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

LOG_DIR = Path.home() / ".local/share/nexus/logs"
MASTER_LOG_FILE = LOG_DIR / "nexus_master.log"

_LOG_FORMAT = (
    "[%(asctime)s.%(msecs)03d] [%(levelname)-7s] "
    "[%(process)d:%(threadName)s] [%(name)s:%(filename)s:%(lineno)d] - %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized_loggers = {}
_lock = threading.Lock()

def get_logger(name: str, log_filename: Optional[str] = None) -> logging.Logger:
    """
    Get a configured logger that writes detailed records to:
    1. Module-specific log file (~/.local/share/nexus/logs/<module>.log)
    2. Master log file (~/.local/share/nexus/logs/nexus_master.log)
    3. Console / Stderr
    """
    with _lock:
        if name in _LOG_INITIALIZED:
            return logging.getLogger(name)

        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        # Ensure directory exists
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # 1. Module-specific rotating file handler (5 MB max, 5 backups)
        if log_filename is None:
            log_filename = f"{name}.log"

        mod_log_path = LOG_DIR / log_filename
        try:
            fh = logging.handlers.RotatingFileHandler(
                str(mod_log_path),
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception as e:
            sys.stderr.write(f"[logger] Failed to create module log handler for {mod_log_path}: {e}\n")

        # 2. Master rotating file handler (10 MB max, 5 backups)
        try:
            mfh = logging.handlers.RotatingFileHandler(
                str(MASTER_LOG_FILE),
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            mfh.setLevel(logging.DEBUG)
            mfh.setFormatter(formatter)
            logger.addHandler(mfh)
        except Exception as e:
            sys.stderr.write(f"[logger] Failed to create master log handler: {e}\n")

        # 3. Console handler (INFO and above to console by default, DEBUG if DEBUG=1)
        ch = logging.StreamHandler(sys.stderr)
        console_level = logging.DEBUG if os.environ.get("NEXUS_DEBUG", os.environ.get("ANTIGRAVITY_DEBUG", "1")) == "1" else logging.INFO
        ch.setLevel(console_level)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        _LOG_INITIALIZED[name] = True
        logger.debug("Logger '%s' initialized (Module log: %s, Master: %s)", name, mod_log_path, MASTER_LOG_FILE)
        return logger

_LOG_INITIALIZED = {}

def setup_global_exception_handler(component_name: str):
    """Install global crash hooks for unhandled exceptions and thread exceptions."""
    logger = get_logger(component_name)

    def excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_lines = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical(
            "FATAL UNHANDLED EXCEPTION in %s:\n%s",
            component_name,
            tb_lines,
        )

    def threading_excepthook(args):
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
        tb_lines = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        logger.critical(
            "FATAL UNHANDLED THREAD EXCEPTION in thread %s (%s):\n%s",
            args.thread.name if args.thread else "Unknown",
            component_name,
            tb_lines,
        )

    sys.excepthook = excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = threading_excepthook

    logger.debug("Global crash exception hooks installed for %s", component_name)
