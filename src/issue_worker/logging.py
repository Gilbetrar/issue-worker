"""File-based logging for issue-worker runs."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".local" / "state" / "issue-worker" / "logs"
MAX_LOG_FILES = 20


def setup_logging(verbose: bool = False) -> Path:
    """Configure logging to both console and a timestamped log file.

    Console output is unchanged (INFO level, plain format).
    Log file captures everything including DEBUG level.

    Returns the path to the log file.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOG_DIR / f"issue-worker-{timestamp}.log"

    # Root logger
    root = logging.getLogger("issue_worker")
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    # File handler — captures everything
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(file_handler)

    # Console handler — mirrors existing print behavior
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console_handler)

    return log_file


def prune_logs() -> int:
    """Remove old log files, keeping only the most recent MAX_LOG_FILES.

    Returns the number of files removed.
    """
    if not LOG_DIR.exists():
        return 0

    log_files = sorted(LOG_DIR.glob("issue-worker-*.log"))
    to_remove = log_files[:-MAX_LOG_FILES] if len(log_files) > MAX_LOG_FILES else []

    for f in to_remove:
        f.unlink()

    return len(to_remove)


def list_log_files() -> list[Path]:
    """Return log files sorted by modification time (newest first)."""
    if not LOG_DIR.exists():
        return []
    return sorted(LOG_DIR.glob("issue-worker-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)


def get_logger() -> logging.Logger:
    """Get the issue_worker logger."""
    return logging.getLogger("issue_worker")
