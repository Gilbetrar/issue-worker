"""Project selection, GitHub sync, and cloning."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path


def get_local_projects(base_dir: Path) -> list[str]:
    """Get list of local git projects (directories with .git)."""
    projects = []
    if not base_dir.is_dir():
        return projects
    for d in sorted(base_dir.iterdir()):
        if d.is_dir() and (d / ".git").is_dir():
            projects.append(d.name)
    return projects


def get_github_repos(account: str) -> list[str]:
    """Get list of GitHub repos for an account."""
    try:
        result = subprocess.run(
            ["gh", "repo", "list", account, "--limit", "100", "--json", "name", "--jq", ".[].name"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return []
        return [r.strip() for r in result.stdout.strip().split("\n") if r.strip()]
    except (subprocess.TimeoutExpired, OSError):
        return []


def select_project(
    input_name: str | None,
    base_dir: Path,
    github_account: str,
    ssh_host: str = "github.com",
) -> str | None:
    """Select a project interactively or by name.

    Returns the project name, or None if no project was selected.
    Clones from GitHub if the project isn't local.
    """
    # Exact local match
    if input_name and (base_dir / input_name / ".git").is_dir():
        return input_name

    local = get_local_projects(base_dir)
    remote = get_github_repos(github_account)

    # Build combined list: local projects + remote-only repos
    local_set = set(local)
    entries: list[tuple[str, str]] = []  # (name, source)
    for p in local:
        entries.append((p, "local"))
    for r in remote:
        if r not in local_set:
            entries.append((r, "github"))
    entries.sort(key=lambda e: e[0])

    if not entries:
        print("Error: No local or GitHub projects found")
        return None

    # If input was given, try fuzzy match
    if input_name:
        matches = [(n, s) for n, s in entries if input_name.lower() in n.lower()]
        if len(matches) == 1:
            name, source = matches[0]
            if source == "github":
                if not _clone_repo(github_account, name, base_dir, ssh_host):
                    return None
            return name
        if len(matches) > 1:
            # Multiple matches — fall through to picker with these
            entries = matches

    # Interactive picker
    if shutil.which("fzf"):
        return _fzf_pick(entries, base_dir, github_account, ssh_host, query=input_name)
    else:
        return _menu_pick(entries, base_dir, github_account, ssh_host)


def _fzf_pick(
    entries: list[tuple[str, str]],
    base_dir: Path,
    github_account: str,
    ssh_host: str = "github.com",
    query: str | None = None,
) -> str | None:
    """Use fzf for interactive selection."""
    lines = [f"{name} ({source})" for name, source in entries]
    fzf_input = "\n".join(lines)

    cmd = [
        "fzf", "--height=20", "--reverse",
        "--header=Select project (local or clone from GitHub):",
        "--select-1", "--exit-0",
    ]
    if query:
        cmd.extend(["--query", query])

    try:
        result = subprocess.run(
            cmd,
            input=fzf_input,
            capture_output=True,
            text=True,
        )
    except OSError:
        return _menu_pick(entries, base_dir, github_account, ssh_host)

    if result.returncode != 0 or not result.stdout.strip():
        return None

    selected = result.stdout.strip()
    # Parse "name (source)"
    name = selected.rsplit(" (", 1)[0]
    source = "github" if "(github)" in selected else "local"

    if source == "github":
        if not _clone_repo(github_account, name, base_dir, ssh_host):
            return None
    return name


def _menu_pick(
    entries: list[tuple[str, str]],
    base_dir: Path,
    github_account: str,
    ssh_host: str = "github.com",
) -> str | None:
    """Numbered menu fallback when fzf is not available."""
    for i, (name, source) in enumerate(entries, 1):
        print(f"  {i}) {name} ({source})")

    try:
        choice = input("Enter number: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not choice.isdigit():
        return None
    idx = int(choice) - 1
    if idx < 0 or idx >= len(entries):
        return None

    name, source = entries[idx]
    if source == "github":
        if not _clone_repo(github_account, name, base_dir, ssh_host):
            return None
    return name


def _clone_repo(account: str, name: str, base_dir: Path, ssh_host: str = "github.com") -> bool:
    """Clone a GitHub repo into the base directory via SSH."""
    print(f"Cloning {name} from GitHub...")
    try:
        result = subprocess.run(
            ["git", "clone", f"git@{ssh_host}:{account}/{name}.git", str(base_dir / name)],
            timeout=120,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        print(f"Error: Failed to clone {name}")
        return False


def get_repo_url(project_path: Path) -> str | None:
    """Get the GitHub owner/repo string from a git remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        # Handle both SSH and HTTPS URLs
        # git@github.com:Owner/Repo.git -> Owner/Repo
        # https://github.com/Owner/Repo.git -> Owner/Repo
        for prefix in ["git@github.com:", "https://github.com/"]:
            if url.startswith(prefix):
                return url[len(prefix):].removesuffix(".git")
        # Handle SSH host aliases (e.g., git@github-work:Owner/Repo.git)
        if ":" in url and "@" in url:
            return url.split(":", 1)[1].removesuffix(".git")
        return None
    except OSError:
        return None
