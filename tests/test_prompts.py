"""Tests for issue_worker.prompts module."""

from __future__ import annotations

from pathlib import Path

import pytest

from issue_worker.prompts import render_consolidation_prompt, render_prompt


class TestRenderPrompt:
    """Tests for render_prompt."""

    def test_substitutes_all_variables(self) -> None:
        result = render_prompt(
            project="my-project",
            repo="Owner/my-project",
            project_path="/tmp/my-project",
            iteration=3,
            max_iterations=25,
        )
        assert "my-project" in result
        assert "Owner/my-project" in result
        assert "/tmp/my-project" in result
        assert "3" in result
        assert "25" in result

    def test_no_unreplaced_placeholders(self) -> None:
        result = render_prompt(
            project="proj",
            repo="Owner/proj",
            project_path="/tmp/proj",
            iteration=1,
            max_iterations=10,
        )
        assert "{PROJECT}" not in result
        assert "{REPO}" not in result
        assert "{PROJECT_PATH}" not in result
        assert "{ITERATION}" not in result
        assert "{MAX_ITERATIONS}" not in result


class TestRenderConsolidationPrompt:
    """Tests for render_consolidation_prompt."""

    def test_substitutes_project_path(self) -> None:
        result = render_consolidation_prompt(project_path="/home/user/myproj")
        assert "/home/user/myproj" in result

    def test_no_unreplaced_placeholders(self) -> None:
        result = render_consolidation_prompt(project_path="/tmp/test")
        assert "{PROJECT_PATH}" not in result


class TestTemplateMissing:
    """Tests for missing template files."""

    def test_missing_template_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "issue_worker.prompts._templates_dir",
            lambda: Path("/nonexistent/templates"),
        )
        with pytest.raises(FileNotFoundError):
            render_prompt("p", "r", "/p", 1, 10)
