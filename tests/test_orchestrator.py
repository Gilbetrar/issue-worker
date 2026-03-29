"""Tests for learnings consolidation in issue_worker.orchestrator."""

from __future__ import annotations

from pathlib import Path

from issue_worker.orchestrator import (
    CONSOLIDATION_LINE_THRESHOLD,
    Config,
    _run_consolidation,
    _should_consolidate,
)


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
