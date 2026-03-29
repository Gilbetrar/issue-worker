"""Tests for issue_worker.notifications module."""

from __future__ import annotations

from issue_worker.notifications import _escape


class TestEscape:
    """Tests for _escape AppleScript string escaping."""

    def test_plain_string(self) -> None:
        assert _escape("hello world") == "hello world"

    def test_escapes_quotes(self) -> None:
        assert _escape('say "hello"') == 'say \\"hello\\"'

    def test_escapes_backslashes(self) -> None:
        assert _escape("path\\to\\file") == "path\\\\to\\\\file"

    def test_escapes_both(self) -> None:
        result = _escape('a "b" c\\d')
        assert result == 'a \\"b\\" c\\\\d'

    def test_empty_string(self) -> None:
        assert _escape("") == ""
