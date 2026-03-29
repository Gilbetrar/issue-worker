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


def open_terminal_tab(cmd: str, title: str = "Worker") -> bool:
    """Open a new Terminal.app tab and run a command in it.

    Uses Terminal.app's native 'do script' AppleScript command, which does NOT
    require the app to be frontmost (unlike the keystroke approach).

    Returns True if the tab was opened successfully.
    """
    # Write command to a temp script to avoid AppleScript string injection
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
    except OSError:
        return False

    # Use Terminal.app's 'do script' — no System Events, no keystroke simulation.
    # Pass the script path and title as arguments to osascript to avoid all
    # string escaping issues (AppleScript's `item N of argv` is injection-safe).
    osascript_code = '''
on run argv
    set scriptPath to item 1 of argv
    set tabTitle to item 2 of argv
    tell application "Terminal"
        activate
        do script "/bin/bash " & quoted form of scriptPath & "; rm -f " & quoted form of scriptPath
        set custom title of selected tab of front window to tabTitle
    end tell
end run
'''

    for attempt in range(3):
        try:
            result = subprocess.run(
                ["osascript", "-e", osascript_code, str(script_path), title],
                capture_output=True,
                timeout=15,
            )
            if result.returncode == 0:
                return True
            # AppleScript error — retry
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


