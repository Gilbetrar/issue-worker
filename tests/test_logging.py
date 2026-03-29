"""Tests for issue_worker.logging module."""

from __future__ import annotations

import logging
from pathlib import Path

from issue_worker.logging import (
    MAX_LOG_FILES,
    get_logger,
    list_log_files,
    prune_logs,
    setup_logging,
)


def test_setup_logging_creates_file(tmp_path: Path, monkeypatch: object) -> None:
    """Log file is created in the correct directory."""
    monkeypatch.setattr("issue_worker.logging.LOG_DIR", tmp_path)

    log_file = setup_logging()

    assert log_file.exists()
    assert log_file.parent == tmp_path
    assert log_file.name.startswith("issue-worker-")
    assert log_file.suffix == ".log"

    # Clean up handlers to avoid interference with other tests
    logging.getLogger("issue_worker").handlers.clear()


def test_setup_logging_writes_content(tmp_path: Path, monkeypatch: object) -> None:
    """Log file contains messages written via the logger."""
    monkeypatch.setattr("issue_worker.logging.LOG_DIR", tmp_path)

    log_file = setup_logging()
    log = get_logger()
    log.info("test info message")
    log.debug("test debug message")

    # Flush handlers
    for handler in log.handlers:
        handler.flush()

    content = log_file.read_text()
    assert "test info message" in content
    assert "test debug message" in content

    log.handlers.clear()


def test_prune_logs_keeps_max(tmp_path: Path, monkeypatch: object) -> None:
    """Log rotation keeps only MAX_LOG_FILES files."""
    monkeypatch.setattr("issue_worker.logging.LOG_DIR", tmp_path)

    # Create more than MAX_LOG_FILES log files
    for i in range(MAX_LOG_FILES + 5):
        (tmp_path / f"issue-worker-20260101-{i:06d}.log").write_text(f"log {i}")

    removed = prune_logs()

    remaining = list(tmp_path.glob("issue-worker-*.log"))
    assert len(remaining) == MAX_LOG_FILES
    assert removed == 5


def test_prune_logs_no_op_when_under_limit(tmp_path: Path, monkeypatch: object) -> None:
    """No files are removed when under the limit."""
    monkeypatch.setattr("issue_worker.logging.LOG_DIR", tmp_path)

    for i in range(3):
        (tmp_path / f"issue-worker-20260101-{i:06d}.log").write_text(f"log {i}")

    removed = prune_logs()

    assert removed == 0
    assert len(list(tmp_path.glob("issue-worker-*.log"))) == 3


def test_prune_logs_nonexistent_dir(monkeypatch: object) -> None:
    """No error when log directory doesn't exist."""
    monkeypatch.setattr("issue_worker.logging.LOG_DIR", Path("/nonexistent/path"))
    assert prune_logs() == 0


def test_list_log_files_newest_first(tmp_path: Path, monkeypatch: object) -> None:
    """list_log_files returns files sorted newest first."""
    monkeypatch.setattr("issue_worker.logging.LOG_DIR", tmp_path)

    import time

    f1 = tmp_path / "issue-worker-20260101-000001.log"
    f1.write_text("old")
    time.sleep(0.05)
    f2 = tmp_path / "issue-worker-20260101-000002.log"
    f2.write_text("new")

    files = list_log_files()
    assert len(files) == 2
    assert files[0].name == f2.name  # newest first


def test_list_log_files_empty_dir(tmp_path: Path, monkeypatch: object) -> None:
    """Returns empty list when no log files exist."""
    monkeypatch.setattr("issue_worker.logging.LOG_DIR", tmp_path)
    assert list_log_files() == []
