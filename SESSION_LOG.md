# Issue Worker — Session Log

Raw session history. Agents: append here, read LEARNINGS.md instead.

---

## Agent Session - Issue #1

**Worked on:** Issue #1 - Add logging system

**What I did:**
- Created `src/issue_worker/logging.py` with setup_logging(), prune_logs(), list_log_files(), get_logger()
- Replaced all print() calls in orchestrator.py with structured logger calls (info, debug, warning, error)
- Added `logs` subcommand to cli.py that lists log files and tails the latest
- Added `verbose` flag to Config dataclass (controls console DEBUG output)
- Created `tests/test_logging.py` with 7 tests (all passing)
- Added ruff and pytest as dev dependencies
- Committed all project source files (were previously untracked)

**What I learned:**
- No CI workflows exist yet — checks must be run locally
- All source files were untracked after the initial commit (only .gitignore and LICENSE were committed)
- ruff is configured in pyproject.toml with target-version py312

**Codebase facts discovered:**
- terminal.py has a pre-existing E402 lint violation
- Project uses hatchling as build backend
- The pyproject.toml `[tool.ruff]` section only had target-version configured

**Mistakes made:**
- None significant

---

## Agent Session - Issue #2

**Worked on:** Issue #2 - Add learnings consolidation support

**What I did:**
- Added `_should_consolidate()` and `_run_consolidation()` to orchestrator.py
- Added `CONSOLIDATION_TIMEOUT` (300s) and `CONSOLIDATION_LINE_THRESHOLD` (200) constants
- Consolidation triggers at iteration 1 and every 10th iteration (1, 10, 20, 30...)
- Consolidation runs sequentially before the main agent (no concurrent writes)
- Failure is non-fatal — logs warning and continues to main agent
- Added 12 tests in tests/test_orchestrator.py covering: iteration logic, threshold checks, success, launch failure, timeout, missing template, signal cleanup, single-attempt guarantee
- All 22 tests pass (7 logging + 15 consolidation... actually 22 total)

**What I learned:**
- The consolidation template and `render_consolidation_prompt()` already existed — only orchestrator logic needed
- Pre-existing lint issues: E402 in terminal.py, F401 in test_logging.py — don't fix unless asked
- Monkeypatching module-level constants works well for controlling timeouts in tests

**Codebase facts discovered:**
- Launcher pattern: terminal.open_terminal_tab / open_terminal_tab_test are interchangeable callables (cmd, title) -> bool
- Signal polling pattern: write .tmp then rename for atomicity

**Mistakes made:**
- None

---

## Agent Session - Issue #5

**Worked on:** Issue #5 - Add pytest test suite

**What I did:**
- Created tests/test_signals.py (12 tests): write, read, wait, clear, roundtrip, dataclass str
- Created tests/test_prompts.py (5 tests): variable substitution, no unreplaced placeholders, missing template
- Created tests/test_project.py (10 tests): local project discovery, repo URL parsing (SSH, HTTPS, host alias)
- Created tests/test_notifications.py (5 tests): AppleScript string escaping
- Created tests/conftest.py (shared fixtures placeholder)
- Created .github/workflows/ci.yml: runs ruff check + pytest on push/PR to main
- Added [tool.pytest.ini_options] to pyproject.toml
- All 57 tests pass, ruff clean, CI green on first push

**What I learned:**
- A pre-commit hook auto-stages and commits new files — watch for double commits
- CI workflow uses astral-sh/setup-uv@v4 for uv installation in GitHub Actions
- get_repo_url tests work well with real git repos in tmp_path (no mocking needed)

**Codebase facts discovered:**
- pytest and ruff were already dev dependencies from issue #1 work
- 57 total tests across 6 test files now

**Mistakes made:**
- None

---

## Agent Session - Iteration 3

**Worked on:** Issue #7 - Remove old bash issue-worker from agent-system repo (+ housekeeping)

**What I did:**
- Verified all 59 tests pass and ruff is clean
- Confirmed CI green for both issue #5 commits (327234b, 0e8c652)
- Closed issues #1, #2, #5, and #7 on GitHub
- Updated LEARNINGS.md: added CI section, updated dev commands
- Deleted ~/AI/Agents/scripts/issue-worker/ (old bash version)
- Added issue-worker to AGENTS.md projects table in agent-system repo
- Verified run_claude alias and all acceptance criteria for issue #7
- Committed and pushed to agent-system repo (89f31ac)

**What I learned:**
- Previous agents may leave issues open even after completing the work — check and close them
- The agent-system repo (~/AI/Agents) has many untracked/modified files — only stage and commit the specific files relevant to your change
- AGENTS.md is symlinked from ~/CLAUDE.md — changes there affect all projects

**Mistakes made:**
- None

---

## Agent Session - Iteration 5

**Worked on:** Survey — no open issues remaining

**What I did:**
- Read LEARNINGS.md for context
- Checked all open issues: none found
- Verified closed issues #3, #4, #6 were intentionally cut/deferred (comments confirm)
- All 7 issues are legitimately closed
- Signaled COMPLETE

**What I learned:**
- Issues #3 (profiles), #4 (init), #6 (tmux) were cut by the user — not missing implementations
- All issue-worker work is done for now

---

## Agent Session - Issue #8

**Worked on:** Issue #8 - Enforce single-agent execution — prevent duplicate concurrent agents

**What I did:**
- Implemented all 4 sub-fixes (A-D) from the issue:
  - A: Added `_wait_for_agent_exit()` gate before every `launcher()` call, tracked `prev_pid` across iterations
  - B: Fixed PAUSED "leave" path to block until stuck agent exits (was advancing and spawning duplicates)
  - C: Added `NO_WORK` signal status — agents can signal "nothing to do" without triggering crash detection
  - D: Changed stuck-agent dialog default from "Leave Running" to "Kill & Resume"
- Added 4 tests for `_wait_for_agent_exit` function
- Fixed pre-existing CI failure: `test_complete_result_exits_zero` didn't mock the project path, failing on GitHub runners

**What I learned:**
- `_is_process_alive` is called both in the guard clause and the while loop — test counts must account for both
- The `Closes #N` syntax in commit messages auto-closes GitHub issues on push
- CLI tests that reference filesystem paths need Path.home() mocked for CI portability

**Codebase facts discovered:**
- `prev_pid` tracking was completely absent — no mechanism to prevent duplicate agents
- The PAUSED "leave" path fell through to `iteration += 1; continue`, spawning duplicates
- Signal statuses are just strings (no enum) — adding new ones requires updating the comment, orchestrator dispatch, and prompt template

**Mistakes made:**
- Initial test expected 3 sleep calls but `_wait_for_agent_exit` calls `_is_process_alive` in guard clause too (consumed 1 of 3 alive counts) — fixed to expect 2

---

## Agent Session - Issue #9

**Worked on:** Issue #9 - Make repo sync safe before launching agents

**What I did:**
- Added `SyncResult` dataclass (success: bool, message: str) returned by `_sync_main()`
- Refactored `_sync_main()` to check return codes of all git commands (branch detection, checkout, stash, fetch, pull, stash pop)
- Added `_try_restore_stash()` helper — best-effort stash restore on sync failure paths
- Updated `run()` to abort with `RunResult(final_status="error")` when sync fails
- Added 11 tests covering: clean repo, branch checkout, all failure paths (branch detection, checkout, stash, fetch, pull, timeout, stash pop conflict), and stash restore on failure

**What I learned:**
- There were stale duplicate `SyncResult` class definitions already in orchestrator.py from prior incomplete work — had to clean those up
- The `_mock_subprocess` helper pattern (dispatch based on git subcommand) works well for testing git command sequences
- Using callable handlers in the mock dispatch allows stateful tests (e.g., stash succeeds first call, fails on pop)

**Codebase facts discovered:**
- Test count went from 64 to 75 with the 11 new sync tests
- The `Closes #N` keyword in commit messages auto-closes GitHub issues on push

---

## Agent Session - Issue #10

**Worked on:** Issue #10 - Prefer opening new agent sessions in Terminal tabs, not windows

**What I did:**
- Refactored `terminal.py` to extract `_build_applescript()`, `_write_temp_script()`, and `_invoke_osascript()` as testable units
- Modified the AppleScript to use System Events `keystroke "t" using command down` (Cmd+T) when Terminal already has a window open, falling back to `do script` (new window) when no windows exist
- Added 17 tests in `tests/test_terminal.py` covering AppleScript content, subprocess invocation, retry logic, and integration

**What I learned:**
- Terminal.app has no native AppleScript command to create a tab — the only reliable approaches use System Events (keystroke or menu click)
- `do script cmd in front window` runs in the *selected tab* of that window, which is the newly-created tab after Cmd+T
- The original code avoided System Events for the initial launch but that's unavoidable for tab creation

**Codebase facts discovered:**
- Test count went from 75 to 92 with the 17 new terminal tests
- This project is Python-only (no package.json); checks are `uv run ruff check` and `uv run pytest`
