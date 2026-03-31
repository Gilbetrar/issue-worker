"""Template loading and variable substitution for agent prompts."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


_PYTHON_VERIFY = """\
   ```bash
   uv run ruff check src/ tests/   # Lint
   uv run pytest tests/ -v          # Tests
   ```"""

_NODE_VERIFY = """\
   ```bash
   npm run typecheck
   npm run lint
   npm test
   npm run build
   ```"""

_GENERIC_VERIFY = """\
   ```bash
   # Check LEARNINGS.md or the repo's CI config for the correct commands
   ```"""


def detect_verify_commands(project_path: str) -> str:
    """Return verification command block appropriate for the project type."""
    p = Path(project_path)
    if (p / "pyproject.toml").is_file():
        return _PYTHON_VERIFY
    if (p / "package.json").is_file():
        return _NODE_VERIFY
    return _GENERIC_VERIFY


def _read_template(name: str) -> str:
    """Read a bundled template, supporting editable and wheel installs."""
    pkg_root = Path(__file__).parent.parent.parent
    repo_template = pkg_root / "templates" / name
    if repo_template.is_file():
        return repo_template.read_text()

    return resources.files("issue_worker").joinpath("templates", name).read_text()


def render_prompt(
    project: str,
    repo: str,
    project_path: str,
    iteration: int,
    max_iterations: int,
) -> str:
    """Render the main agent prompt template with variables substituted."""
    template = _read_template("prompt.md")
    return _substitute(template, {
        "PROJECT": project,
        "REPO": repo,
        "PROJECT_PATH": project_path,
        "ITERATION": str(iteration),
        "MAX_ITERATIONS": str(max_iterations),
        "VERIFY_COMMANDS": detect_verify_commands(project_path),
    })


def render_consolidation_prompt(project_path: str) -> str:
    """Render the consolidation agent prompt template."""
    template = _read_template("consolidate-learnings.md")
    return _substitute(template, {"PROJECT_PATH": project_path})


def _substitute(template: str, variables: dict[str, str]) -> str:
    """Replace {VARIABLE} placeholders in a template string."""
    result = template
    for key, value in variables.items():
        result = result.replace("{" + key + "}", value)
    return result
