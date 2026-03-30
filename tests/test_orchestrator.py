"""Tests for issue_worker.orchestrator module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from issue_worker.orchestrator import (
    AGENT_EXIT_GRACE_PERIOD,
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

    def test_detaches_after_grace_period(self, monkeypatch) -> None:
        """Process stays alive forever — function returns after grace period."""
        sleep_calls: list[float] = []

        monkeypatch.setattr(
            "issue_worker.orchestrator._is_process_alive", lambda pid: True
        )
        monkeypatch.setattr(
            "issue_worker.orchestrator.time.sleep",
            lambda s: sleep_calls.append(s),
        )
        _wait_for_agent_exit(12345, "lingering")
        # Should have polled every 5s for AGENT_EXIT_GRACE_PERIOD seconds
        expected_polls = int(AGENT_EXIT_GRACE_PERIOD / 5)
        assert len(sleep_calls) == expected_polls
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

    def test_crashed_signal_aborts(self, tmp_path: Path, monkeypatch) -> None:
        """CRASHED signal (shell wrapper fallback) should trigger crash abort."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="CRASHED", summary="agent exited without signal"),
        )
        config.max_crashes = 3
        config.max_iterations = 10

        result = _run_with(tmp_path, config, max_iterations=10)

        assert result.final_status == "aborted"
        assert "failures" in result.message.lower()
        assert len(launch_calls) == 3  # 3 crashes then abort

    def test_quick_exit_with_valid_signal_not_crash(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A quick exit with a valid WORKING signal should NOT count as crash."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="fast but valid"),
            time_step=0.5,  # very fast exit
        )
        config.max_iterations = 3

        result = _run_with(tmp_path, config, max_iterations=3)

        # Should iterate normally, not abort
        assert result.final_status == "max_iterations"
        assert result.iterations_completed == 3

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

    def test_timeout_no_signal_is_failure(self, tmp_path: Path, monkeypatch) -> None:
        """Timeout with no signal and dead agent should count as failure."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=None,  # Timeout — no signal
        )
        config.max_crashes = 3
        config.max_iterations = 10

        result = _run_with(tmp_path, config, max_iterations=10)

        assert result.final_status == "aborted"
        assert len(launch_calls) == 3  # retries then aborts

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

    def test_unknown_signal_treated_as_failure(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Unknown signal values should not advance iteration."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="BANANA", summary="not a real signal"),
        )
        config.max_crashes = 3
        config.max_iterations = 10

        result = _run_with(tmp_path, config, max_iterations=10)

        assert result.final_status == "aborted"
        assert "BANANA" in result.message
        assert len(launch_calls) == 3

    def test_no_work_quick_exit_not_crash(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """NO_WORK with quick exit should not count as crash."""
        _calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="NO_WORK", summary="nothing to do"),
            time_step=0.5,  # very quick
        )

        result = _run_with(tmp_path, config, max_iterations=5)

        assert result.final_status == "complete"
        assert "no actionable" in result.message.lower()


# ── Pre-existing handoff (restart-safety, issue #14) ─────────────


class TestPreExistingHandoff:
    """Tests for restart-safe handoff behavior."""

    def test_preexisting_handoff_blocks_until_resolved(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """HANDOFF.md at startup blocks agent launch until the file is deleted."""
        handoff = tmp_path / "HANDOFF.md"
        handoff.write_text("# Action needed\nDo the thing\n")

        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="did work"),
        )

        sleep_count = [0]

        def sleep_and_delete(_: float) -> None:
            sleep_count[0] += 1
            if sleep_count[0] >= 3:
                handoff.unlink(missing_ok=True)

        monkeypatch.setattr("issue_worker.orchestrator.time.sleep", sleep_and_delete)

        result = _run_with(tmp_path, config, max_iterations=1)

        assert sleep_count[0] >= 3
        assert len(launch_calls) == 1
        assert result.final_status == "max_iterations"

    def test_preexisting_handoff_never_deleted_by_orchestrator(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The orchestrator must not delete HANDOFF.md — only the operator can."""
        handoff = tmp_path / "HANDOFF.md"
        handoff.write_text("# Action needed\n")

        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="did work"),
        )

        file_existed_every_check = [True]
        sleep_count = [0]

        def sleep_and_verify(_: float) -> None:
            sleep_count[0] += 1
            # Only verify during the pre-loop handoff wait (first 5 calls)
            if sleep_count[0] <= 5 and not handoff.exists():
                file_existed_every_check[0] = False
            if sleep_count[0] == 5:
                handoff.unlink()

        monkeypatch.setattr("issue_worker.orchestrator.time.sleep", sleep_and_verify)

        _run_with(tmp_path, config, max_iterations=1)

        assert file_existed_every_check[0] is True
        assert sleep_count[0] >= 5

    def test_no_preexisting_handoff_proceeds_normally(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Without HANDOFF.md at startup, run() proceeds without blocking."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="COMPLETE", summary="done"),
        )

        result = _run_with(tmp_path, config, max_iterations=5)

        assert result.final_status == "complete"
        assert len(launch_calls) == 1

    def test_preexisting_handoff_sends_notification(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Operator should be notified when a pre-existing handoff blocks startup."""
        handoff = tmp_path / "HANDOFF.md"
        handoff.write_text("# Blocked\n")

        _calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="work"),
        )

        notify_calls: list[tuple] = []
        monkeypatch.setattr(
            "issue_worker.orchestrator.notifications.notify",
            lambda *a, **kw: notify_calls.append(a),
        )

        sleep_count = [0]

        def sleep_and_delete(_: float) -> None:
            sleep_count[0] += 1
            if sleep_count[0] >= 2:
                handoff.unlink(missing_ok=True)

        monkeypatch.setattr("issue_worker.orchestrator.time.sleep", sleep_and_delete)

        _run_with(tmp_path, config, max_iterations=1)

        assert any("BLOCKED" in str(call) for call in notify_calls)

    def test_resolved_handoff_allows_normal_launch(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """After HANDOFF.md is resolved, the full run loop executes normally."""
        handoff = tmp_path / "HANDOFF.md"
        handoff.write_text("# Will be resolved\n")

        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="work"),
        )

        sleep_count = [0]

        def sleep_and_delete(_: float) -> None:
            sleep_count[0] += 1
            if sleep_count[0] == 1:
                handoff.unlink()

        monkeypatch.setattr("issue_worker.orchestrator.time.sleep", sleep_and_delete)

        result = _run_with(tmp_path, config, max_iterations=3)

        assert result.final_status == "max_iterations"
        assert result.iterations_completed == 3
        assert len(launch_calls) == 3

# ── Stuck-agent retry behavior (issue #15) ─────────────────────


class TestStuckAgentRetry:
    """Tests for stuck-agent kill/leave iteration accounting."""

    def test_kill_retries_same_iteration(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Killing a stuck agent should retry the same iteration, not skip it."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="did work"),
        )

        # First iteration: agent appears stuck (alive after signal timeout),
        # user chooses "kill". Second iteration: normal WORKING signal.
        iteration_signals = iter([None, Signal(status="WORKING", summary="ok")])

        monkeypatch.setattr(
            "issue_worker.orchestrator.signals.wait_for_signal",
            lambda path, timeout: next(iteration_signals),
        )

        # Agent is alive on first call (stuck), dead after that
        alive_calls = [0]

        def fake_alive(pid: int) -> bool:
            alive_calls[0] += 1
            # First two alive checks: stuck agent (one in timeout block, one in PAUSED block)
            return alive_calls[0] <= 2

        monkeypatch.setattr("issue_worker.orchestrator._is_process_alive", fake_alive)

        kill_calls: list[int] = []
        monkeypatch.setattr(
            "issue_worker.orchestrator._kill_agent",
            lambda pid: kill_calls.append(pid),
        )
        monkeypatch.setattr(
            "issue_worker.orchestrator.notifications.prompt_stuck_action",
            lambda *a, **kw: "kill",
        )

        result = _run_with(tmp_path, config, max_iterations=1)

        # Kill was called
        assert len(kill_calls) == 1
        # The retry succeeded (WORKING on second attempt) → iteration completed
        assert result.final_status == "max_iterations"
        assert result.iterations_completed == 1
        # Launched twice: once for the stuck attempt, once for the retry
        assert len(launch_calls) == 2

    def test_kill_does_not_consume_iteration_budget(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Interrupted attempts should not count toward max_iterations."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="work"),
        )

        # Every odd launch is stuck (killed), every even launch works.
        # With max_iterations=2, we need 2 successful completions.
        call_count = [0]

        def alternating_signal(path, timeout):
            call_count[0] += 1
            if call_count[0] % 2 == 1:
                return None  # stuck → triggers kill
            return Signal(status="WORKING", summary="completed")

        monkeypatch.setattr(
            "issue_worker.orchestrator.signals.wait_for_signal",
            alternating_signal,
        )

        alive_tracker = [0]

        def alive_for_odd_calls(pid: int) -> bool:
            alive_tracker[0] += 1
            # Alive during odd signal waits (stuck), dead during even
            return call_count[0] % 2 == 1

        monkeypatch.setattr("issue_worker.orchestrator._is_process_alive", alive_for_odd_calls)
        monkeypatch.setattr(
            "issue_worker.orchestrator._kill_agent", lambda pid: None,
        )
        monkeypatch.setattr(
            "issue_worker.orchestrator.notifications.prompt_stuck_action",
            lambda *a, **kw: "kill",
        )

        result = _run_with(tmp_path, config, max_iterations=2)

        # 2 completed iterations (WORKING), 2 interrupted (killed) = 4 launches
        assert result.final_status == "max_iterations"
        assert result.iterations_completed == 2
        assert len(launch_calls) == 4

    def test_leave_does_not_advance_iteration(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Leaving a stuck agent running should retry the same iteration after it exits."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="work"),
        )

        # First call: stuck (None signal). Second: normal WORKING.
        signal_iter = iter([None, Signal(status="WORKING", summary="done")])

        monkeypatch.setattr(
            "issue_worker.orchestrator.signals.wait_for_signal",
            lambda path, timeout: next(signal_iter),
        )

        alive_calls = [0]

        def fake_alive(pid: int) -> bool:
            alive_calls[0] += 1
            # Alive for first 2 checks (stuck detection), then dead
            return alive_calls[0] <= 2

        monkeypatch.setattr("issue_worker.orchestrator._is_process_alive", fake_alive)
        monkeypatch.setattr(
            "issue_worker.orchestrator.notifications.prompt_stuck_action",
            lambda *a, **kw: "leave",
        )

        # _wait_for_agent_exit will be called for "leave" path — make it return immediately
        wait_calls: list[tuple] = []

        def tracking_wait(pid, label=""):
            wait_calls.append((pid, label))

        monkeypatch.setattr(
            "issue_worker.orchestrator._wait_for_agent_exit",
            tracking_wait,
        )

        result = _run_with(tmp_path, config, max_iterations=1)

        # Leave path also retries same iteration
        assert result.final_status == "max_iterations"
        assert result.iterations_completed == 1
        assert len(launch_calls) == 2  # stuck + retry
        # The "leave" path called _wait_for_agent_exit with "stuck agent" label
        assert any("stuck agent" in str(call) for call in wait_calls)

    def test_kill_prevents_duplicate_agents(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """After kill, _wait_for_agent_exit is called before the retry launch."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="work"),
        )

        # First: stuck, second: COMPLETE
        signal_iter = iter([None, Signal(status="COMPLETE", summary="done")])
        monkeypatch.setattr(
            "issue_worker.orchestrator.signals.wait_for_signal",
            lambda path, timeout: next(signal_iter),
        )

        alive_calls = [0]

        def fake_alive(pid: int) -> bool:
            alive_calls[0] += 1
            return alive_calls[0] <= 2

        monkeypatch.setattr("issue_worker.orchestrator._is_process_alive", fake_alive)
        monkeypatch.setattr("issue_worker.orchestrator._kill_agent", lambda pid: None)
        monkeypatch.setattr(
            "issue_worker.orchestrator.notifications.prompt_stuck_action",
            lambda *a, **kw: "kill",
        )

        wait_calls: list[tuple] = []

        def tracking_wait(pid, label=""):
            wait_calls.append((pid, label))

        monkeypatch.setattr(
            "issue_worker.orchestrator._wait_for_agent_exit",
            tracking_wait,
        )

        result = _run_with(tmp_path, config, max_iterations=5)

        assert result.final_status == "complete"
        # _wait_for_agent_exit called before retry launch (prev_pid=None after kill)
        # and before initial launch
        assert len(launch_calls) == 2
        # prev_pid is set to None after kill, so the retry's wait gets None
        assert wait_calls[1] == (None, "previous iteration")


    def test_same_run_cleanup_still_clears_transient_files(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Per-iteration clean-slate still removes SIGNAL.txt and started file."""
        launch_calls, config = _setup_run(
            monkeypatch, tmp_path,
            signal=Signal(status="WORKING", summary="work"),
        )

        # Pre-create transient files
        (tmp_path / "SIGNAL.txt").write_text("STALE\n")
        (tmp_path / ".issue-worker-started").write_text("12345\n")

        result = _run_with(tmp_path, config, max_iterations=1)

        assert result.final_status == "max_iterations"
        assert len(launch_calls) == 1
