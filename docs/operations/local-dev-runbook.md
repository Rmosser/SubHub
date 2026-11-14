# Local Dev Runbook (Frequent Startup Issues)

This doc records the recurring reasons why the local service "won't start" or the browser shows
`ERR_CONNECTION_REFUSED`, plus the fastest verification/repair steps.

Repo: `SubHub`  
Service: FastAPI + Uvicorn  
Default local port: `8080`  
Local log: `local-dev.log`  
Local storage root: `./var` (SQLite at `./var/data/app.db`)

`scripts/run_local.sh`/`scripts/stop_local.sh` 只接受安全的 instance slug 与有效端口，
并在停止前核验记录的启动时间和命令身份；不要手工拼接日志或 pid 路径。

## 0. Node 24 Baseline

The repo pins Node 24 in [`.nvmrc`](../../.nvmrc).
If you use `nvm`, run `nvm install 24 && nvm use` before any `npm` command.
CI's Woodpecker `node-24` step uses the same major, and `scripts/run_local.sh` refuses any other major.

With another Node installed (for example Node 25), run the two servers directly instead of `run_local.sh`:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --log-level info
npm run dev --prefix frontend -- --port 5173 --strictPort
```

The Vite dev server serves `/manage/` and proxies `/api`, `/sub` and `/static` to port 8080. If `.env` sets `POLICY_BACKUP_ENABLED=true` with an HTTPS repository but no `POLICY_BACKUP_GITHUB_TOKEN`, the API refuses to start; prefix the command with `POLICY_BACKUP_ENABLED=false` for local work instead of editing `.env`.

## 0. Fast Verification Checklist (30s)

1. Is anything listening on `8080`?

```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

2. Can we reach the portal?

```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/
```

3. If refused, read the last 100 log lines:

```bash
tail -n 100 local-dev.log
```

## 1. Root Cause: `.env` Is Not Shell-Safe (Most Common)

### Symptom

You run:

```bash
set -a && source .env && set +a
```

and see:

```
bash: Relay: command not found
```

### Why It Happens

`.env` is being *sourced by bash*. Lines like this are **not** valid shell when values contain spaces:

```
APP_NAME=LZC Relay Subscription
```

Bash interprets it as `APP_NAME=LZC` and tries to execute `Relay`.

### Fix

Quote values with spaces:

```
APP_NAME="LZC Relay Subscription"
```

Recommendation: keep `.env` compatible with `source` (quote anything with spaces or `#`).

## 2. Root Cause: `--reload` + `nohup` Makes Process State Confusing

### Symptom

`local-dev.log` contains:

```
Uvicorn running on http://127.0.0.1:8080
Application startup complete.
```

But:

```bash
curl http://127.0.0.1:8080/
```

returns refused, and `lsof` shows nothing.

### Why It Happens

`uvicorn --reload` spawns a reloader + server subprocess. Under `nohup` (and when killed/restarted
frequently), you can end up with:

- server subprocess died, reloader still present (or vice versa)
- `pkill` matches only one process and leaves the other behind
- logs look "healthy" but the listener is already gone

### Fix / Recommendation

For **stable background** local run, do **not** use `--reload`.

For dev iteration with reload, run it in **foreground**:

```bash
set -a && source .env && set +a
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload --log-level debug
```

## 3. Root Cause: Port Conflict (8080 Already Used)

### Symptom

Uvicorn fails to bind, or the page you open is actually served by another app.

### Fix

```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

- Kill the occupying process, or
- Start this app on a different port (example `8099`) and adjust `APP_BASE_URL` if you hardcode it.

## 4. Root Cause: `APP_BASE_URL` Mismatch Breaks Import Links

### Symptom

The portal opens, but the generated links point to `127.0.0.1:8000` while you run on `8080`.

### Why It Happens

If `APP_BASE_URL` is set (and not the built-in default), the server uses it as the canonical base URL.

Current behavior includes a safety fallback:

- If `APP_BASE_URL` points to local host but the port does not match the current request
  (for example `8000` vs running service on `8080`), the app auto-falls back to request base URL
  and shows a mismatch warning in portal/admin pages.

### Fix

For local dev, recommend leaving it empty:

```
APP_BASE_URL=
```

so the app uses `request.base_url` (which matches `http://127.0.0.1:8080`).

## 5. Root Cause: Storage Root / Encryption Key Issues (Looks Like "Data Lost")

### Symptom A: "Saved data disappeared after restart"

Common causes:

- The service started with a different `STORAGE_ROOT` (writes to a different `./var`).
- First-time setup has not been initialized yet.
- You changed `instance_secrets.json`中的密钥，旧数据无法解密。

### Current Behavior (by design)

- Local default: `STORAGE_ROOT=./var`
- Persistence: SQLite at `./var/data/app.db`
- First boot requires `/setup` initialization before `/admin` and `/sub/*` become available.
- If `data_encryption_key` doesn't match existing encrypted data: **the service refuses to start**
  with a clear error message (fail-fast).

### Fix

- Do not rotate `data_encryption_key` for the same storage directory unless you explicitly migrate.
- Keep local `.env` stable across restarts.

## 6. Root Cause: Missing LazyCat Identity Header

### Symptom

`/admin` returns `401` with `lazycat login required`.

### Why It Happens

Admin routes now trust LazyCat identity headers only.  
In local direct access, gateway headers are absent by default.

### Fix

Use a simulated header in local debug requests:

```bash
curl -H "X-HC-User-ID: local-dev-user" http://127.0.0.1:8080/admin
```

## 7. Standard Local Start/Stop Commands

Stable background run (no reload):

```bash
pkill -f "uvicorn app.main:app" || true
set -a && source .env && set +a
nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --log-level info > local-dev.log 2>&1 &
sleep 1
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/
```

If refused: `tail -n 200 local-dev.log`.

## 8. Automation Runner Caveat (Codex/CI Shell)

### Symptom

Background startup command returns success once, but later:

- `healthz=000`
- `lsof` has no listener
- pidfile exists but `pid_alive=0`

### Why It Happens

In some automation shells, detached children from `nohup ... &` can be reclaimed when the parent command finishes.
This makes background mode look flaky even when app startup itself is healthy.

### Recommendation

For debugging in automation runner:

1. Prefer foreground mode first:

```bash
set -a && source .env && set +a
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --log-level info
```

2. Capture evidence before concluding root cause:

```bash
bash "$CODEX_HOME/skills/fastapi-debug-control-loop/scripts/capture_local_fastapi_incident.sh" \
  127.0.0.1 8080 var/logs/SubHub-app.log var/logs/SubHub-app.pid var/debug-incidents
```
