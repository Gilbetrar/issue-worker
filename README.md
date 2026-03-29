# Issue Worker

CLI orchestrator for autonomous Claude Code sessions on GitHub issues.

## Install

```bash
uv tool install --editable .
```

## Usage

```bash
iw anki-package           # Run on a project (default 10 iterations)
iw slide-extractor 100    # 100 iterations max
iw                        # Interactive project picker
iw --test                 # Self-test mode (validates orchestration)
```
