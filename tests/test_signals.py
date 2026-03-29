"""Tests for issue_worker.signals module."""

from __future__ import annotations

from pathlib import Path

from issue_worker.signals import Signal, clear_signal, read_signal, wait_for_signal, write_signal


class TestWriteSignal:
    """Tests for write_signal."""

    def test_creates_file(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        write_signal(path, "WORKING", "did stuff")
        assert path.exists()

    def test_content_format(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        write_signal(path, "COMPLETE", "all done")
        content = path.read_text()
        assert content == "COMPLETE\nall done\n"

    def test_atomic_no_tmp_left(self, tmp_path: Path) -> None:
        """Temp file should not remain after write."""
        path = tmp_path / "SIGNAL.txt"
        write_signal(path, "WORKING", "test")
        assert not path.with_suffix(".tmp").exists()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        write_signal(path, "WORKING", "first")
        write_signal(path, "COMPLETE", "second")
        content = path.read_text()
        assert content == "COMPLETE\nsecond\n"


class TestReadSignal:
    """Tests for read_signal."""

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        assert read_signal(path) is None

    def test_returns_none_for_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        path.write_text("")
        assert read_signal(path) is None

    def test_parses_status_and_summary(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        path.write_text("WORKING\nDid some work\n")
        signal = read_signal(path)
        assert signal is not None
        assert signal.status == "WORKING"
        assert signal.summary == "Did some work"

    def test_handles_status_only(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        path.write_text("PAUSED\n")
        signal = read_signal(path)
        assert signal is not None
        assert signal.status == "PAUSED"
        assert signal.summary == ""

    def test_handles_multiline_summary(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        path.write_text("WORKING\nline1\nline2\nline3\n")
        signal = read_signal(path)
        assert signal is not None
        assert signal.status == "WORKING"
        assert "line1" in signal.summary
        assert "line3" in signal.summary

    def test_roundtrip(self, tmp_path: Path) -> None:
        """write_signal -> read_signal produces correct data."""
        path = tmp_path / "SIGNAL.txt"
        write_signal(path, "COMPLETE", "finished everything")
        signal = read_signal(path)
        assert signal is not None
        assert signal.status == "COMPLETE"
        assert signal.summary == "finished everything"


class TestWaitForSignal:
    """Tests for wait_for_signal."""

    def test_returns_immediately_if_exists(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        write_signal(path, "WORKING", "ready")
        signal = wait_for_signal(path, timeout=1, interval=0.1)
        assert signal is not None
        assert signal.status == "WORKING"

    def test_returns_none_on_timeout(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        signal = wait_for_signal(path, timeout=0, interval=0.1)
        assert signal is None


class TestClearSignal:
    """Tests for clear_signal."""

    def test_removes_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        path.write_text("WORKING\ntest\n")
        clear_signal(path)
        assert not path.exists()

    def test_no_error_if_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "SIGNAL.txt"
        clear_signal(path)  # Should not raise


class TestSignalDataclass:
    """Tests for Signal dataclass."""

    def test_str_representation(self) -> None:
        signal = Signal(status="WORKING", summary="hello")
        assert str(signal) == "WORKING\nhello"
