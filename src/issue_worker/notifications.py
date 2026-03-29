"""macOS notifications via osascript."""

from __future__ import annotations

import subprocess


def notify(title: str, message: str, sound: str = "Glass") -> None:
    """Show a macOS notification. Fails silently if osascript is unavailable."""
    script = (
        f'display notification "{_escape(message)}" '
        f'with title "{_escape(title)}" '
        f'sound name "{sound}"'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


def notify_stuck_agent(
    project: str,
    iteration: int,
    pid: int,
    elapsed_minutes: int,
) -> None:
    """Send high-visibility notification that an agent is stuck."""
    message = (
        f"Agent stuck in {project} (iter {iteration}, PID {pid}). "
        f"No signal after {elapsed_minutes}min. Likely permission prompt."
    )
    notify("STUCK AGENT", message, "Sosumi")
    _say(f"Issue worker agent is stuck in {project}. Needs your attention.")


def prompt_stuck_action(pid: int, project: str) -> str:
    """Show a macOS dialog asking what to do about a stuck agent.

    Returns: "kill", "leave", or "timeout" (dialog gave up after 5 min).
    """
    script = (
        f'display alert "Issue Worker: Agent Stuck" '
        f'message "PID {pid} in {_escape(project)} appears blocked on a permission prompt.\\n\\n'
        f'Kill it and resume, or leave it running for manual intervention?" '
        f'buttons {{"Kill & Resume", "Leave Running"}} '
        f'default button "Leave Running" '
        f'giving up after 300'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=310,
        )
        stdout = result.stdout or ""
        if "Kill" in stdout:
            return "kill"
        if "gave up" in stdout:
            return "timeout"
        return "leave"
    except (subprocess.TimeoutExpired, OSError):
        return "timeout"


def _say(text: str) -> None:
    """Speak text aloud using macOS say command. Non-blocking."""
    try:
        subprocess.Popen(
            ["say", "-v", "Samantha", text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def _escape(s: str) -> str:
    """Escape a string for AppleScript."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
