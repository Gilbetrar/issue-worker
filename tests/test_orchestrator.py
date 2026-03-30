"""Tests for issue_worker.orchestrator module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from issue_worker.orchestrator import (
    CONSOLIDATION_LINE_THRESHOLD,
    Config,
    RunResult,
    SyncResult,
    _run_consolidation,
    _should_consolidate,
    _sync_main,
    _wait_for_agent_exit,
    run,
)
from issue_worker.signals import Signal


class TestShouldConsolidate:
    """Tests for _should_consolidate iteration logic."""

    def test_iteration_1_triggers(self) -> None:
        assert _should_consolidate(1) is True

    def test_iteration_10_triggers(self) -> None:
        assert _should_consolidate(10) is True

    def test_iteration_20_triggers(self) -> None:
        assert _should_consolidate(20) is True

    def test_iteration_2_skips(self) -> None:
        assert _should_consolidate(2) is False

    def test_iteration_5_skips(self) -> None:
        assert _should_consolidate(5) is False

    def test_iteration_11_skips(self) -> None:
        assert _should_consolidate(11) is False


def _make_launcher(calls: list, *, return_value: bool = True, side_effect=None):
    """Create a fake launcher that records calls."""

    def launcher(cmd: str, title: str) -> bool:
        calls.append((cmd, title))
        if side_effect:
            side_effect()
        return return_value

    return launcher


class TestRunConsolidation:
    """Tests for _run_consolidation."""

    def test_skips_when_no_session_log(self, tmp_path: Path) -> None:
        config = Config(test_mode=True)
        calls: list = []
        result = _run_consolidation(tmp_path, config, _make_launcher(calls))
        assert result is False
        assert calls == []

    def test_skips_when_under_threshold(self, tmp_path: Path) -> None:
        config = Config(test_mode=True)
        (tmp_path / "SESSION_LOG.md").write_text("\n".join(f"line {i}" for i in range(100)))
        calls: list = []
        result = _run_consolidation(tmp_path, config, _make_launcher(calls))
        assert result is False
        assert calls == []

    def test_skips_at_exactly_threshold(self, tmp_path: Path) -> None:
        """Threshold is >200, so exactly 200 lines should skip."""
        config = Config(test_mode=True)
        (tmp_path / "SESSION_LOG.md").write_text(
            "\n".join(f"line {i}" for i in range(CONSOLIDATION_LINE_THRESHOLD))
        )
        calls: list = []
        result = _run_consolidation(tmp_path, config, _make_launcher(calls))
        assert result is False
        assert calls == []

    def test_runs_when_over_threshold(self, tmp_path: Path, monkeypatch) -> None:
        config = Config(test_mode=True)
        (tmp_path / "SESSION_LOG.md").write_text("\n".join(f"line {i}" for i in range(250)))
        signal_file = tmp_path / "CONSOLIDATION_SIGNAL.txt"

        def write_signal():
            signal_file.write_text("DONE\n")

        calls: list = []
        monkeypatch.setattr("issue_worker.orchestrator.time.sleep", lambda _: None)
        result = _run_consolidation(
            tmp_path, config, _make_launcher(calls, side_effect=write_signal)
        )
        assert result is True
        assert len(calls) == 1
        assert "Consolidation" in calls[0][1]

    def test_launch_failure_is_nonfatal(self, tmp_path: Path) -> None:
        config = Config(test_mode=True)
        (tmp_path / "SESSION_LOG.md").write_text("\n".join(f"line {i}" for i in range(250)))
        calls: list = []
        result = _run_consolidation(
            tmp_path, config, _make_launcher(calls, return_value=False)
        )
        assert result is False

    def test_timeout_is_nonfatal(self, tmp_path: Path, monkeypatch) -> None:
        config = Config(test_mode=True)
        (tmp_path / "SESSION_LOG.md").write_text("\n".join(f"line {i}" for i in range(250)))
        calls: list = []

        monkeypatch.setattr("issue_worker.orchestrator.CONSOLIDATION_TIMEOUT", 0)
        result = _run_consolidation(tmp_path, config, _make_launcher(calls))
        assert result is False
        assert len(calls) == 1  # Launched, but timed out

    def test_template_missing_is_nonfatal(self, tmp_path: Path, monkeypatch) -> None:
        config = Config(test_mode=True)
        (tmp_path / "SESSION_LOG.md").write_text("\n".join(f"line {i}" for i in range(250)))

        def raise_not_found(_path: str) -> str:
            raise FileNotFoundError("template not found")

        monkeypatch.setattr(
            "issue_worker.orchestrator.prompts.render_consolidation_prompt",
            raise_not_found,
        )
        calls: list = []
        result = _run_consolidation(tmp_path, config, _make_launcher(calls))
        assert result is False
        assert calls == []

    def test_signal_file_cleaned_up(self, tmp_path: Path, monkeypatch) -> None:
        config = Config(test_mode=True)
        (tmp_path / "SESSION_LOG.md").write_text("\n".join(f"line {i}" for i in range(250)))
        signal_file = tmp_path / "CONSOLIDATION_SIGNAL.txt"

        def write_signal():
            signal_file.write_text("DONE\n")

        calls: list = []
        monkeypatch.setattr("issue_worker.orchestrator.time.sleep", lambda _: None)
        _run_consolidation(
            tmp_path, config, _make_launcher(calls, side_effect=write_signal)
        )
        assert not signal_file.exists()

    def test_only_attempted_once(self, tmp_path: Path, monkeypatch) -> None:
        """Consolidation should launch exactly one agent, not retry on failure."""
        config = Config(test_mode=True)
        (tmp_path / "SESSION_LOG.md").write_text("\n".join(f"line {i}" for i in range(250)))
        calls: list = []

        monkeypatch.setattr("issue_worker.orchestrator.CONSOLIDATION_TIMEOUT", 0)
        _run_consolidation(tmp_path, config, _make_launcher(calls))
        assert len(calls) == 1


class TestWaitForAgentExit:
    """Tests for _wait_for_agent_exit — the block-while-alive gate."""

    def test_returns_immediately_if_pid_is_none(self) -> None:
        _wait_for_agent_exit(None)  # Should not block

    def test_returns_immediately_if_pid_is_none_with_label(self) -> None:
        _wait_for_agent_exit(None, "test")  # Should not block

    def test_returns_immediately_if_process_dead(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "issue_worker.orchestrator._is_process_alive", lambda pid: False
        )
        _wait_for_agent_exit(12345)  # Should not block

    def test_blocks_until_process_exits(self, monkeypatch) -> None:
        # alive_count=3: 1 consumed by guard check, 2 by while loop iterations
        alive_count = [3]
        sleep_calls: list[float] = []

        def fake_alive(pid: int) -> bool:
            if alive_count[0] > 0:
                alive_count[0] -= 1
                return True
            return False

        monkeypatch.setattr("issue_worker.orchestrator._is_process_alive", fake_alive)
        monkeypatch.setattr(
            "issue_worker.orchestrator.time.sleep",
            lambda s: sleep_calls.append(s),
        )
        _wait_for_agent_exit(12345, "test")
        assert len(sleep_calls) == 2
        assert all(s == 5 for s in sleep_calls)


def _ok(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """Create a successful CompletedProcess."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr: str = "error") -> subprocess.CompletedProcess:
    """Create a failed CompletedProcess."""
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


def _mock_subprocess(responses: dict) -> MagicMock:
    """Create a subprocess.run mock that dispatches based on the first git arg.

    responses maps a git subcommand (e.g. "branch", "checkout") to a
    CompletedProcess or callable that returns one.
    """

    def side_effect(cmd, **kwargs):
        # Find the git subcommand (first arg after "git")
        git_idx = cmd.index("git") if "git" in cmd else -1
        subcommand = cmd[git_idx + 1] if git_idx >= 0 and git_idx + 1 < len(cmd) else ""
        handler = responses.get(subcommand, _ok())
        if callable(handler):
            return handler(cmd, **kwargs)
        return handler

    mock = MagicMock(side_effect=side_effect)
    return mock


class TestSyncMain:
    """Tests for _sync_main — repo sync before agent launch."""

    def test_clean_repo_on_main(self, tmp_path: Path, monkeypatch) -> None:
        """Clean repo already on main: fetch+pull succeed."""
        mock = _mock_subprocess({
            "branch": _ok("main\n"),
            "status": _ok(""),  # clean
            "fetch": _ok(),
            "pull": _ok(),
        })
        monkeypatch.setattr("issue_worker.orchestrator.subprocess.run", mock)

        result = _sync_main(tmp_path)
        assert result.success is True

    def test_checkout_from_feature_branch(self, tmp_path: Path, monkeypatch) -> None:
        """On feature branch, checkout to main succeeds, then sync."""
        mock = _mock_subprocess({
            "branch": _ok("feature-x\n"),
            "checkout": _ok(),
            "status": _ok(""),
            "fetch": _ok(),
            "pull": _ok(),
        })
        monkeypatch.setattr("issue_worker.orchestrator.subprocess.run", mock)

        result = _sync_main(tmp_path)
        assert result.success is True

    def test_branch_detection_failure_aborts(self, tmp_path: Path, monkeypatch) -> None:
        """Cannot detect current branch → abort."""
        mock = _mock_subprocess({
            "branch": _fail("fatal: not a git repository"),
        })
        monkeypatch.setattr("issue_worker.orchestrator.subprocess.run", mock)

        result = _sync_main(tmp_path)
        assert result.success is False
        assert "detect current branch" in result.message

    def test_checkout_failure_aborts(self, tmp_path: Path, monkeypatch) -> None:
        """checkout to main fails → abort."""
        mock = _mock_subprocess({
            "branch": _ok("feature-x\n"),
            "checkout": _fail("error: pathspec 'main' did not match"),
        })
        monkeypatch.setattr("issue_worker.orchestrator.subprocess.run", mock)

        result = _sync_main(tmp_path)
        assert result.success is False
        assert "checkout main" in result.message

    def test_dirty_repo_stash_restore_success(self, tmp_path: Path, monkeypatch) -> None:
        """Dirty tree → stash, sync, restore all succeed."""
        stash_calls = []

        def stash_handler(cmd, **kwargs):
            stash_calls.append(cmd)
            return _ok()

        mock = _mock_subprocess({
            "branch": _ok("main\n"),
            "status": _ok("M file.txt\n"),
            "stash": stash_handler,
            "fetch": _ok(),
            "pull": _ok(),
        })
        monkeypatch.setattr("issue_worker.orchestrator.subprocess.run", mock)

        result = _sync_main(tmp_path)
        assert result.success is True
        assert len(stash_calls) == 2  # stash --include-untracked + stash pop

    def test_stash_creation_failure_aborts(self, tmp_path: Path, monkeypatch) -> None:
        """Stash creation fails → abort, don't try to sync."""
        mock = _mock_subprocess({
            "branch": _ok("main\n"),
            "status": _ok("M file.txt\n"),
            "stash": _fail("error: could not stash"),
        })
        monkeypatch.setattr("issue_worker.orchestrator.subprocess.run", mock)

        result = _sync_main(tmp_path)
        assert result.success is False
        assert "stash" in result.message.lower()

    def test_fetch_failure_aborts(self, tmp_path: Path, monkeypatch) -> None:
        """Fetch fails → abort."""
        mock = _mock_subprocess({
            "branch": _ok("main\n"),
            "status": _ok(""),
            "fetch": _fail("fatal: unable to access remote"),
            "pull": _ok(),
        })
        monkeypatch.setattr("issue_worker.orchestrator.subprocess.run", mock)

        result = _sync_main(tmp_path)
        assert result.success is False
        assert "fetch" in result.message.lower()

    def test_pull_failure_aborts(self, tmp_path: Path, monkeypatch) -> None:
        """Pull --rebase fails → abort."""
        mock = _mock_subprocess({
            "branch": _ok("main\n"),
            "status": _ok(""),
            "fetch": _ok(),
            "pull": _fail("CONFLICT (content): Merge conflict"),
        })
        monkeypatch.setattr("issue_worker.orchestrator.subprocess.run", mock)

        result = _sync_main(tmp_path)
        assert result.success is False
        assert "pull" in result.message.lower()

    def test_fetch_timeout_aborts(self, tmp_path: Path, monkeypatch) -> None:
        """Fetch times out → abort."""

        def timeout_fetch(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

        mock = _mock_subprocess({
            "branch": _ok("main\n"),
            "status": _ok(""),
            "fetch": timeout_fetch,
        })
        monkeypatch.setattr("issue_worker.orchestrator.subprocess.run", mock)

        result = _sync_main(tmp_path)
        assert result.success is False
        assert "timed out" in result.message

    def test_stash_pop_conflict_blocks(self, tmp_path: Path, monkeypatch) -> None:
        """Stash pop conflict after sync → abort (don't launch agents)."""
        stash_call_count = [0]

        def stash_handler(cmd, **kwargs):
            stash_call_count[0] += 1
            if stash_call_count[0] == 1:
                return _ok()  # stash --include-untracked succeeds
            return _fail("CONFLICT (content): Merge conflict in file.txt")  # pop fails

        mock = _mock_subprocess({
            "branch": _ok("main\n"),
            "status": _ok("M file.txt\n"),
            "stash": stash_handler,
            "fetch": _ok(),
            "pull": _ok(),
        })
        monkeypatch.setattr("issue_worker.orchestrator.subprocess.run", mock)

        result = _sync_main(tmp_path)
        assert result.success is False
        assert "stash" in result.message.lower()
        assert "conflict" in result.message.lower() or "remain" in result.message.lower()

    def test_fetch_failure_restores_stash(self, tmp_path: Path, monkeypatch) -> None:
        """When fetch fails after stashing, attempt to restore stash."""
        stash_calls = []

        def stash_handler(cmd, **kwargs):
            stash_calls.append(cmd)
            return _ok()

        mock = _mock_subprocess({
            "branch": _ok("main\n"),
            "status": _ok("M file.txt\n"),
            "stash": stash_handler,
            "fetch": _fail("connection refused"),
        })
        monkeypatch.setattr("issue_worker.orchestrator.subprocess.run", mock)

        result = _sync_main(tmp_path)
        assert result.success is False
        # Should have called stash twice: once to stash, once to pop (restore)
        assert len(stash_calls) == 2


# ── Helpers for run() tests ────────────────────────────────────────


def _setup_run(
    monkeypatch,
    tmp_path: Path,
    *,
    sync_ok: bool = True,
    signal: Signal | None = Signal(status="WORKING", summary="did work"),
    launcher_ok: bool = True,
    agent_starts: bool = True,
    time_step: float = 50.0,
) -> tuple[list[tuple[str, str]], Config]:
    """Wire up common mocks for orchestrator.run() and return (launch_calls, config)."""
    launch_calls: list[tuple[str, str]] = []
    started_file = tmp_path / ".issue-worker-started"

    # Time: each call advances by time_step so elapsed = time_step per iteration
    counter = [0.0]

    def fake_time() -> float:
        counter[0] += time_step
        return counter[0]

    monkeypatch.setattr("issue_worker.orchestrator.time.time", fake_time)
    monkeypatch.setattr("issue_worker.orchestrator.time.sleep", lambda _: None)

    # Sync
    monkeypatch.setattr(
        "issue_worker.orchestrator._sync_main",
        lambda _: SyncResult(success=sync_ok, message="test"),
    )

    # Skip consolidation & agent-exit wait
    monkeypatch.setattr("issue_worker.orchestrator._should_consolidate", lambda _: False)
    monkeypatch.setattr("issue_worker.orchestrator._wait_for_agent_exit", lambda *a, **kw: None)

    # Prompt rendering
    monkeypatch.setattr("issue_worker.orchestrator.prompts.render_prompt", lambda **kw: "test")

    # Process liveness
    monkeypatch.setattr("issue_worker.orchestrator._is_process_alive", lambda pid: False)

    # Notifications
    monkeypatch.setattr("issue_worker.orchestrator.notifications.notify", lambda *a, **kw: None)
    monkeypatch.setattr("issue_worker.orchestrator.notifications.notify_stuck_agent", lambda **kw: None)
    monkeypatch.setattr("issue_worker.orchestrator.notifications.prompt_stuck_action", lambda *a, **kw: "kill")

    # Launcher
    def fake_launcher(cmd: str, title: str) -> bool:
        launch_calls.append((cmd, title))
        if agent_starts and launcher_ok:
            started_file.write_text("99999\n")
        return launcher_ok

    monkeypatch.setattr("issue_worker.orchestrator.terminal.open_terminal_tab_test", fake_launcher)
    monkeypatch.setattr("issue_worker.orchestrator.terminal.open_terminal_tab", fake_launcher)

    # Signal
    monkeypatch.setattr(
        "issue_worker.orchestrator.signals.wait_for_signal",
        lambda path, timeout: signal,
    )

    config = Config(test_mode=True)
    return launch_calls, config


def _run_with(
    tmp_path: Path,
    config: Config,
    max_iterations: int = 1,
) -> RunResult:
    """Call run() with common defaults and a given max_iterations."""
    config.max_iterations = max_iterations
    return run(
        project="test-proj",
        repo="Gilbetrar/test-proj",
        project_path=tmp_path,
        config=config,
        use_test_launcher=True,
    )


# ── Run loop state transitions ─────────────────────────────────────


class TestRunLoop:
    """Tests for the orchestrator run() state machine."""

    def test_sync_failure_prevents_launch(self, tmp_path: Path, monkeypatch) -> None:
        """Failed repo sync should abort immediately — launcher never called."""
        launch_calls, config = _setup_run(monkeypatch, tmp_path, sync_ok=False)

        result = _run_with(tmp_path, config)

        assert result.final_status == "error"
        assert "sync failed" in result.message.lower()
        assert launch_calls == []

    def test_complete_signal_stops_loop(self, tmp_path: Path, monkeypatch) -> None:
        """COMPLETE signal should stop the loop with status 'complete'."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="COMPLETE", summary="all done"),
        )

        result = _run_with(tmp_path, config, max_iterations=5)

        assert result.final_status == "complete"
        assert result.iterations_completed == 1
        assert len(launch_calls) == 1

    def test_no_work_signal_stops_loop(self, tmp_path: Path, monkeypatch) -> None:
        """NO_WORK signal should stop the loop with status 'complete'."""
        _calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="NO_WORK", summary="nothing to do"),
        )

        result = _run_with(tmp_path, config)

        assert result.final_status == "complete"
        assert "no actionable" in result.message.lower()

    def test_working_signal_continues(self, tmp_path: Path, monkeypatch) -> None:
        """WORKING signal should increment iteration and continue."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="did stuff"),
        )

        result = _run_with(tmp_path, config, max_iterations=3)

        assert result.final_status == "max_iterations"
        assert result.iterations_completed == 3
        assert len(launch_calls) == 3

    def test_max_iterations_reached(self, tmp_path: Path, monkeypatch) -> None:
        """Hitting max iterations returns 'max_iterations' status."""
        _calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="work"),
        )

        result = _run_with(tmp_path, config, max_iterations=2)

        assert result.final_status == "max_iterations"
        assert result.iterations_completed == 2
        assert "2" in result.message

    def test_crash_guard_aborts(self, tmp_path: Path, monkeypatch) -> None:
        """Rapid exits (elapsed < min_runtime) should trigger crash abort."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="fast exit"),
            time_step=0.5,  # elapsed = 0.5s, well under min_runtime=3
        )
        config.max_crashes = 3
        config.max_iterations = 10

        result = _run_with(tmp_path, config, max_iterations=10)

        assert result.final_status == "aborted"
        assert "rapid exit" in result.message.lower()
        assert len(launch_calls) == 3  # 3 crashes then abort

    def test_launch_failure_aborts(self, tmp_path: Path, monkeypatch) -> None:
        """Launcher returning False should retry then abort."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            launcher_ok=False,
        )
        config.max_crashes = 3
        config.max_iterations = 10

        result = _run_with(tmp_path, config, max_iterations=10)

        assert result.final_status == "aborted"
        assert len(launch_calls) == 3

    def test_agent_start_failure_aborts(self, tmp_path: Path, monkeypatch) -> None:
        """Agent never writing started file should retry then abort."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            agent_starts=False,
        )
        config.max_crashes = 3
        config.max_iterations = 10

        result = _run_with(tmp_path, config, max_iterations=10)

        assert result.final_status == "aborted"
        assert "failed to start" in result.message.lower()
        assert len(launch_calls) == 3

    def test_template_not_found_returns_error(self, tmp_path: Path, monkeypatch) -> None:
        """Missing prompt template should return error, not crash."""
        _calls, config = _setup_run(monkeypatch, tmp_path)
        monkeypatch.setattr(
            "issue_worker.orchestrator.prompts.render_prompt",
            MagicMock(side_effect=FileNotFoundError("template not found")),
        )

        result = _run_with(tmp_path, config)

        assert result.final_status == "error"
        assert "template" in result.message.lower()

    def test_working_plus_handoff_treated_as_paused(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """WORKING signal with HANDOFF.md present should be overridden to PAUSED."""
        handoff = tmp_path / "HANDOFF.md"

        # Launcher creates HANDOFF.md (simulating agent writing it)
        started_file = tmp_path / ".issue-worker-started"
        launch_calls: list[tuple[str, str]] = []

        def launcher_with_handoff(cmd: str, title: str) -> bool:
            launch_calls.append((cmd, title))
            started_file.write_text("99999\n")
            handoff.write_text("needs human action\n")
            return True

        _calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="did work"),
        )
        monkeypatch.setattr(
            "issue_worker.orchestrator.terminal.open_terminal_tab_test",
            launcher_with_handoff,
        )

        # time.sleep should delete HANDOFF.md to unblock the wait loop
        sleep_count = [0]

        def sleep_and_maybe_delete(_: float) -> None:
            sleep_count[0] += 1
            if sleep_count[0] >= 3:
                handoff.unlink(missing_ok=True)

        monkeypatch.setattr("issue_worker.orchestrator.time.sleep", sleep_and_maybe_delete)

        notify_calls: list[tuple] = []
        monkeypatch.setattr(
            "issue_worker.orchestrator.notifications.notify",
            lambda *a, **kw: notify_calls.append(a),
        )

        result = _run_with(tmp_path, config, max_iterations=1)

        # Should have sent PAUSED notification
        assert any("PAUSED" in str(call) for call in notify_calls)
        assert result.final_status == "max_iterations"

    def test_timeout_no_signal_continues(self, tmp_path: Path, monkeypatch) -> None:
        """Timeout with no signal and dead agent should continue."""
        _calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=None,  # Timeout — no signal
        )

        # wait_for_signal returns None → orchestrator writes a fallback signal.
        # After the fallback, it reads the signal file.  Because _is_process_alive
        # returns False and there's no HANDOFF.md, the fallback is WORKING.
        result = _run_with(tmp_path, config, max_iterations=2)

        assert result.final_status == "max_iterations"
        assert result.iterations_completed == 2

    def test_wait_for_agent_exit_called_between_iterations(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The run loop must call _wait_for_agent_exit with the previous PID."""
        wait_calls: list[tuple] = []

        def tracking_wait(pid, label=""):
            wait_calls.append((pid, label))

        _calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="work"),
        )
        monkeypatch.setattr(
            "issue_worker.orchestrator._wait_for_agent_exit",
            tracking_wait,
        )

        _run_with(tmp_path, config, max_iterations=3)

        # First call has prev_pid=None, subsequent calls have the fake PID
        assert wait_calls[0][0] is None
        assert wait_calls[1][0] == 99999
        assert wait_calls[2][0] == 99999
