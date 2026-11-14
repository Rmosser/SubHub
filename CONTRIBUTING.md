# Contributing Guide

Start with `docs/index.md`. Use `docs/quality.md` for repository-evidenced validation commands.

## Branches and commits

- Branch from `main` into a topic branch such as `codex/<topic>` or `claude/<topic>`.
- Keep commits scoped to one coherent change.
- Use Conventional Commit prefixes: `feat|fix|docs|refactor|test|chore`.

## Context and documentation

- Load only the context documents relevant to the change.
- Keep code, tests, and affected documentation synchronized in the same change when practical.
- `docs/doc-sync-rules.json` provides executable path-to-document feedback.
- `docs/plans/template.md` is optional for complex work; there is no mandatory Active Plan.

## Before opening or updating a PR

Run the smallest relevant set from `docs/quality.md`. At minimum for documentation-sensitive changes:

```bash
./.venv/bin/python scripts/run_docs_consistency_audit.py
```

For Python behavior, frontend behavior, or deployment changes, add the corresponding tests/lint/build/runtime checks from `docs/quality.md`.

## Pull requests

- Describe the behavior and scope, not a Harness state.
- Record the exact validation commands actually run.
- If checks fail or remain pending, fix or report the concrete blocker instead of declaring the PR ready.
- Resolve actionable review feedback normally; the repository does not define a separate review-round state machine or merge formula.
