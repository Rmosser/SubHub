# Quality

Use only commands that are present in the repository or its current CI configuration. Run the smallest relevant set first, then broaden when the change warrants it.

## Python environment

CI creates the development environment with:

```bash
python scripts/ci_pip_cache.py
```

The README's local application setup uses `python3 -m venv .venv`, activates it, and installs `requirements.txt`.

The Woodpecker `smoke` workflow runs documentation checks, then Python
dependency preparation (`python-setup`), which installs the job-local `.venv`
once and runs Ruff. Three test steps then start in parallel at the same
execution depth: `fast-tests`, `api-tests` and frontend `node-24`. Keeping them
at the same depth avoids the executor's stage barrier delaying Python tests
until frontend checks finish. The two Python containers read the prepared
environment: `api-tests` covers `api and not slow`, and `fast-tests` covers
all remaining cases in the previous fast-suite union. The partitions
preserve the exact union of the former unit, repo, service-not-slow, smoke and
API-not-slow commands, including slow tests selected by unit/repo/smoke. Tests
with overlapping markers run once instead of once per matching command.
Each partition reports its 20 slowest durations and writes separate pytest
cache and JUnit files under `.ci/pytest-cache/` and `.ci/test-results/`.

Main pushes and the `subhub-daily` cron additionally run `full-tests` after
both Python partitions and the frontend pass, reusing the job-local `.venv`;
the full suite and its selection are unchanged. CI builds the frontend under
`.ci/frontend-dist` so it cannot clear files while the fast API tests read them.
After all branches pass, `full-tests` copies that build to the standard static
asset location before testing the complete application. Each workflow has its own workspace.
CI uses `ci/requirements-linux-py313.lock`: exact transitive versions and SHA-256
hashes, bound to both input requirements files and the pinned Linux/amd64 Python
3.13.14 / pip 26.1.2 image. The existing host snapshot endpoint at
`http://172.18.0.1:17894/v1/uv/` transports a signed wheelhouse; it is not a PyPI
index. The job verifies its signature, identity, checksum and archive limits,
creates a fresh `.venv`, and installs offline with `--no-index --require-hashes`.
It does not upgrade pip, restore an old venv or mount a host cache directory.

A missing/invalid snapshot or failed offline install recreates `.venv` and
installs the same locked public PyPI wheels through
`http://172.18.0.1:17896` (the host's pinned DMIT EB Fast IPv4 route). If that
fails, it recreates `.venv` and retries direct PyPI. A failed direct install
fails CI. The cache restore has a 30-second total deadline; offline installation
has 60 seconds, and proxy/direct installation has 120/180 seconds with socket
timeout 10 seconds and one retry. These cache settings do not alter test selection or the
required `ci/woodpecker/pr/smoke` context. `CI_CACHE_MODE=off` forces the cold path.
A `CI_CACHE_PHASE` JSON line records hit/fallback, package preparation time,
archive bytes and whether installation was offline.

Run `python scripts/ci_pip_cache.py --check-lock` to detect stale input bindings.
After changing either input requirements file, resolve inside the workflow's
exact Python image (not a macOS venv), then regenerate and commit the CI lock:

```bash
mkdir -p .ci
python -m pip install --dry-run --ignore-installed --only-binary=:all: \
  --index-url https://pypi.org/simple -r requirements-dev.txt --report .ci/pip-report.json
python scripts/ci_pip_cache.py --write-lock .ci/pip-report.json
python scripts/ci_pip_cache.py --check-lock
```

The host timer prewarms trusted `main` when the CI queue is empty; a new PR lock
may initially use the cold path. Ordinary jobs cannot publish cache contents.
The snapshot consumer is vendored from the control-plane repository's
`ci-cache/pip_snapshot.py`; update producer and consumer together when changing
the protocol. Local development continues to use `requirements-dev.txt`.

## Documentation consistency

```bash
./.venv/bin/python scripts/run_docs_consistency_audit.py
```

CI's `docs-checks` step runs the same script with the image's `python`.

The audit checks current documentation structure/links/paths and direct path-to-document synchronization from `docs/doc-sync-rules.json`. It does not require a plan document.

## Lint

```bash
./.venv/bin/python -m ruff check .
```

Frontend lint:

```bash
npm run lint --prefix frontend
```

A fix command exists in `frontend/package.json`:

```bash
npm run lint:fix --prefix frontend
```

## Python tests

Whole pytest suite:

```bash
./.venv/bin/python -m pytest
```

Resident-runtime recovery drill (local temporary fixtures only):

```bash
./.venv/bin/python -m pytest tests/test_runtime_recovery.py -q
```

This drill performs semantic SQLite readback on a separate target, runs a
child-process `SIGKILL` after atomic restore promotion, and exercises fake Git,
fake HTTPS alert transport, durable UNKNOWN receipts, and task-exit watchdog
paths. Startup retry is bounded by a global deadline and leaves unprocessed
receipts durable for the resident watchdog; it does not contact a production
Git remote or alert sink.

Repository-provided layered entry points:

```bash
bash scripts/test_unit.sh
bash scripts/test_repo.sh
./.venv/bin/python -m pytest -m "service and not slow"
bash scripts/test_smoke.sh
bash scripts/test_api.sh -m "not slow"
bash scripts/test_changed_fast.sh
bash scripts/test_full.sh
```

## Client UI replica

`design/client-ui-replica/` holds generated inventory and replica data. After changing its generators, `tokens/`, or `replica/build_data.py`, regenerate and check (no Chrome or local captures needed):

```bash
./.venv/bin/python design/client-ui-replica/replica/build_data.py
./.venv/bin/python -m pytest tests/test_client_ui_replica.py -q
```

Pixel comparison needs the local-only reference captures in `design/client-ui-replica/screens/` and Google Chrome:

```bash
./.venv/bin/python design/client-ui-replica/replica/compare.py shadowrocket-config-edit
```

## Frontend

The frontend has tracked runtime-contract tests (including API boundary and status-parser regressions). The Woodpecker `node-24` step runs them before the build:

```bash
npm ci --prefix frontend
npm run test:unit --prefix frontend
npm run build --prefix frontend
npm run lint --prefix frontend
```

`frontend/package.json` defines `build` as `tsc -b && vite build`, so the verified build includes TypeScript compilation.

Visible UI changes also need a real browser readback: widths, themes, frost fallback, keyboard paths and console checks are listed under Verification in `DESIGN.md`, and per-page interactions in `docs/operations/ui-smoke-test-task.md`. Tests, build and lint do not replace it.

The CI install probes the read-only npm proxy at `http://172.18.0.1:17893/-/ping`
for at most five seconds. A healthy proxy is used with registry-host replacement;
an unavailable proxy falls back to `https://registry.npmjs.org/`. The cached
install uses bounded fetch retries/timeouts; a failure after a successful probe
retries the same install once against the public registry. A failed public
install still fails CI. Both paths keep
`npm ci`, its audit, and its lifecycle scripts. Jobs do not mount host cache storage.

## Build, deploy, and runtime readback

Repository build helper (默认只构建并保留 LPK，不切盒子或安装):

```bash
bash scripts/deploy_to_lazycat.sh
```

真实安装只允许使用已审核的盒子、显式部署与确认参数；安装后脚本等新容器就绪再做版本/digest/health readback，通过时打印 `verified …`，失败一律报 `ERROR` 并非零退出：

```bash
bash scripts/deploy_to_lazycat.sh --deploy --box <box-name> --confirm
```

The repository also documents the LazyCat build/install path:

```bash
lzc-cli project build
lzc-cli app install .pkgout/*.lpk --apk n
```

Runtime status readback:

```bash
lzc-cli app status cloud.lazycat.subhub
```

`/healthz` exposes instance liveness and initialization state without user data. Authenticated `/api/status` and `/diagnostics` expose the current user's runtime details; the operations runbook checks `last_refresh_at`, `last_error`, `accounts_status`, and `pending_domain_count_by_account` there.

No standalone runtime log CLI command is currently evidenced in the repository; use `docs/operations/troubleshooting.md` and the documented runtime readbacks rather than inventing one.

## Security/release feedback

```bash
scripts/security_preflight.sh
```

Release-specific behavioral checks are in `docs/governance/release-checklist.md`.

## Unknown / not independently defined

- Formatter: no standalone formatter command is evidenced.
- Standalone typecheck: none evidenced; TypeScript checking is part of `npm run build --prefix frontend`.
- Runtime log CLI: unknown; do not guess a command.
