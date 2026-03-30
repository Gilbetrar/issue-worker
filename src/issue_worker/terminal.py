"""Terminal session launchers for running Claude Code in isolated tabs."""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path


# Track temp scripts for cleanup
_temp_scripts: list[Path] = []


def _cleanup_temp_scripts() -> None:
    """Remove any leftover temp scripts."""
    for p in _temp_scripts:
        p.unlink(missing_ok=True)
    _temp_scripts.clear()


import atexit

atexit.register(_cleanup_temp_scripts)


def _build_applescript() -> str:
    """Build the AppleScript that opens a command in a Terminal tab.

    When Terminal already has an open window, creates a new tab via Cmd+T
    (System Events keystroke) instead of opening a new window.  Falls back
    to a new window when no windows exist.

    The script expects two positional arguments from osascript:
      argv[1] = path to the shell script to execute
      argv[2] = custom tab title
    """
    return '''\
on run argv
    set scriptPath to item 1 of argv
    set tabTitle to item 2 of argv
    set shellCmd to "/bin/bash " & quoted form of scriptPath & "; rm -f " & quoted form of scriptPath

    tell application "Terminal"
        activate

        if (count of windows) > 0 then
            -- Prefer a tab in the existing window
            tell application "System Events"
                tell process "Terminal"
                    keystroke "t" using command down
                end tell
            end tell
            delay 0.5
            do script shellCmd in front window
        else
            -- No window yet — do script creates one
            do script shellCmd
        end if

        set custom title of selected tab of front window to tabTitle
    end tell
end run'''


def _write_temp_script(cmd: str) -> Path | None:
    """Write *cmd* to an executable temp script. Returns the path or None."""
    try:
        tmp = tempfile.NamedTemporaryFile(
            prefix="iw-tab-",
            suffix=".sh",
            mode="w",
            delete=False,
        )
        tmp.write(cmd)
        tmp.write("\n")
        tmp.close()
        script_path = Path(tmp.name)
        script_path.chmod(0o755)
        _temp_scripts.append(script_path)
        return script_path
    except OSError:
        return None


def _invoke_osascript(
    applescript: str, script_path: Path, title: str
) -> bool:
    """Run *applescript* via osascript with retry logic.

    Returns True on success.
    """
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["osascript", "-e", applescript, str(script_path), title],
                capture_output=True,
                timeout=15,
            )
            if result.returncode == 0:
                return True
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return False
        except subprocess.TimeoutExpired:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return False
        except OSError:
            return False

    return False


def open_terminal_tab(cmd: str, title: str = "Worker") -> bool:
    """Open a new Terminal.app tab and run a command in it.

    Prefers opening a tab in an existing Terminal window.  Falls back to
    a new window when no windows are open.

    Returns True if the tab was opened successfully.
    """
    script_path = _write_temp_script(cmd)
    if script_path is None:
        return False

    return _invoke_osascript(_build_applescript(), script_path, title)


def open_terminal_tab_test(cmd: str, title: str = "Worker") -> bool:
    """Test stub: run the command directly via bash (no Terminal tab)."""
    try:
        subprocess.Popen(
            ["/bin/bash", "-c", cmd],
            start_new_session=True,
        )
        return True
    except OSError:
        return False
