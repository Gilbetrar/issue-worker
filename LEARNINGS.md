# Issue Worker — Learnings

Distilled patterns for future agents. Keep under 100 lines.

## Project Structure

- Python package at `src/issue_worker/`, installed via `uv tool install --editable .`
- Entry point: `issue_worker.cli:main` (registered as `issue-worker` and `issues`)
- Modules: cli, orchestrator, logging, signals, notifications, terminal, prompts, project
- Templates in `templates/`, defaults in `defaults/`
- Tests in `tests/` using pytest

## Dev Commands

```bash
uv run ruff check src/ tests/   # Lint (src + tests)
uv run pytest tests/ -v         # Tests (115 tests across 8 files)
uv add --dev <package>          # Add dev dependency
```

## CI

- GitHub Actions workflow at `.github/workflows/ci.yml`
- Runs on push/PR to main: ruff check + pytest
- Always run checks locally before committing too

## Conventions

- `from __future__ import annotations` at top of every module
- Dataclasses for config/data structures
- Type hints throughout

## Logging

- All orchestrator output goes through `logging.getLogger("issue_worker")`
- Console handler: INFO level, plain `%(message)s` format (mirrors old print behavior)
- File handler: DEBUG level with timestamps at `~/.local/state/issue-worker/logs/`
- Log rotation: keeps last 20 files via `prune_logs()`
- `issue-worker logs` subcommand to view recent logs

## Signal Statuses

Agents write these to SIGNAL.txt:
- `WORKING` — completed work, spawn next iteration
- `PAUSED` — needs human intervention (write HANDOFF.md too)
- `COMPLETE` — all issues done, stop the loop
- `NO_WORK` — nothing actionable found (not a crash, stops the loop)
- `CRASHED` — shell wrapper fallback when agent exits without writing a signal

Failure detection is signal-based (not timing-based). Missing signals, CRASHED, and unknown values count as failures. Valid signals always accepted regardless of speed.

## Concurrency Protection

- `_wait_for_agent_exit(prev_pid)` blocks before every `launcher()` call
- Waits up to `AGENT_EXIT_GRACE_PERIOD` (30s), then detaches — does NOT kill
- Detach is safe because the previous agent's signal was already processed; lingering processes are just orphaned MCP servers
- The PAUSED "leave" path blocks until the stuck agent exits (never advances)
- Dialog default is "Kill & Resume" (safer than "Leave Running")

## Repo Sync

- `_sync_main()` returns `SyncResult(success, message)` — orchestrator aborts if `success` is False
- All git commands check return codes; failures are surfaced, not ignored
- If changes were stashed and sync fails, `_try_restore_stash()` attempts best-effort restore
- Tests mock `subprocess.run` via `_mock_subprocess()` helper that dispatches by git subcommand

## Testing run()

- `_setup_run()` helper in test_orchestrator.py mocks ~10 deps; use keyword overrides per test
- The launcher mock must write `.issue-worker-started` with a fake PID for _wait_for_file to pass
- crash_count reset is inside each valid signal handler — NOT before unknown signal check
- For stuck-agent paths, assert whether the same iteration is retried or skipped; killing a blocked agent should not silently consume an iteration

## Review Follow-ups

- Pre-existing `HANDOFF.md` at startup blocks launch with a BLOCKED notification — orchestrator polls until operator deletes it (issue #14)
- The stuck-agent "kill" path should retry the interrupted work unit, not increment iteration and move on
- Consolidation launches its own Claude session; if that path stays asynchronous, it needs the same liveness/serialization guarantees as normal worker launches
- Editable installs work today, but prompt/default loading is repo-relative; treat wheel packaging as suspect until templates/defaults are explicitly packaged and tested

## Key Gotchas

- `terminal.py` has a pre-existing ruff E402 (import not at top) — don't fix unless asked
- The `_banner()` and `_sync_main()` helper functions get their own logger via `get_logger()`
- CLI tests must mock `Path.home()` for CI portability (runner doesn't have ~/AI/Projects/)
