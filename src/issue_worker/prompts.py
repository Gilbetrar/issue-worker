"""Template loading and variable substitution for agent prompts."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


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
