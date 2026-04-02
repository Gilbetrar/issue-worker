"""Tests for issue_worker.cli."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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


def test_complete_result_exits_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Successful completion should exit with status 0."""
    # Create fake project directory with .git so the is_dir() check passes
    (tmp_path / "AI" / "Projects" / "issue-worker").mkdir(parents=True)
    (tmp_path / "AI" / "Projects" / "issue-worker" / ".git").mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    monkeypatch.setattr(cli, "select_project", lambda **_: "issue-worker")
    monkeypatch.setattr(cli, "get_repo_url", lambda _path: "Gilbetrar/issue-worker")
    monkeypatch.setattr(cli, "run", lambda **_: RunResult(1, "complete", "done"))
    monkeypatch.setattr(sys, "argv", ["issue-worker"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0


def _setup_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Wire up Path.home() and create a fake project directory."""
    (tmp_path / "AI" / "Projects" / "myproj").mkdir(parents=True)
    (tmp_path / "AI" / "Projects" / "myproj" / ".git").mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))


def test_max_iterations_result_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """max_iterations final status should exit with code 1."""
    _setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "select_project", lambda **_: "myproj")
    monkeypatch.setattr(cli, "get_repo_url", lambda _path: "Gilbetrar/myproj")
    monkeypatch.setattr(cli, "run", lambda **_: RunResult(10, "max_iterations", "done"))
    monkeypatch.setattr(sys, "argv", ["issue-worker", "myproj"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 1


def test_error_result_exits_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Error or aborted final status should exit with code 2."""
    _setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "select_project", lambda **_: "myproj")
    monkeypatch.setattr(cli, "get_repo_url", lambda _path: "Gilbetrar/myproj")
    monkeypatch.setattr(cli, "run", lambda **_: RunResult(0, "error", "sync failed"))
    monkeypatch.setattr(sys, "argv", ["issue-worker", "myproj"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2


def test_aborted_result_exits_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Aborted final status should also exit with code 2."""
    _setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "select_project", lambda **_: "myproj")
    monkeypatch.setattr(cli, "get_repo_url", lambda _path: "Gilbetrar/myproj")
    monkeypatch.setattr(cli, "run", lambda **_: RunResult(2, "aborted", "crashed"))
    monkeypatch.setattr(sys, "argv", ["issue-worker", "myproj"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2


def test_no_project_selected_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """select_project returning None should exit with code 1."""
    _setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "select_project", lambda **_: None)
    monkeypatch.setattr(sys, "argv", ["issue-worker", "nonexistent"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 1


def test_not_a_git_repo_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Project directory without .git should exit with code 1."""
    (tmp_path / "AI" / "Projects" / "notgit").mkdir(parents=True)
    # No .git directory
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(cli, "select_project", lambda **_: "notgit")
    monkeypatch.setattr(sys, "argv", ["issue-worker", "notgit"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 1


def test_no_repo_url_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """get_repo_url returning None should exit with code 1."""
    _setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "select_project", lambda **_: "myproj")
    monkeypatch.setattr(cli, "get_repo_url", lambda _path: None)
    monkeypatch.setattr(sys, "argv", ["issue-worker", "myproj"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 1


def test_max_iterations_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--max-iterations flag should override the default."""
    _setup_cli(monkeypatch, tmp_path)

    captured: dict = {}

    def capture_run(**kwargs):
        captured.update(kwargs)
        return RunResult(1, "complete", "done")

    monkeypatch.setattr(cli, "select_project", lambda **_: "myproj")
    monkeypatch.setattr(cli, "get_repo_url", lambda _path: "Gilbetrar/myproj")
    monkeypatch.setattr(cli, "run", capture_run)
    monkeypatch.setattr(sys, "argv", ["issue-worker", "myproj", "--max-iterations", "42"])

    with pytest.raises(SystemExit):
        cli.main()

    assert captured["config"].max_iterations == 42


def test_test_flag_sets_test_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--test flag should set config.test_mode and use_test_launcher."""
    _setup_cli(monkeypatch, tmp_path)

    captured: dict = {}

    def capture_run(**kwargs):
        captured.update(kwargs)
        return RunResult(1, "complete", "done")

    monkeypatch.setattr(cli, "select_project", lambda **_: "myproj")
    monkeypatch.setattr(cli, "get_repo_url", lambda _path: "Gilbetrar/myproj")
    monkeypatch.setattr(cli, "run", capture_run)
    monkeypatch.setattr(sys, "argv", ["issue-worker", "myproj", "--test"])

    with pytest.raises(SystemExit):
        cli.main()

    assert captured["config"].test_mode is True
    assert captured["use_test_launcher"] is True


def test_profile_flag_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--profile work should create a Config with work account and paths."""
    (tmp_path / "work-ai" / "myproj").mkdir(parents=True)
    (tmp_path / "work-ai" / "myproj" / ".git").mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    captured: dict = {}

    def capture_run(**kwargs):
        captured.update(kwargs)
        return RunResult(1, "complete", "done")

    monkeypatch.setattr(cli, "select_project", lambda **_: "myproj")
    monkeypatch.setattr(cli, "get_repo_url", lambda _path: "benbateman-work/myproj")
    monkeypatch.setattr(cli, "run", capture_run)
    monkeypatch.setattr(sys, "argv", ["issue-worker", "myproj", "--profile", "work"])

    with pytest.raises(SystemExit):
        cli.main()

    assert captured["config"].github_account == "benbateman-work"
    assert captured["config"].projects_dir == tmp_path / "work-ai"


def test_profile_flag_default_is_personal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Omitting --profile should default to personal."""
    _setup_cli(monkeypatch, tmp_path)

    captured: dict = {}

    def capture_run(**kwargs):
        captured.update(kwargs)
        return RunResult(1, "complete", "done")

    monkeypatch.setattr(cli, "select_project", lambda **_: "myproj")
    monkeypatch.setattr(cli, "get_repo_url", lambda _path: "Gilbetrar/myproj")
    monkeypatch.setattr(cli, "run", capture_run)
    monkeypatch.setattr(sys, "argv", ["issue-worker", "myproj"])

    with pytest.raises(SystemExit):
        cli.main()

    assert captured["config"].github_account == "Gilbetrar"
