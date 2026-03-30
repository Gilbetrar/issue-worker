"""Main orchestration loop for autonomous Claude Code sessions."""

from __future__ import annotations

import os
import signal as signal_mod
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import signals, terminal, notifications, prompts
from .logging import setup_logging, prune_logs, get_logger

CONSOLIDATION_TIMEOUT = 300  # 5 minutes
CONSOLIDATION_LINE_THRESHOLD = 200
AGENT_EXIT_GRACE_PERIOD = 30  # seconds to wait before detaching from a finished agent


@dataclass
class Config:
    """Orchestrator configuration (hardcoded defaults for MVP)."""

    projects_dir: Path = field(default_factory=lambda: Path.home() / "AI" / "Projects")
    github_account: str = "Gilbetrar"
    max_iterations: int = 10
    poll_timeout: int = 1800  # 30 minutes
    max_crashes: int = 3
    test_mode: bool = False
    verbose: bool = False

    # Paths to Claude config files (resolved relative to package)
    settings_file: Path | None = None
    mcp_config: Path | None = None

    def __post_init__(self) -> None:
        if self.settings_file is None:
            self.settings_file = _defaults_dir() / "settings.json"
        if self.mcp_config is None:
            self.mcp_config = _defaults_dir() / "mcp.json"
        if self.test_mode:
            self.max_iterations = 3


@dataclass
class SyncResult:
    """Result of a repository sync operation."""

    success: bool
    message: str


@dataclass
class RunResult:
    """Result of an orchestrator run."""

    iterations_completed: int
    final_status: str  # "complete", "max_iterations", "aborted", "error"
    message: str


def run(
    project: str,
    repo: str,
    project_path: Path,
    config: Config,
    use_test_launcher: bool = False,
) -> RunResult:
    """Run the orchestration loop.

    Args:
        project: Project name.
        repo: GitHub owner/repo string.
        project_path: Absolute path to the project directory.
        config: Orchestrator configuration.
        use_test_launcher: If True, use subprocess instead of Terminal tabs.
    """
    launcher = terminal.open_terminal_tab_test if use_test_launcher else terminal.open_terminal_tab

    signal_file = project_path / "SIGNAL.txt"
    started_file = project_path / ".issue-worker-started"

    # Set up logging
    log_file = setup_logging(verbose=config.verbose)
    log = get_logger()
    log.debug("Log file: %s", log_file)
    prune_logs()

    # Print banner
    if config.test_mode:
        _banner("Issue Worker - SELF-TEST MODE")
    else:
        _banner("Issue Worker - Autonomous GitHub Issue Processor")
    log.info("Project: %s", project)
    log.info("Path: %s", project_path)
    log.info("Repo: %s", repo)
    log.info("Branch: main (direct)")
    log.info("Max iterations: %s", config.max_iterations)
    log.info("")

    # Ensure on main and synced
    sync_result = _sync_main(project_path)
    if not sync_result.success:
        log.error("Repository sync failed: %s", sync_result.message)
        return RunResult(
            iterations_completed=0,
            final_status="error",
            message=f"Repository sync failed: {sync_result.message}",
        )

    # Check for unresolved handoff from a previous run
    handoff_file = project_path / "HANDOFF.md"
    if handoff_file.exists():
        log.info("")
        log.info("╔══════════════════════════════════════════════════════════╗")
        log.info("║  BLOCKED — Unresolved handoff from a previous run      ║")
        log.info("╚══════════════════════════════════════════════════════════╝")
        log.info("")
        log.info("  HANDOFF.md exists at: %s", handoff_file)
        log.info("  This file contains instructions from a prior paused agent.")
        log.info("")
        log.info("  To resolve:")
        log.info("    1. Read HANDOFF.md and complete the requested action")
        log.info("    2. Delete HANDOFF.md when done")
        log.info("  Or to skip: rm %s", handoff_file)
        log.info("")
        notifications.notify("BLOCKED", "Issue worker: unresolved handoff from prior run")
        log.info("  Waiting for HANDOFF.md to be resolved (deleted)...")
        while handoff_file.exists():
            time.sleep(5)
        log.info("  HANDOFF.md resolved. Proceeding with launch...")
        log.info("")

    crash_count = 0
    iteration = 1
    crash_tested = False  # Test mode: only simulate crash once on iteration 2
    prev_pid: int | None = None  # Track previous agent PID to prevent duplicates

    while iteration <= config.max_iterations:
        log.info("")
        log.info("─" * 59)
        log.info("  Iteration %d of %d", iteration, config.max_iterations)
        log.info("─" * 59)

        # Block if previous agent is still alive — never spawn duplicates
        _wait_for_agent_exit(prev_pid, "previous iteration")

        # Consolidation: distill SESSION_LOG.md at iteration 1 and every 10th
        if _should_consolidate(iteration):
            _run_consolidation(project_path, config, launcher)

        # Build prompt and write to temp file
        prompt_file = Path(tempfile.mktemp(prefix="iw-prompt-", suffix=".md"))
        try:
            prompt_text = prompts.render_prompt(
                project=project,
                repo=repo,
                project_path=str(project_path),
                iteration=iteration,
                max_iterations=config.max_iterations,
            )
            prompt_file.write_text(prompt_text)
        except FileNotFoundError:
            return RunResult(
                iterations_completed=iteration - 1,
                final_status="error",
                message="Could not find prompt template. Check templates/prompt.md exists.",
            )

        # Clean slate
        signals.clear_signal(signal_file)
        (project_path / "HANDOFF.md").unlink(missing_ok=True)
        started_file.unlink(missing_ok=True)

        # Build command
        if config.test_mode:
            if iteration == 2 and not crash_tested:
                # Simulate agent crash: writes CRASHED signal (once)
                crash_tested = True
                tab_cmd = (
                    f"cd '{project_path}' && echo $$ > '{started_file}' && "
                    f"echo 'TEST: simulating agent crash' && "
                    f"printf 'CRASHED\\nTest crash — agent exited abnormally.\\n' > '{signal_file}.tmp' && "
                    f"mv '{signal_file}.tmp' '{signal_file}'"
                )
            else:
                tab_cmd = (
                    f"cd '{project_path}' && echo $$ > '{started_file}' && "
                    f"echo 'TEST MODE: sleeping 5s to simulate work...' && sleep 5 && "
                    f"printf 'WORKING\\nTest iteration {iteration} completed.\\n' > '{signal_file}.tmp' && "
                    f"mv '{signal_file}.tmp' '{signal_file}'"
                )
        else:
            tab_cmd = (
                f"cd '{project_path}' && echo $$ > '{started_file}' && "
                f"claude --settings '{config.settings_file}' --mcp-config '{config.mcp_config}' "
                f"--dangerously-skip-permissions < '{prompt_file}' ; "
                f"[ ! -f '{signal_file}' ] && "
                f"printf 'CRASHED\\nAgent exited without writing signal file.\\n' > '{signal_file}.tmp' && "
                f"mv '{signal_file}.tmp' '{signal_file}'"
            )

        # Launch
        log.info("Opening Terminal tab for agent...")
        log.debug("Tab command: %s", tab_cmd)
        if not launcher(tab_cmd, f"Issue Worker - Iteration {iteration}"):
            crash_count += 1
            log.error("Failed to open Terminal tab. (%d/%d)", crash_count, config.max_crashes)
            if crash_count >= config.max_crashes:
                notifications.notify("ABORTED", "Issue worker: agents failing to start", "Sosumi")
                prompt_file.unlink(missing_ok=True)
                return RunResult(
                    iterations_completed=iteration - 1,
                    final_status="aborted",
                    message=f"Failed to open Terminal tabs {config.max_crashes} times.",
                )
            log.info("  Retrying in 5s...")
            time.sleep(5)
            continue  # Retry same iteration

        # Verify agent started
        log.info("Verifying agent started...")
        if not _wait_for_file(started_file, timeout=15, interval=1):
            crash_count += 1
            log.error("Agent never started (%d/%d)", crash_count, config.max_crashes)
            if crash_count >= config.max_crashes:
                notifications.notify("ABORTED", "Issue worker: agents failing to start", "Sosumi")
                prompt_file.unlink(missing_ok=True)
                return RunResult(
                    iterations_completed=iteration - 1,
                    final_status="aborted",
                    message=f"Agent failed to start {config.max_crashes} times.",
                )
            log.info("  Retrying in 5s...")
            time.sleep(5)
            continue

        pid_str = started_file.read_text().strip() if started_file.exists() else ""
        pid = int(pid_str) if pid_str.isdigit() else None
        prev_pid = pid  # Track for block-while-alive gate
        log.info("Agent started (PID: %s)", pid or "unknown")
        # Keep started_file — we need the PID for liveness checks on timeout

        # Wait for signal
        log.info("Waiting for Claude to finish (timeout %ds)...", config.poll_timeout)
        signal = signals.wait_for_signal(signal_file, config.poll_timeout)

        if signal is None:
            # Timed out — check if agent is stuck (still alive) or exited silently
            agent_alive = pid is not None and _is_process_alive(pid)

            if agent_alive:
                log.warning("")
                log.warning("Agent process is still alive but has not signaled.")
                log.warning("  This usually means it is blocked on a permission prompt.")
                notifications.notify_stuck_agent(
                    project=project,
                    iteration=iteration,
                    pid=pid,
                    elapsed_minutes=config.poll_timeout // 60,
                )
                signals.write_signal(signal_file, "PAUSED", "Agent stuck: process alive but no signal after timeout.")
                signal = signals.read_signal(signal_file)
            elif (project_path / "HANDOFF.md").exists():
                signals.write_signal(signal_file, "PAUSED", "Timeout: agent exited but HANDOFF.md exists.")
                signal = signals.read_signal(signal_file)
            # else: signal stays None — dead agent with no signal is a failure

        time.sleep(0.2)

        # Clean up temp files
        signals.clear_signal(signal_file)
        started_file.unlink(missing_ok=True)
        prompt_file.unlink(missing_ok=True)

        # Failure detection: no signal or CRASHED (shell wrapper fallback)
        if signal is None or signal.status == "CRASHED":
            reason = "no signal written" if signal is None else (signal.summary or "agent crashed")
            crash_count += 1
            log.warning("")
            log.warning("Agent failed: %s (%d/%d)", reason, crash_count, config.max_crashes)
            if crash_count >= config.max_crashes:
                notifications.notify("ABORTED", "Issue worker: agents failing", "Sosumi")
                return RunResult(
                    iterations_completed=iteration - 1,
                    final_status="aborted",
                    message=f"{config.max_crashes} agent failures.",
                )
            log.info("  Retrying in 10s...")
            time.sleep(10)
            continue  # Retry same iteration

        # Display summary
        if signal.summary:
            log.info("")
            for line in signal.summary.split("\n"):
                log.info("  %s", line)

        # Override WORKING -> PAUSED if HANDOFF.md exists
        if signal.status == "WORKING" and (project_path / "HANDOFF.md").exists():
            log.info("Signal was WORKING but HANDOFF.md exists — treating as PAUSED.")
            signal = signals.Signal(status="PAUSED", summary=signal.summary)

        # Handle signals
        if signal.status == "COMPLETE":
            log.info("")
            _banner("All work completed!")
            log.info("  Project: %s", project_path)
            return RunResult(
                iterations_completed=iteration,
                final_status="complete",
                message="All issues complete.",
            )

        if signal.status == "NO_WORK":
            log.info("")
            _banner("No actionable work found")
            log.info("  Project: %s", project_path)
            return RunResult(
                iterations_completed=iteration,
                final_status="complete",
                message="No actionable issues found.",
            )

        if signal.status == "PAUSED":
            crash_count = 0
            log.info("")
            log.info("╔══════════════════════════════════════════════════════════╗")
            log.info("║  PAUSED — Human action required                        ║")
            log.info("╚══════════════════════════════════════════════════════════╝")

            # Check if this is a stuck-agent pause (agent process still alive)
            agent_still_alive = pid is not None and _is_process_alive(pid)

            if agent_still_alive:
                log.warning("")
                log.warning("  Agent PID %d is STILL RUNNING (likely stuck on permission prompt).", pid)
                log.warning("  Check Terminal.app for a tab waiting for input.")
                log.info("")

                action = notifications.prompt_stuck_action(pid, project)

                if action == "kill":
                    log.info("  Killing stuck agent (PID %d)...", pid)
                    _kill_agent(pid)
                    prev_pid = None
                    started_file.unlink(missing_ok=True)
                    time.sleep(2)
                    log.info("  Agent killed. Retrying iteration %d...", iteration)
                    continue  # Retry same iteration — interrupted work shouldn't consume budget
                else:
                    # Block until agent exits — never advance with a live agent
                    log.info("  Leaving agent running. Waiting for it to exit...")
                    log.info("  To kill manually: kill %d", pid)
                    _wait_for_agent_exit(pid, "stuck agent")
                    prev_pid = None
                    log.info("  Stuck agent exited. Restarting iteration...")
                    continue  # Retry same iteration with fresh agent

            notifications.notify("PAUSED", "Issue worker needs human action")

            if (project_path / "HANDOFF.md").exists():
                log.info("")
                log.info("  HANDOFF.md found. Waiting for interactive session...")
                log.info("  Run: cd %s && claude    then:  /pick-up-handoff", project_path)
                log.info("")
                while (project_path / "HANDOFF.md").exists():
                    time.sleep(5)
                log.info("  HANDOFF.md deleted. Resuming...")
            else:
                log.info("")
                try:
                    input("  No HANDOFF.md found. Press Enter to resume...")
                except (EOFError, KeyboardInterrupt):
                    return RunResult(
                        iterations_completed=iteration,
                        final_status="aborted",
                        message="User interrupted during PAUSED state.",
                    )

            time.sleep(2)
            iteration += 1
            continue

        if signal.status == "WORKING":
            crash_count = 0
            log.info("")
            log.info("Work unit completed. Continuing to next iteration...")
            time.sleep(2)
            iteration += 1
            continue

        # Unknown signal — don't advance, treat as failure
        log.warning("Unknown signal '%s'. Treating as failure.", signal.status)
        crash_count += 1
        if crash_count >= config.max_crashes:
            notifications.notify("ABORTED", "Issue worker: unknown signals", "Sosumi")
            return RunResult(
                iterations_completed=iteration - 1,
                final_status="aborted",
                message=f"Unknown signal '{signal.status}' after {config.max_crashes} failures.",
            )
        continue

    return RunResult(
        iterations_completed=config.max_iterations,
        final_status="max_iterations",
        message=f"Reached max iterations ({config.max_iterations}).",
    )


def _should_consolidate(iteration: int) -> bool:
    """Check if consolidation should run (iteration 1 and every 10th)."""
    return iteration == 1 or iteration % 10 == 0


def _run_consolidation(
    project_path: Path,
    config: Config,
    launcher,
) -> bool:
    """Run learnings consolidation if SESSION_LOG.md is large enough.

    Launches a separate agent to distill SESSION_LOG.md into LEARNINGS.md.
    Non-fatal: logs warnings on failure but never raises.

    Serialized with the same rigor as normal worker launches:
    - PID tracked via started file
    - Startup verified before waiting for signal
    - Process exit confirmed after signal received

    Returns True if consolidation completed, False if skipped or failed.
    """
    log = get_logger()
    session_log = project_path / "SESSION_LOG.md"

    if not session_log.exists():
        log.info("No SESSION_LOG.md — skipping consolidation.")
        return False

    line_count = len(session_log.read_text().splitlines())
    if line_count <= CONSOLIDATION_LINE_THRESHOLD:
        log.info(
            "SESSION_LOG.md is %d lines (threshold: %d) — skipping.",
            line_count,
            CONSOLIDATION_LINE_THRESHOLD,
        )
        return False

    log.info("SESSION_LOG.md is %d lines — running consolidation...", line_count)

    consolidation_signal = project_path / "CONSOLIDATION_SIGNAL.txt"
    consolidation_started = project_path / ".issue-worker-consolidation-started"
    consolidation_signal.unlink(missing_ok=True)
    consolidation_started.unlink(missing_ok=True)

    prompt_file = Path(tempfile.mktemp(prefix="iw-consolidate-", suffix=".md"))
    try:
        prompt_text = prompts.render_consolidation_prompt(str(project_path))
        prompt_file.write_text(prompt_text)
    except FileNotFoundError:
        log.warning("Consolidation template not found — skipping.")
        prompt_file.unlink(missing_ok=True)
        return False

    if config.test_mode:
        tab_cmd = (
            f"cd '{project_path}' && echo $$ > '{consolidation_started}' && "
            f"echo 'TEST: consolidation running...' && sleep 2 && "
            f"printf 'DONE\\n' > '{consolidation_signal}.tmp' && "
            f"mv '{consolidation_signal}.tmp' '{consolidation_signal}'"
        )
    else:
        tab_cmd = (
            f"cd '{project_path}' && echo $$ > '{consolidation_started}' && "
            f"claude --settings '{config.settings_file}' --mcp-config '{config.mcp_config}' "
            f"--dangerously-skip-permissions < '{prompt_file}' ; "
            f"rm -f '{prompt_file}'"
        )

    if not launcher(tab_cmd, "Issue Worker - Consolidation"):
        log.warning("Failed to open consolidation tab — skipping.")
        prompt_file.unlink(missing_ok=True)
        return False

    # Verify consolidation agent started (same gate as normal workers)
    if not _wait_for_file(consolidation_started, timeout=15, interval=1):
        log.warning("Consolidation agent never started — skipping.")
        prompt_file.unlink(missing_ok=True)
        return False

    pid_str = consolidation_started.read_text().strip()
    pid = int(pid_str) if pid_str.isdigit() else None
    log.info("Consolidation agent started (PID: %s)", pid or "unknown")

    log.info("Waiting for consolidation (timeout %ds)...", CONSOLIDATION_TIMEOUT)
    elapsed = 0.0
    completed = False
    while elapsed < CONSOLIDATION_TIMEOUT:
        if consolidation_signal.exists():
            content = consolidation_signal.read_text().strip()
            if content:
                completed = True
                break
        time.sleep(5)
        elapsed += 5

    if not completed:
        log.warning("Consolidation timed out after %ds.", CONSOLIDATION_TIMEOUT)

    # Block until consolidation process exits — never overlap with the main worker
    _wait_for_agent_exit(pid, "consolidation")

    # Clean up
    consolidation_signal.unlink(missing_ok=True)
    consolidation_started.unlink(missing_ok=True)
    prompt_file.unlink(missing_ok=True)

    if completed:
        log.info("Consolidation complete.")
    return completed


def _sync_main(project_path: Path) -> SyncResult:
    """Ensure we're on main and synced. Returns structured success/failure.

    On failure, attempts to restore any stashed changes before returning.
    The orchestrator must not launch agents when this returns success=False.
    """
    log = get_logger()
    stashed = False

    # Detect current branch
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return SyncResult(
            success=False,
            message=f"Failed to detect current branch: {result.stderr.strip()}",
        )
    current_branch = result.stdout.strip()

    # 2. Check for dirty working tree
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )
    if status_result.returncode != 0:
        return SyncResult(
            success=False,
            message=f"Failed to check working tree: {status_result.stderr.strip()}",
        )
    is_dirty = bool(status_result.stdout.strip())

    # 3. Stash dirty changes BEFORE checkout (so checkout doesn't conflict)
    if is_dirty:
        log.info("Working tree has changes. Stashing before sync...")
        stash_result = subprocess.run(
            ["git", "stash", "--include-untracked"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if stash_result.returncode != 0:
            return SyncResult(
                success=False,
                message=f"Failed to stash changes: {stash_result.stderr.strip()}",
            )
        stashed = True

    # 4. Checkout main if needed
    if current_branch != "main":
        log.info("Switching to main branch...")
        checkout_result = subprocess.run(
            ["git", "checkout", "main"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if checkout_result.returncode != 0:
            _try_restore_stash(project_path, stashed)
            return SyncResult(
                success=False,
                message=f"Failed to checkout main: {checkout_result.stderr.strip()}",
            )

    # Fetch and pull
    log.info("Syncing with remote...")
    try:
        result = subprocess.run(
            ["git", "fetch", "origin"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            _try_restore_stash(project_path, stashed)
            return SyncResult(
                success=False,
                message=f"git fetch failed: {result.stderr.strip()}",
            )

        result = subprocess.run(
            ["git", "pull", "--rebase"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            _try_restore_stash(project_path, stashed)
            return SyncResult(
                success=False,
                message=f"git pull --rebase failed: {result.stderr.strip()}",
            )
    except subprocess.TimeoutExpired:
        _try_restore_stash(project_path, stashed)
        return SyncResult(success=False, message="git sync timed out")

    # Restore stashed changes
    if stashed:
        log.info("Restoring stashed changes...")
        result = subprocess.run(
            ["git", "stash", "pop"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return SyncResult(
                success=False,
                message=(
                    f"Stash restore failed (possible conflict). "
                    f"Changes remain in stash. "
                    f"Run 'git stash show' in {project_path} to review."
                ),
            )

    log.info("Working directly on main branch.")
    return SyncResult(success=True, message="Synced to main.")


def _try_restore_stash(project_path: Path, stashed: bool) -> None:
    """Best-effort stash restore after a sync failure."""
    if not stashed:
        return
    log = get_logger()
    log.info("Restoring stashed changes after sync failure...")
    result = subprocess.run(
        ["git", "stash", "pop"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.warning("Could not restore stash: %s", result.stderr.strip())
        log.warning("  Changes remain in stash. Run 'git stash show' to review.")


def _wait_for_file(path: Path, timeout: int, interval: float = 1.0) -> bool:
    """Wait for a file to appear."""
    elapsed = 0.0
    while elapsed < timeout:
        if path.exists():
            return True
        time.sleep(interval)
        elapsed += interval
    return False


def _banner(text: str) -> None:
    """Print a boxed banner."""
    log = get_logger()
    line = "═" * 59
    log.info(line)
    log.info("  %s", text)
    log.info(line)


def _is_process_alive(pid: int) -> bool:
    """Check if a process is still running using kill(pid, 0)."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we don't own it


def _kill_agent(pid: int) -> None:
    """Terminate a stuck agent process. Tries SIGTERM, then SIGKILL."""
    try:
        os.kill(pid, signal_mod.SIGTERM)
        for _ in range(10):
            time.sleep(0.5)
            if not _is_process_alive(pid):
                return
        os.kill(pid, signal_mod.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        get_logger().warning("  Cannot kill PID %d (permission denied)", pid)


def _wait_for_agent_exit(pid: int | None, label: str = "") -> None:
    """Wait for the given agent process to exit, with a timeout.

    This is the primary guard against duplicate concurrent agents.
    Called before every launcher() invocation.

    Waits up to AGENT_EXIT_GRACE_PERIOD seconds for a natural exit.
    If the process is still alive after that, logs a warning and
    detaches (returns without killing).  This is safe because this
    function is only called after the previous agent's signal has
    already been written and processed — the work is done, the
    lingering process is just orphaned MCP servers.
    """
    if pid is None or not _is_process_alive(pid):
        return
    log = get_logger()
    suffix = f" ({label})" if label else ""
    log.info("  Previous agent (PID %d) still alive%s. Waiting for exit...", pid, suffix)

    elapsed = 0.0
    while elapsed < AGENT_EXIT_GRACE_PERIOD:
        if not _is_process_alive(pid):
            log.info("  Previous agent exited.")
            return
        time.sleep(5)
        elapsed += 5

    log.warning(
        "  Agent PID %d did not exit after %ds — likely lingering MCP servers. "
        "Detaching and proceeding to next iteration.",
        pid,
        AGENT_EXIT_GRACE_PERIOD,
    )


def _defaults_dir() -> Path:
    """Get the path to the bundled defaults directory."""
    return Path(__file__).parent.parent.parent / "defaults"
