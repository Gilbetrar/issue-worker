"""Tests for issue_worker.cli."""

from __future__ import annotations

import argparse
import sys

import pytest

from issue_worker import cli
from issue_worker.orchestrator import RunResult


def test_logs_subcommand_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    """`issue-worker logs` should bypass the main parser and dispatch directly."""
    called: dict[str, int] = {}

    def fake_logs_command(args: argparse.Namespace) -> None:
        called["tail"] = args.tail

    monkeypatch.setattr(cli, "_logs_command", fake_logs_command)
    monkeypatch.setattr(sys, "argv", ["issue-worker", "logs", "-n", "5"])

    cli.main()

    assert called == {"tail": 5}


def test_numeric_positional_is_max_iterations(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lone numeric positional argument should be treated as max iterations."""
    seen: dict[str, object] = {}

    def fake_select_project(input_name, base_dir, github_account):
        seen["input_name"] = input_name
        seen["base_dir"] = base_dir
        seen["github_account"] = github_account
        return None

    monkeypatch.setattr(cli, "select_project", fake_select_project)
    monkeypatch.setattr(sys, "argv", ["issue-worker", "25"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 1
    assert seen["input_name"] is None


def test_complete_result_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful completion should exit with status 0."""
    monkeypatch.setattr(cli, "select_project", lambda **_: "issue-worker")
    monkeypatch.setattr(cli, "get_repo_url", lambda _path: "Gilbetrar/issue-worker")
    monkeypatch.setattr(cli, "run", lambda **_: RunResult(1, "complete", "done"))
    monkeypatch.setattr(sys, "argv", ["issue-worker"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
