"""Tests for issue_worker.prompts module."""

from __future__ import annotations

import issue_worker.prompts as prompts
from pathlib import Path

import pytest

from issue_worker.prompts import (
    detect_verify_commands,
    render_consolidation_prompt,
    render_prompt,
)


def _render_for_python_project(tmp_path: Path) -> str:
    """Render the prompt as if targeting a Python project."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    return render_prompt(
        project="issue-worker",
        repo="Owner/issue-worker",
        project_path=str(tmp_path),
        iteration=1,
        max_iterations=10,
    )


def _render_for_node_project(tmp_path: Path) -> str:
    """Render the prompt as if targeting a Node project."""
    (tmp_path / "package.json").write_text('{"name": "test"}')
    return render_prompt(
        project="my-app",
        repo="Owner/my-app",
        project_path=str(tmp_path),
        iteration=1,
        max_iterations=10,
    )


class TestDetectVerifyCommands:
    """Tests for detect_verify_commands."""

    def test_python_project(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        result = detect_verify_commands(str(tmp_path))
        assert "uv run ruff check" in result
        assert "uv run pytest" in result

    def test_node_project(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}")
        result = detect_verify_commands(str(tmp_path))
        assert "npm run lint" in result
        assert "npm test" in result

    def test_unknown_project(self, tmp_path: Path) -> None:
        result = detect_verify_commands(str(tmp_path))
        assert "LEARNINGS.md" in result

    def test_python_takes_precedence_over_node(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        (tmp_path / "package.json").write_text("{}")
        result = detect_verify_commands(str(tmp_path))
        assert "uv run ruff check" in result


class TestRenderPrompt:
    """Tests for render_prompt."""

    def test_substitutes_all_variables(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        result = render_prompt(
            project="my-project",
            repo="Owner/my-project",
            project_path=str(tmp_path),
            iteration=3,
            max_iterations=25,
        )
        assert "my-project" in result
        assert "Owner/my-project" in result
        assert str(tmp_path) in result
        assert "3" in result
        assert "25" in result

    def test_no_unreplaced_placeholders(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        result = render_prompt(
            project="proj",
            repo="Owner/proj",
            project_path=str(tmp_path),
            iteration=1,
            max_iterations=10,
        )
        assert "{PROJECT}" not in result
        assert "{REPO}" not in result
        assert "{PROJECT_PATH}" not in result
        assert "{ITERATION}" not in result
        assert "{MAX_ITERATIONS}" not in result
        assert "{VERIFY_COMMANDS}" not in result

    def test_prompt_requires_commit_specific_ci_checking(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        result = render_prompt(
            project="proj",
            repo="Owner/proj",
            project_path=str(tmp_path),
            iteration=1,
            max_iterations=10,
        )
        assert "gh run list --repo Owner/proj --commit <sha>" in result
        assert "The commit you signal must be the commit whose CI passed." in result

    def test_prompt_avoids_git_add_dot(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        result = render_prompt(
            project="proj",
            repo="Owner/proj",
            project_path=str(tmp_path),
            iteration=1,
            max_iterations=10,
        )
        assert "git add ." not in result
        assert "git add <changed-files>" in result


class TestPromptBehavioralContract:
    """Tests that the prompt's behavioral contract matches the runtime model.

    These tests validate that the prompt gives agents correct instructions
    for the target repo, not just that placeholders are substituted.
    """

    def test_python_repo_does_not_require_npm(self, tmp_path: Path) -> None:
        """A Python project prompt must never reference npm commands."""
        result = _render_for_python_project(tmp_path)
        assert "npm run lint" not in result
        assert "npm run typecheck" not in result
        assert "npm test" not in result
        assert "npm run build" not in result

    def test_python_repo_uses_correct_commands(self, tmp_path: Path) -> None:
        """A Python project prompt must reference its actual verification tools."""
        result = _render_for_python_project(tmp_path)
        assert "uv run ruff check" in result
        assert "uv run pytest" in result

    def test_node_repo_uses_npm_commands(self, tmp_path: Path) -> None:
        """A Node project prompt must reference npm commands."""
        result = _render_for_node_project(tmp_path)
        assert "npm run lint" in result
        assert "npm test" in result

    def test_direct_to_main_does_not_require_pr_creation(self, tmp_path: Path) -> None:
        """The prompt uses direct-to-main; PR creation must not be the normal path."""
        result = _render_for_python_project(tmp_path)
        assert "direct commits" in result.lower() or "direct commits to `main`" in result
        # The prompt should not frame PR creation as the default completion path
        assert "Create a PR when:" not in result

    def test_prompt_rejects_hardcoded_npm_in_template(self) -> None:
        """Guard: the raw template must not contain hardcoded npm verify commands."""
        template = prompts._read_template("prompt.md")
        assert "npm run typecheck" not in template
        assert "npm run lint" not in template
        assert "npm run build" not in template


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
        monkeypatch.setattr(prompts, "__file__", "/nonexistent/src/issue_worker/prompts.py")
        monkeypatch.setattr(
            "issue_worker.prompts.resources.files",
            lambda _package: Path("/nonexistent/package"),
        )
        with pytest.raises(FileNotFoundError):
            render_prompt("p", "r", "/p", 1, 10)


class TestBundledResourceFallback:
    """Tests for bundled resource loading outside editable installs."""

    def test_render_prompt_uses_packaged_template_when_repo_template_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundled = tmp_path / "issue_worker"
        bundled.mkdir()
        (bundled / "templates").mkdir()
        (bundled / "templates" / "prompt.md").write_text("Hello {PROJECT} #{ITERATION}")

        monkeypatch.setattr(prompts, "__file__", "/nonexistent/src/issue_worker/prompts.py")
        monkeypatch.setattr(
            "issue_worker.prompts.resources.files",
            lambda _package: bundled,
        )

        result = render_prompt("myproj", "Owner/myproj", "/tmp/myproj", 7, 20)
        assert result == "Hello myproj #7"

    def test_render_consolidation_prompt_uses_packaged_template_when_repo_template_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundled = tmp_path / "issue_worker"
        bundled.mkdir()
        (bundled / "templates").mkdir()
        (bundled / "templates" / "consolidate-learnings.md").write_text(
            "Consolidate {PROJECT_PATH}"
        )

        monkeypatch.setattr(prompts, "__file__", "/nonexistent/src/issue_worker/prompts.py")
        monkeypatch.setattr(
            "issue_worker.prompts.resources.files",
            lambda _package: bundled,
        )

        result = render_consolidation_prompt("/tmp/project")
        assert result == "Consolidate /tmp/project"
