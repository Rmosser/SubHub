# AGENTS.md

SubHub is a LazyCat-hosted tool that detects network connectivity, privacy leaks, and unauthorized connections, then routes or blocks them. Keep changes scoped to the repository's product, runtime, deployment, and quality contracts.

## Start here

1. Read `docs/index.md` and follow the Context Map for the task.
2. Read `docs/quality.md` before choosing validation commands.
3. Load only the product, architecture, API, deployment, operations, or historical documents needed for the current change.

## Repository-wide invariants

- LazyCat login protection stays enabled by default. Anonymous access is limited to `/healthz`, `/sub/*`, and `/rules/*`.
- User configuration is isolated by `lazycat_user_id`.
- Distributable packages must not contain real `SUB_TOKEN` or `DATA_ENCRYPTION_KEY` values; `scripts/security_preflight.sh` checks the manifest and the built LPK.
- Local Python and tests use `./.venv`.
- HTTP surface changes must keep `docs/api/http-api.md` synchronized.
- Subscription output semantic changes must keep `docs/api/subscription-output-contract.md` synchronized.

## Minimum feedback

- Documentation consistency: `./.venv/bin/python scripts/run_docs_consistency_audit.py`
- Fast smoke: `bash scripts/test_smoke.sh`
- Frontend changes: `npm run lint --prefix frontend`, `npm run test:unit --prefix frontend`, `npm run build --prefix frontend`; visible UI changes also need the browser readback in `DESIGN.md` (Verification), since tests and builds do not replace it.
- Full command inventory and runtime readback: `docs/quality.md`

## Planning

`docs/plans/template.md` is an optional aid for complex work or Codex Plan mode. It is not a required artifact and there is no Active Plan gate.
