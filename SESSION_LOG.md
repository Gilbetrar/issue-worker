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

---

## Agent Session - Issue #9 (follow-up fix)

**Worked on:** Issue #9 - Make repo sync safe before launching agents (stash ordering fix)

**What I did:**
- Found that a parallel agent had already implemented the main #9 changes (SyncResult, error checking, tests)
- Fixed a remaining bug: the stash/checkout order was wrong (checkout before stash), which fails when switching branches with a dirty working tree
- Added returncode check for `git status --porcelain`
- Committed and pushed the fix; CI passed

**What I learned:**
- Multiple agents can work concurrently on the same repo — always `git pull` and check recent commits before starting
- File modification race conditions occur with active hooks/linters — Write tool can fail repeatedly if external processes modify the file between Read and Write
- The linter auto-deduplicates class definitions and may rename fields

**Mistakes made:**
- Spent time trying to write the entire file multiple times due to file modification races with linter/hooks

---

## Agent Session - Issues #10 and #11

**Worked on:** Issue #10 (already done by previous iteration), Issue #11 - Document the real operating model

**What I learned:**
- Previous iteration (3) committed issue #10 work but didn't close the issue or write session log — always complete all post-work steps
- Issue #10 was auto-closed by GitHub when the commit with "Closes #10" was pushed, same for #11
- Git status snapshot at conversation start can be stale — always verify with live `git status`

**Codebase facts discovered:**
- README was only 19 lines with incorrect command name (`iw` not registered; actual commands are `issue-worker` and `issues`)
- Config defaults are hardcoded in `orchestrator.Config` dataclass, not configurable via CLI
- Consolidation runs at iteration 1 and every 10th, triggered when SESSION_LOG.md exceeds 200 lines

**Mistakes made:**
- None

---

## Agent Session - Issue #12

**Worked on:** Issue #12 - Expand test coverage to the run loop, CLI, and prelaunch gating

**What I learned:**
- Testing `run()` requires mocking ~10 dependencies (sync, time, signals, launcher, notifications, prompts, process liveness)
- A `_setup_run()` helper with keyword overrides keeps individual tests focused and readable
- `time.time` mock needs careful step size: 50s for normal flow (above min_runtime=3), 0.5s for crash tests (below min_runtime)
- The HANDOFF.md override test needs the launcher to create the file (clean slate deletes it first), and time.sleep to delete it
- CLI tests need `Path.home()` mocked for CI portability (runner lacks ~/AI/Projects/)

**Codebase facts discovered:**
- Test count went from 75 to 112 (37 new tests: 12 run loop + 8 CLI + 17 terminal from prior iteration)
- CLI exit codes: 0 = complete/no_work, 1 = max_iterations or validation failure, 2 = error/aborted
- The orchestrator has 3 separate abort paths: sync failure (error), launch/start failures (aborted), crash guard (aborted)

**Mistakes made:**
- None — previous iterations already committed #10 and #11, so I correctly identified the next available issue

---

## Agent Session - Issue #13

**Worked on:** Issue #13 - Make agent signal handling explicit and failure-safe

**What I learned:**
- The timing-based rapid-exit guard was a heuristic for crash detection that became unnecessary once signals were made explicit
- Shell wrapper fallback (CRASHED) is needed for fast failure detection — without it the orchestrator would poll until timeout
- crash_count reset must happen inside each valid signal handler, NOT before unknown signal detection — otherwise unknown signals reset crash_count to 0 on every iteration and the abort threshold is never reached (caused an infinite loop in tests)
- Removing `min_runtime` from Config also simplifies test setup (no more time_step tuning)

**Codebase facts discovered:**
- Test count: 115 (3 new tests for CRASHED, unknown signal, and quick-valid-exit)
- Signal states: WORKING, PAUSED, COMPLETE, NO_WORK are agent-written; CRASHED is shell-wrapper-written
- The `time.time` mock is no longer needed since timing-based crash detection was removed

**Mistakes made:**
- Initially placed `crash_count = 0` before unknown signal check, which made the unknown signal handler unable to accumulate crashes (reset to 0 every loop). Fixed by moving reset into each valid handler

---

## Agent Session - Issue #14

**Worked on:** Issue #14 - Make paused handoffs restart-safe instead of deleting unresolved HANDOFF.md

**What I did:**
- Added pre-loop HANDOFF.md check in `run()` that blocks with a BLOCKED notification until the operator resolves (deletes) the file
- Added 6 tests: blocks until resolved, never deleted by orchestrator, no-handoff proceeds normally, sends notification, resolved allows full loop, same-run cleanup still works
- Updated LEARNINGS.md and README.md with restart-safe handoff semantics
- Also committed previously lingering docs changes from issue #13 review follow-ups

**What I learned:**
- When mocking `time.sleep` for pre-loop blocking behavior, the same mock gets called during the iteration loop too — need to scope assertions to the right phase
- The per-iteration clean-slate HANDOFF.md deletion (line 150) is harmless for same-run cases because the PAUSED handler already waited for resolution

**Codebase facts discovered:**
- The clean-slate section (lines 149-151) deletes SIGNAL.txt, HANDOFF.md, and .issue-worker-started at the start of every iteration
- `_setup_run()` helper already mocks notifications.notify, so handoff tests that need to track notify calls must re-monkeypatch it

**Mistakes made:**
- First test run: `test_preexisting_handoff_never_deleted_by_orchestrator` failed because the sleep mock's unlink call ran during post-signal sleep (line 270) after the file was already gone. Fixed by scoping the file-existence check to the first N sleep calls

---

## Agent Session - Issue #15

**Worked on:** Issue #15 - Retry the same iteration after killing a stuck agent

**What I did:**
- Removed `iteration += 1` from the stuck-agent kill path in orchestrator.py (line 351)
- Updated log message to say "Retrying iteration N..." instead of "Resuming orchestration..."
- Added `TestStuckAgentRetry` test class with 4 tests:
  - `test_kill_retries_same_iteration` — verifies kill path retries, not skips
  - `test_kill_does_not_consume_iteration_budget` — alternating stuck/success proves budget accounting
  - `test_leave_does_not_advance_iteration` — leave path also retries
  - `test_kill_prevents_duplicate_agents` — _wait_for_agent_exit called before retry launch

**What I learned:**
- The "leave" path already correctly retried without incrementing (had `continue` without `iteration += 1`)
- Testing stuck-agent flows requires careful coordination of `_is_process_alive` mock state across multiple checks (timeout block + PAUSED block)

**Codebase facts discovered:**
- `_is_process_alive` is called in two places for stuck agents: once in the timeout block (line 251) and once in the PAUSED handler (line 334)
- `prev_pid` is set to `None` after kill but preserved after "leave" (leave path uses `_wait_for_agent_exit` instead)

**Mistakes made:**
- None — clean implementation on first attempt
