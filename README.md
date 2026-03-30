# Issue Worker

CLI orchestrator for autonomous Claude Code sessions on GitHub issues.

Launches Claude Code agents in macOS Terminal tabs, one at a time, to work through open GitHub issues. Each agent picks an issue, implements changes, commits, pushes, and signals the orchestrator when done. The orchestrator then spawns the next iteration.

## Prerequisites

**Platform:** macOS only (uses Terminal.app and `osascript` for tab management).

**Required tools:**

| Tool | Purpose | Install |
|------|---------|---------|
| [Claude Code](https://claude.ai/code) | AI agent that does the work | `npm install -g @anthropic-ai/claude-code` |
| [GitHub CLI](https://cli.github.com/) | Issue listing, repo operations | `brew install gh` |
| [uv](https://docs.astral.sh/uv/) | Python package manager | `brew install uv` |
| Python 3.12+ | Runtime | Via uv or system |

**Optional:**

| Tool | Purpose |
|------|---------|
| [fzf](https://github.com/junegunn/fzf) | Interactive project picker (falls back to numbered menu) |

**Environment assumptions:**

- Projects live in `~/AI/Projects/` (hardcoded default)
- GitHub account defaults to `Gilbetrar` (hardcoded)
- Agents commit directly to `main` — no feature branches
- `gh auth` must be configured for the target GitHub account

## Install

```bash
uv tool install --editable .
```

This registers two equivalent commands: `issue-worker` and `issues`.

## Usage

```bash
issue-worker anki-renderer       # Run on a project (default 10 iterations)
issue-worker slide-extractor 25  # Up to 25 iterations
issue-worker                     # Interactive project picker (uses fzf if available)
issue-worker 50                  # Picker with 50 max iterations
issue-worker --test              # Self-test mode (3 iterations, no real agents)
issue-worker logs                # View recent log files
issue-worker logs -n 50          # Show last 50 lines of latest log
issue-worker --version           # Print version
```

Project names are fuzzy-matched against local `~/AI/Projects/` directories. If a project exists on GitHub but not locally, the orchestrator clones it automatically.

## How Orchestration Works

1. **Sync** — Checks out `main`, stashes dirty changes, fetches and rebases from origin
2. **Consolidation** — On iteration 1 (and every 10th), optionally distills `SESSION_LOG.md` into `LEARNINGS.md` if the log is large (>200 lines)
3. **Launch** — Opens a new Terminal tab running Claude Code with a templated prompt (`templates/prompt.md`)
4. **Wait** — Polls for a `SIGNAL.txt` file in the project directory (default timeout: 30 minutes)
5. **Handle signal** — Decides what to do next based on the agent's signal
6. **Repeat** — Increments iteration and loops back to step 3

Each agent runs `claude` with `--dangerously-skip-permissions` using settings from `defaults/settings.json` and MCP config from `defaults/mcp.json`.

### Failure detection

Crash detection is signal-based. An agent fails if it exits without writing a signal file (the shell wrapper writes `CRASHED`) or writes an unknown signal value. Valid signals (`WORKING`, `PAUSED`, `COMPLETE`, `NO_WORK`) are always accepted regardless of how quickly the agent ran. After 3 consecutive failures, the orchestrator aborts and sends a macOS notification.

### Duplicate prevention

The orchestrator tracks the PID of each agent and waits up to 30 seconds for the previous process to exit before launching the next one. If the process is still alive after that (typically orphaned MCP servers lingering after Claude finishes), the orchestrator detaches and proceeds — it does not kill the process.

Both consolidation and normal worker agents use the same lifecycle controls: PID tracking via started files, startup verification, and process-exit gating. Consolidation must fully exit before the main worker launches — the orchestrator never allows overlapping Claude sessions.

## Signals and Handoff

Agents communicate with the orchestrator by writing `SIGNAL.txt` in the project root:

| Signal | Meaning | Orchestrator action |
|--------|---------|-------------------|
| `WORKING` | Completed work, more to do | Spawn next iteration |
| `PAUSED` | Needs human intervention | Notify and wait for `HANDOFF.md` deletion |
| `COMPLETE` | All issues done | Stop the loop (exit 0) |
| `NO_WORK` | No actionable issues found | Stop the loop (exit 0) |
| `CRASHED` | Agent exited without writing a signal (shell wrapper fallback) | Retry, abort after max crashes |

Signal files are written atomically (write `.tmp`, then rename). If an agent exits without writing a signal, the shell wrapper writes `CRASHED` so the orchestrator detects the failure immediately rather than waiting for a timeout. Unknown signal values are also treated as failures.

### PAUSED / Handoff flow

When an agent can't complete a step (e.g., needs manual approval):

1. Agent writes `HANDOFF.md` with instructions for the human
2. Agent writes `SIGNAL.txt` with status `PAUSED`
3. Orchestrator sends a macOS notification and waits
4. Human runs `cd <project> && claude` to complete the handoff
5. Human deletes `HANDOFF.md`
6. Orchestrator detects deletion and resumes

### Restart-safe handoffs

If the orchestrator restarts while a `HANDOFF.md` exists from a prior run, it **blocks** before entering the launch loop. No agents are spawned until the operator resolves (deletes) the file. A `BLOCKED` notification is sent with instructions.

### Stuck agent detection

If the poll timeout expires and the agent process is still alive (likely stuck on a permission prompt), the orchestrator sends a notification and offers to kill the process or wait.

## Logs and Troubleshooting

Logs are stored at `~/.local/state/issue-worker/logs/` with automatic rotation (keeps last 20 files).

- **Console output**: INFO level, plain messages
- **Log files**: DEBUG level with timestamps

```bash
issue-worker logs          # List log files and tail the latest
issue-worker logs -n 100   # Show last 100 lines
```

### Learnings files (per-project)

| File | Purpose | Audience |
|------|---------|----------|
| `LEARNINGS.md` | Distilled patterns (~100 lines max) | Every agent reads this first |
| `SESSION_LOG.md` | Raw session history | Reference only, not read by agents |

## Current Limitations

- **macOS only** — Terminal.app and `osascript` are required for tab management
- **Hardcoded defaults** — Projects directory (`~/AI/Projects/`) and GitHub account (`Gilbetrar`) are set in code, not configurable via CLI flags or config file
- **Direct-to-main** — No branch/PR workflow; agents commit directly to `main`
- **Single project** — Runs one project at a time; no multi-project scheduling

## Development

```bash
# Install dev dependencies
uv sync --group dev

# Lint
uv run ruff check src/ tests/

# Test (116 tests)
uv run pytest tests/ -v

# Self-test mode (validates orchestration without real agents)
issue-worker --test
```

CI runs on every push/PR to `main` via GitHub Actions (`.github/workflows/ci.yml`): ruff check + pytest.
