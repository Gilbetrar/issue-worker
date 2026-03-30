"""Tests for issue_worker.terminal module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from issue_worker.terminal import (
    _build_applescript,
    _invoke_osascript,
    _write_temp_script,
    open_terminal_tab,
)


# ── AppleScript generation ──────────────────────────────────────────


class TestBuildApplescript:
    """Verify the generated AppleScript uses the tab-oriented code path."""

    def test_contains_keystroke_tab_command(self) -> None:
        script = _build_applescript()
        assert 'keystroke "t" using command down' in script

    def test_uses_system_events_for_tab(self) -> None:
        script = _build_applescript()
        assert "System Events" in script

    def test_falls_back_to_new_window_when_none_exist(self) -> None:
        script = _build_applescript()
        assert "count of windows" in script
        # The else branch uses bare 'do script' (no 'in front window')
        # which creates a new window.
        assert "do script shellCmd\n" in script

    def test_runs_in_front_window_for_tab_path(self) -> None:
        script = _build_applescript()
        assert "do script shellCmd in front window" in script

    def test_sets_custom_title(self) -> None:
        script = _build_applescript()
        assert "set custom title" in script

    def test_cleans_up_script_file(self) -> None:
        script = _build_applescript()
        assert "rm -f" in script

    def test_accepts_two_argv_items(self) -> None:
        script = _build_applescript()
        assert "item 1 of argv" in script
        assert "item 2 of argv" in script


# ── Temp-script writer ──────────────────────────────────────────────


class TestWriteTempScript:
    """Verify temp-script creation."""

    def test_creates_executable_file(self, tmp_path: Path, monkeypatch) -> None:
        import issue_worker.terminal as mod

        monkeypatch.setattr(mod, "_temp_scripts", [])
        path = _write_temp_script("echo hello")
        assert path is not None
        assert path.exists()
        assert path.stat().st_mode & 0o755
        assert path.read_text() == "echo hello\n"
        # cleanup
        path.unlink(missing_ok=True)

    def test_returns_none_on_os_error(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "issue_worker.terminal.tempfile.NamedTemporaryFile",
            MagicMock(side_effect=OSError("disk full")),
        )
        assert _write_temp_script("echo fail") is None


# ── osascript invocation & retry ────────────────────────────────────


class TestInvokeOsascript:
    """Verify subprocess invocation passes the right arguments and retries."""

    def test_passes_script_path_and_title(self) -> None:
        mock_run = MagicMock(
            return_value=subprocess.CompletedProcess(args=[], returncode=0)
        )
        script = "-- applescript"
        with patch("issue_worker.terminal.subprocess.run", mock_run):
            result = _invoke_osascript(script, Path("/tmp/test.sh"), "My Title")

        assert result is True
        call_args = mock_run.call_args[0][0]
        assert call_args == ["osascript", "-e", script, "/tmp/test.sh", "My Title"]

    def test_retries_on_nonzero_exit(self, monkeypatch) -> None:
        call_count = [0]
        monkeypatch.setattr("issue_worker.terminal.time.sleep", lambda _: None)

        def failing_run(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                return subprocess.CompletedProcess(args=cmd, returncode=1)
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        with patch("issue_worker.terminal.subprocess.run", side_effect=failing_run):
            result = _invoke_osascript("--", Path("/tmp/x.sh"), "T")

        assert result is True
        assert call_count[0] == 3

    def test_returns_false_after_max_retries(self, monkeypatch) -> None:
        monkeypatch.setattr("issue_worker.terminal.time.sleep", lambda _: None)
        mock_run = MagicMock(
            return_value=subprocess.CompletedProcess(args=[], returncode=1)
        )
        with patch("issue_worker.terminal.subprocess.run", mock_run):
            result = _invoke_osascript("--", Path("/tmp/x.sh"), "T")

        assert result is False
        assert mock_run.call_count == 3

    def test_retries_on_timeout(self, monkeypatch) -> None:
        call_count = [0]
        monkeypatch.setattr("issue_worker.terminal.time.sleep", lambda _: None)

        def timeout_then_ok(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=15)
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        with patch("issue_worker.terminal.subprocess.run", side_effect=timeout_then_ok):
            result = _invoke_osascript("--", Path("/tmp/x.sh"), "T")

        assert result is True
        assert call_count[0] == 2

    def test_returns_false_on_os_error(self) -> None:
        with patch(
            "issue_worker.terminal.subprocess.run",
            side_effect=OSError("no osascript"),
        ):
            result = _invoke_osascript("--", Path("/tmp/x.sh"), "T")
        assert result is False


# ── Integration: open_terminal_tab ──────────────────────────────────


class TestOpenTerminalTab:
    """End-to-end tests for the public launcher function."""

    def test_returns_false_when_script_write_fails(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "issue_worker.terminal._write_temp_script", lambda _: None
        )
        assert open_terminal_tab("echo hi") is False

    def test_calls_osascript_with_tab_oriented_script(self, monkeypatch) -> None:
        captured: dict = {}

        def fake_invoke(applescript, script_path, title):
            captured["applescript"] = applescript
            captured["script_path"] = script_path
            captured["title"] = title
            return True

        monkeypatch.setattr("issue_worker.terminal._invoke_osascript", fake_invoke)
        monkeypatch.setattr(
            "issue_worker.terminal._write_temp_script",
            lambda cmd: Path("/tmp/fake.sh"),
        )

        result = open_terminal_tab("echo hi", "Test Tab")
        assert result is True
        assert 'keystroke "t" using command down' in captured["applescript"]
        assert captured["title"] == "Test Tab"

    def test_propagates_invoke_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "issue_worker.terminal._write_temp_script",
            lambda cmd: Path("/tmp/fake.sh"),
        )
        monkeypatch.setattr(
            "issue_worker.terminal._invoke_osascript", lambda *a: False
        )
        assert open_terminal_tab("echo hi") is False
