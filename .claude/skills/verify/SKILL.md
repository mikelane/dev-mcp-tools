---
name: verify
description: Run the full quality suite — lint, format check, type check, and tests across all packages with oracle coverage enforcement.
---

Run these checks in order. Stop on first failure and report it.

```bash
# Lint
uv run ruff check .

# Format check
uv run ruff format --check .

# Type check (oracle + shared; webhook not yet covered)
uv run mypy packages/oracle/src packages/shared/src

# Tests — all packages
uv run pytest packages/shared/tests packages/oracle/tests packages/webhook/tests

# Oracle coverage (95% minimum)
uv run --package project-oracle coverage run --branch -m pytest
uv run --package project-oracle coverage report --fail-under=95
```

Report pass/fail for each step. If all pass, say "All clear."
