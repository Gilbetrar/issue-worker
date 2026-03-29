"""Template loading and variable substitution for agent prompts."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def _templates_dir() -> Path:
    """Get the path to the bundled templates directory."""
    # In editable install, this resolves to the repo's templates/ directory
    pkg_root = Path(__file__).parent.parent.parent
    templates = pkg_root / "templates"
    if templates.is_dir():
        return templates
    # Fallback: check importlib.resources
    ref = resources.files("issue_worker").joinpath("../../templates")
    return Path(str(ref))


def render_prompt(
    project: str,
    repo: str,
    project_path: str,
    iteration: int,
    max_iterations: int,
) -> str:
    """Render the main agent prompt template with variables substituted."""
    template = (_templates_dir() / "prompt.md").read_text()
    return _substitute(template, {
        "PROJECT": project,
        "REPO": repo,
        "PROJECT_PATH": project_path,
        "ITERATION": str(iteration),
        "MAX_ITERATIONS": str(max_iterations),
    })


def render_consolidation_prompt(project_path: str) -> str:
    """Render the consolidation agent prompt template."""
    template = (_templates_dir() / "consolidate-learnings.md").read_text()
    return _substitute(template, {"PROJECT_PATH": project_path})


def _substitute(template: str, variables: dict[str, str]) -> str:
    """Replace {VARIABLE} placeholders in a template string."""
    result = template
    for key, value in variables.items():
        result = result.replace("{" + key + "}", value)
    return result
