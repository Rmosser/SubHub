# Git Workflow Standard

## Branch model

- `main`: releasable default branch.
- Topic branches (`codex/<topic>`, `claude/<topic>`): one change each, merged through a PR.
- Woodpecker runs `ci/woodpecker/pr/smoke` for every PR. Branch pushes run CI only for `main` and `codex/**`; a `claude/*` branch is checked through its PR.

## Commit convention

Use a Conventional Commit prefix appropriate to the change:

- `feat`
- `fix`
- `docs`
- `refactor`
- `test`
- `chore`

## Pull request flow

1. Branch from the current `main`.
2. Implement the change with the relevant context from `docs/index.md`.
3. Run repository-evidenced checks from `docs/quality.md`.
4. Push the branch and open/update a PR.
5. Use the current PR head and its real CI/check results as the validation truth.
6. Address actionable review feedback and failing checks before merge.

There is no repository-specific Active Plan, review-round, repair-loop, or fixed ready-to-merge state machine.
