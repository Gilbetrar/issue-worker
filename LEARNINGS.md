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
uv run pytest tests/ -v         # Tests (59 tests across 6 files)
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

## Key Gotchas

- `terminal.py` has a pre-existing ruff E402 (import not at top) — don't fix unless asked
- Original project files were untracked in initial commit — all now committed
- The `_banner()` and `_sync_main()` helper functions get their own logger via `get_logger()`
