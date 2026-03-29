"""CLI entry point for issue-worker."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .logging import list_log_files, LOG_DIR
from .orchestrator import Config, run
from .project import select_project, get_repo_url


def _logs_command(args: argparse.Namespace) -> None:
    """Show recent log files and optionally tail the latest."""
    log_files = list_log_files()
    if not log_files:
        print(f"No log files found in {LOG_DIR}")
        return

    print(f"Log directory: {LOG_DIR}")
    print(f"Log files ({len(log_files)}):")
    print()
    for f in log_files:
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name}  ({size_kb:.1f} KB)")

    # Tail the latest log
    latest = log_files[0]
    tail_lines = args.tail if hasattr(args, "tail") and args.tail else 20
    print()
    print(f"── Latest: {latest.name} (last {tail_lines} lines) ──")
    print()
    lines = latest.read_text().splitlines()
    for line in lines[-tail_lines:]:
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="issue-worker",
        description="Autonomous Claude Code issue processor",
    )
    subparsers = parser.add_subparsers(dest="command")

    # logs subcommand
    logs_parser = subparsers.add_parser("logs", help="Show recent log files and tail the latest")
    logs_parser.add_argument("-n", "--tail", type=int, default=20, help="Number of lines to show from latest log")

    # Main arguments (when no subcommand)
    parser.add_argument("project", nargs="?", help="Project name (fuzzy matched) or omit for picker")
    parser.add_argument("max_iterations", nargs="?", type=int, help="Max iterations (default: 10)")
    parser.add_argument("--test", action="store_true", help="Self-test mode (3 iterations with stubs)")
    parser.add_argument("--max-iterations", type=int, dest="max_iterations_flag", help="Max iterations")
    parser.add_argument("--poll-timeout", type=int, help="Signal poll timeout in seconds")
    parser.add_argument("--verbose", action="store_true", help="Debug output")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    # Handle logs subcommand
    if args.command == "logs":
        _logs_command(args)
        return

    # Resolve max_iterations: flag > positional > default
    max_iterations = args.max_iterations_flag or args.max_iterations or 10

    # Handle case where project looks like a number (e.g., `iw 25`)
    project_input = args.project
    if project_input and project_input.isdigit() and args.max_iterations is None:
        max_iterations = int(project_input)
        project_input = None

    # MVP: hardcoded personal config
    config = Config(
        max_iterations=max_iterations,
        test_mode=args.test,
        verbose=args.verbose,
    )
    if args.poll_timeout:
        config.poll_timeout = args.poll_timeout

    # Select project
    project = select_project(
        input_name=project_input,
        base_dir=config.projects_dir,
        github_account=config.github_account,
    )
    if not project:
        sys.exit(1)

    project_path = config.projects_dir / project
    if not (project_path / ".git").is_dir():
        print(f"Error: {project_path} is not a git repository")
        sys.exit(1)

    repo = get_repo_url(project_path)
    if not repo:
        print(f"Error: Could not get repo URL for {project} at {project_path}")
        sys.exit(1)

    # Run
    result = run(
        project=project,
        repo=repo,
        project_path=project_path,
        config=config,
        use_test_launcher=config.test_mode,
    )

    print()
    print(result.message)

    if result.final_status == "complete":
        sys.exit(0)
    elif result.final_status == "max_iterations":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
