"""Tests for issue_worker.project module."""

from __future__ import annotations

import subprocess
from pathlib import Path

from issue_worker.project import get_local_projects, get_repo_url


class TestGetLocalProjects:
    """Tests for get_local_projects."""

    def test_finds_git_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "proj-a" / ".git").mkdir(parents=True)
        (tmp_path / "proj-b" / ".git").mkdir(parents=True)
        result = get_local_projects(tmp_path)
        assert result == ["proj-a", "proj-b"]

    def test_ignores_non_git_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "proj-a" / ".git").mkdir(parents=True)
        (tmp_path / "not-a-project").mkdir()
        result = get_local_projects(tmp_path)
        assert result == ["proj-a"]

    def test_returns_empty_for_nonexistent_dir(self) -> None:
        result = get_local_projects(Path("/nonexistent/dir"))
        assert result == []

    def test_returns_empty_for_empty_dir(self, tmp_path: Path) -> None:
        result = get_local_projects(tmp_path)
        assert result == []

    def test_sorted_alphabetically(self, tmp_path: Path) -> None:
        (tmp_path / "zebra" / ".git").mkdir(parents=True)
        (tmp_path / "alpha" / ".git").mkdir(parents=True)
        (tmp_path / "middle" / ".git").mkdir(parents=True)
        result = get_local_projects(tmp_path)
        assert result == ["alpha", "middle", "zebra"]


class TestGetRepoUrl:
    """Tests for get_repo_url with real git repos."""

    def test_ssh_url(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:Owner/Repo.git"],
            cwd=repo,
            capture_output=True,
        )
        assert get_repo_url(repo) == "Owner/Repo"

    def test_https_url(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/Owner/Repo.git"],
            cwd=repo,
            capture_output=True,
        )
        assert get_repo_url(repo) == "Owner/Repo"

    def test_ssh_host_alias(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github-work:Org/Repo.git"],
            cwd=repo,
            capture_output=True,
        )
        assert get_repo_url(repo) == "Org/Repo"

    def test_no_remote_returns_none(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        assert get_repo_url(repo) is None

    def test_non_git_dir_returns_none(self, tmp_path: Path) -> None:
        assert get_repo_url(tmp_path) is None
