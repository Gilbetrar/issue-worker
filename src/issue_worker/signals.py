"""Atomic signal file operations for orchestrator <-> agent communication."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Signal:
    status: str  # WORKING, PAUSED, COMPLETE
    summary: str

    def __str__(self) -> str:
        return f"{self.status}\n{self.summary}"


def write_signal(path: Path, status: str, summary: str) -> None:
    """Write a signal file atomically (write to .tmp, then rename)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f"{status}\n{summary}\n")
    tmp.rename(path)


def read_signal(path: Path) -> Signal | None:
    """Read and parse a signal file. Returns None if file doesn't exist."""
    if not path.exists():
        return None
    text = path.read_text().strip()
    if not text:
        return None
    lines = text.split("\n", 1)
    status = lines[0].strip()
    summary = lines[1].strip() if len(lines) > 1 else ""
    return Signal(status=status, summary=summary)


def wait_for_signal(path: Path, timeout: int, interval: float = 5.0) -> Signal | None:
    """Poll for a signal file to appear. Returns the signal or None on timeout."""
    elapsed = 0.0
    while elapsed < timeout:
        signal = read_signal(path)
        if signal is not None:
            return signal
        time.sleep(interval)
        elapsed += interval
    return None


def clear_signal(path: Path) -> None:
    """Remove a signal file if it exists."""
    path.unlink(missing_ok=True)
