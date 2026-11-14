from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import threading
from dataclasses import dataclass, field, replace as dataclass_replace
from pathlib import Path
from tempfile import mkdtemp
from typing import Any
from uuid import uuid4

import yaml
from dulwich import porcelain
from dulwich.objects import Commit
from dulwich.repo import Repo

from app.config import Settings
from app.models import (
    RULE_CATEGORY_TYPE_MANUAL,
    CustomRule,
    RouteContract,
    RouteContractView,
    RuleCategory,
    ScenarioProfile,
    ServiceCatalogEntry,
)
from app.services.error_diagnostics import error_detail
from app.services.runtime_observability import (
    NullRuntimeTaskMonitor,
    RuntimeAlertService,
    RuntimeTaskMonitor,
)
from app.services.route_contract_views import scenario_route_contract
from app.storage.sqlite_repo import SqliteRepo, initial_route_contract_templates

POLICY_BACKUP_MANIFEST_SCHEMA = "subhub.policy-backup.v2"
RUNTIME_KEY_POLICY_BACKUP_STATUS = "policy_backup.status"
DEFAULT_SCENARIO_ID = "scenario-default"
DEFAULT_SCENARIO_SLUG = "default"
MANAGED_ROOT_NAMES = ("manifest.json", "README.md", "global", "categories", "scenarios")
_logger = logging.getLogger("app.policy_backup_service")


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _ordered_yaml(value: object) -> str:
    return yaml.safe_dump(
        value,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
    )


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class RestoreSnapshotChanged(ValueError):
    """A restoration no longer matches the content the user reviewed."""


def _scenario_dir_name(scenario: ScenarioProfile) -> str:
    return DEFAULT_SCENARIO_SLUG if scenario.id == DEFAULT_SCENARIO_ID else scenario.id


def _rule_key(item: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        _normalize_text(item.get("category_name")),
        _normalize_text(item.get("rule_type")),
        _normalize_text(item.get("value")),
        _normalize_text(item.get("target_contract_id") or item.get("target_group")),
    )


def _binding_key(item: dict[str, object]) -> tuple[str, str]:
    return (_normalize_text(item.get("category_name")), _normalize_text(item.get("contract_id")))


def _contract_view_key(item: dict[str, object]) -> str:
    return _normalize_text(item.get("contract_id"))


def _pin_group_key(item: dict[str, object]) -> str:
    return _normalize_text(item.get("group_name"))


def _category_key(item: dict[str, object]) -> str:
    return _normalize_text(item.get("name"))


def _deep_copy(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


@dataclass
class PolicyBackupManifest:
    schema_version: str
    exported_at: str
    app_name: str
    app_version: str
    source_repo: str
    scenario_ids: list[str]
    counts: dict[str, int]
    digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "exported_at": self.exported_at,
            "app_name": self.app_name,
            "app_version": self.app_version,
            "source_repo": self.source_repo,
            "scenario_ids": list(self.scenario_ids),
            "counts": dict(self.counts),
            "digest": self.digest,
        }


@dataclass
class PolicyBackupStatus:
    enabled: bool
    configured: bool
    repo_url: str
    branch: str
    subdir: str
    dirty: bool
    syncing: bool
    last_result: str
    last_sync_at: str
    last_commit_sha: str
    last_error: str
    last_sync_run_id: str
    last_error_detail: dict[str, object] | None
    dirty_generation: int = 0
    acked_generation: int = 0
    outbox_pending_count: int = 0
    outbox_oldest_at: str = ""
    reconciliation_required: bool = False
    reconciliation_error: str = ""
    last_remote_probe_at: str = ""
    last_remote_digest: str = ""
    last_remote_commit_sha: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "repo_url": self.repo_url,
            "branch": self.branch,
            "subdir": self.subdir,
            "dirty": self.dirty,
            "syncing": self.syncing,
            "last_result": self.last_result,
            "last_sync_at": self.last_sync_at,
            "last_commit_sha": self.last_commit_sha,
            "last_error": self.last_error,
            "last_sync_run_id": self.last_sync_run_id,
            "last_error_detail": self.last_error_detail,
            "dirty_generation": self.dirty_generation,
            "acked_generation": self.acked_generation,
            "outbox_pending_count": self.outbox_pending_count,
            "outbox_oldest_at": self.outbox_oldest_at,
            "reconciliation_required": self.reconciliation_required,
            "reconciliation_error": self.reconciliation_error,
            "last_remote_probe_at": self.last_remote_probe_at,
            "last_remote_digest": self.last_remote_digest,
            "last_remote_commit_sha": self.last_remote_commit_sha,
        }

    def to_public_dict(self) -> dict[str, object]:
        """Return the non-sensitive projection safe for anonymous healthz.

        ``to_dict`` is an authenticated management view and intentionally
        includes the configured repository URL and diagnostic text.  Health
        probes are public, so their payload must not disclose credentials
        embedded in that URL (or arbitrary error text that could repeat it).
        Keep this projection limited to bounded state, counters, timestamps,
        and content identifiers.
        """
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "dirty": self.dirty,
            "syncing": self.syncing,
            "last_result": self.last_result,
            "last_sync_at": self.last_sync_at,
            "last_commit_sha": self.last_commit_sha,
            "last_sync_run_id": self.last_sync_run_id,
            "dirty_generation": self.dirty_generation,
            "acked_generation": self.acked_generation,
            "outbox_pending_count": self.outbox_pending_count,
            "outbox_oldest_at": self.outbox_oldest_at,
            "reconciliation_required": self.reconciliation_required,
            "has_reconciliation_error": bool(self.reconciliation_error),
            "last_remote_probe_at": self.last_remote_probe_at,
            "last_remote_digest": self.last_remote_digest,
            "last_remote_commit_sha": self.last_remote_commit_sha,
        }


@dataclass
class _GitSyncResult:
    ok: bool
    changed: bool
    commit_sha: str = ""
    error: str = ""
    error_detail: dict[str, object] | None = None
    ambiguous: bool = False
    remote_digest: str = ""


@dataclass
class _GitRemoteState:
    ok: bool
    commit_sha: str = ""
    manifest_digest: str = ""
    error: str = ""
    error_detail: dict[str, object] | None = None


@dataclass
class _RestorePreviewSection:
    name: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
            "added_count": len(self.added),
            "removed_count": len(self.removed),
            "changed_count": len(self.changed),
        }


class PolicyBackupGitBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repo_root = Path(__file__).resolve().parents[2]
        self.local_root = Path(settings.storage_root) / "backup" / "policy-git"
    def _repo_url(self) -> str:
        return _normalize_text(self.settings.policy_backup_repo_url)

    def _auth_kwargs(self) -> dict[str, object]:
        repo_url = self._repo_url()
        token = _normalize_text(self.settings.policy_backup_github_token)
        if not repo_url or not token:
            return {}
        if repo_url.startswith("http://") or repo_url.startswith("https://"):
            return {
                "username": "x-access-token",
                "password": token,
            }
        return {}

    def _remote_branch_exists(self, repo_url: str, branch: str) -> bool:
        result = porcelain.ls_remote(repo_url, **self._auth_kwargs())
        refs = result.refs if hasattr(result, "refs") else dict(result)
        return f"refs/heads/{branch}".encode("utf-8") in refs

    def _open_temp_repo(self, *, require_remote_branch: bool = False) -> tuple[Repo, Path, Path]:
        self.local_root.mkdir(parents=True, exist_ok=True)
        repo_url = self._repo_url()
        branch = _normalize_text(self.settings.policy_backup_branch) or "main"
        temp_root = Path(mkdtemp(dir=self.local_root))
        worktree = temp_root / "repo"
        branch_exists = self._remote_branch_exists(repo_url, branch)
        if branch_exists:
            repo = porcelain.clone(
                repo_url,
                target=str(worktree),
                branch=branch,
                checkout=True,
                errstream=io.BytesIO(),
                **self._auth_kwargs(),
            )
            return repo, worktree, temp_root
        if require_remote_branch:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise FileNotFoundError(branch)
        repo = porcelain.init(str(worktree))
        repo.refs.set_symbolic_ref(b"HEAD", f"refs/heads/{branch}".encode("utf-8"))
        return repo, worktree, temp_root

    def _remove_managed_tree(self, worktree: Path, subdir: str) -> None:
        root = worktree / subdir if subdir else worktree
        for name in MANAGED_ROOT_NAMES:
            target = root / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()

    def _write_files(self, worktree: Path, files: dict[str, str]) -> None:
        for relpath, content in files.items():
            path = worktree / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def _current_branch_ref(self, repo: Repo) -> str:
        chain, _ = repo.refs.follow(b"HEAD")
        if len(chain) > 1:
            return chain[-1].decode("utf-8")
        return f"refs/heads/{_normalize_text(self.settings.policy_backup_branch) or 'main'}"

    def _has_staged_changes(self, repo: Repo) -> bool:
        status = porcelain.status(repo)
        staged = getattr(status, "staged", {}) or {}
        return any(staged.get(name) for name in ("add", "delete", "modify"))

    def _manifest_relpath(self) -> str:
        prefix = Path(_normalize_text(self.settings.policy_backup_subdir)) if _normalize_text(self.settings.policy_backup_subdir) else Path(".")
        return str((prefix / "manifest.json").as_posix()).lstrip("./")

    def _extract_manifest_digest(self, manifest_text: str) -> str:
        try:
            payload = json.loads(manifest_text)
        except json.JSONDecodeError:
            return ""
        return _normalize_text(payload.get("digest"))

    def _existing_manifest_digest(self, worktree: Path) -> str:
        manifest_path = worktree / self._manifest_relpath()
        if not manifest_path.exists():
            return ""
        return self._extract_manifest_digest(manifest_path.read_text(encoding="utf-8"))

    def sync_files(
        self,
        files: dict[str, str],
        *,
        commit_message: str,
        author_name: str,
        author_email: str,
        sync_run_id: str | None = None,
    ) -> _GitSyncResult:
        sync_run_id = sync_run_id or uuid4().hex
        temp_root: Path | None = None
        push_started = False
        incoming_digest = ""
        try:
            repo, worktree, temp_root = self._open_temp_repo()
            incoming_digest = self._extract_manifest_digest(files.get(self._manifest_relpath(), ""))
            if incoming_digest and incoming_digest == self._existing_manifest_digest(worktree):
                return _GitSyncResult(ok=True, changed=False, remote_digest=incoming_digest)
            subdir = _normalize_text(self.settings.policy_backup_subdir)
            self._remove_managed_tree(worktree, subdir)
            self._write_files(worktree, files)
            porcelain.add(repo)
            if not self._has_staged_changes(repo):
                return _GitSyncResult(ok=True, changed=False, remote_digest=incoming_digest)
            identity = f"{author_name} <{author_email}>".encode("utf-8")
            commit_id = porcelain.commit(
                repo,
                message=commit_message.encode("utf-8"),
                author=identity,
                committer=identity,
                # Policy snapshots are data commits.  Do not inherit the
                # operator checkout's SSH-signing config into a temporary
                # fake/local backup repository.
                sign=False,
            )
            push_started = True
            branch = _normalize_text(self.settings.policy_backup_branch) or "main"
            porcelain.push(
                repo,
                remote_location=self._repo_url(),
                refspecs=f"{self._current_branch_ref(repo)}:refs/heads/{branch}",
                outstream=io.BytesIO(),
                errstream=io.BytesIO(),
                **self._auth_kwargs(),
            )
            return _GitSyncResult(
                ok=True,
                changed=True,
                commit_sha=commit_id.decode("utf-8"),
                remote_digest=incoming_digest,
            )
        except Exception as exc:
            diagnostic = error_detail(exc, "policy_backup_git_sync", sync_run_id)
            _logger.error("policy backup git sync failed: %s", diagnostic)
            return _GitSyncResult(
                ok=False,
                changed=False,
                error=str(diagnostic["message"]) or "git command failed",
                error_detail=diagnostic,
                ambiguous=push_started,
                remote_digest=incoming_digest,
            )
        finally:
            if temp_root is not None:
                shutil.rmtree(temp_root, ignore_errors=True)

    def inspect_remote_manifest(self, *, ref: str | None = None) -> _GitRemoteState:
        """Read the remote branch and manifest without mutating it.

        This read is the recovery boundary after an interrupted push.  A
        caller must compare the returned manifest digest with the exact local
        snapshot digest before acknowledging a durable outbox generation.
        """
        temp_root: Path | None = None
        try:
            repo, _worktree, temp_root = self._open_temp_repo(require_remote_branch=True)
            commit = self._resolve_commit(repo, ref)
            tree = repo[commit.tree]
            _, sha = tree.lookup_path(repo.get_object, self._manifest_relpath().encode("utf-8"))
            manifest = repo[sha].data.decode("utf-8")
            return _GitRemoteState(
                ok=True,
                commit_sha=commit.id.decode("utf-8"),
                manifest_digest=self._extract_manifest_digest(manifest),
            )
        except Exception as exc:
            diagnostic = error_detail(exc, "policy_backup_git_probe", uuid4().hex)
            _logger.error("policy backup git probe failed: %s", diagnostic)
            return _GitRemoteState(
                ok=False,
                error=str(diagnostic["message"]),
                error_detail=diagnostic,
            )
        finally:
            if temp_root is not None:
                shutil.rmtree(temp_root, ignore_errors=True)

    def _resolve_commit(self, repo: Repo, ref: str | None = None) -> Commit:
        branch = _normalize_text(self.settings.policy_backup_branch) or "main"
        candidates: list[bytes] = []
        if ref:
            normalized = ref.encode("utf-8")
            candidates.extend(
                [
                    normalized,
                    f"refs/remotes/origin/{ref}".encode("utf-8"),
                    f"refs/heads/{ref}".encode("utf-8"),
                ]
            )
        else:
            candidates.extend(
                [
                    f"refs/remotes/origin/{branch}".encode("utf-8"),
                    f"refs/heads/{branch}".encode("utf-8"),
                    b"HEAD",
                ]
            )
        for candidate in candidates:
            try:
                target = repo.head() if candidate == b"HEAD" else repo.refs[candidate]
            except KeyError:
                continue
            try:
                obj = repo[target]
            except KeyError:
                continue
            if isinstance(obj, Commit):
                return obj
        raise FileNotFoundError(ref or branch)

    def read_file(self, relpath: str, *, ref: str | None = None) -> str:
        temp_root: Path | None = None
        try:
            repo, _worktree, temp_root = self._open_temp_repo(require_remote_branch=True)
            commit = self._resolve_commit(repo, ref)
            tree = repo[commit.tree]
            _, sha = tree.lookup_path(repo.get_object, relpath.encode("utf-8"))
            blob = repo[sha]
            return blob.data.decode("utf-8")
        except KeyError as exc:
            raise FileNotFoundError(relpath) from exc
        finally:
            if temp_root is not None:
                shutil.rmtree(temp_root, ignore_errors=True)

    def current_source_repo(self) -> str:
        try:
            repo = Repo.discover(str(self.repo_root))
            config = repo.get_config()
            return (config.get((b"remote", b"origin"), b"url") or b"").decode("utf-8").strip()
        except Exception:
            return ""


class PolicyBackupService:
    def __init__(
        self,
        settings: Settings,
        repo: SqliteRepo,
        runtime_monitor: RuntimeTaskMonitor | None = None,
        alerts: RuntimeAlertService | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.backend = PolicyBackupGitBackend(settings)
        self.runtime_monitor = runtime_monitor or NullRuntimeTaskMonitor()
        self.alerts = alerts
        self._loop: asyncio.AbstractEventLoop | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._startup_reconcile_task: asyncio.Task[None] | None = None
        self._startup_ready: asyncio.Event | None = None
        self._event: asyncio.Event | None = None
        self._shutdown = False
        self._dirty = False
        self._dirty_generation = 0
        self._syncing = False
        self._reasons: set[str] = set()
        self._suspend_dirty = 0
        self._state_lock = threading.Lock()
        # Serialize complete policy restore operations outside the repository
        # writer lock.  Staging is intentionally slow and happens in a worker
        # thread; this lock prevents two restores from both preparing against
        # the same live database and then racing their promotions, while it
        # still leaves heartbeats and management writes free to run.
        self._restore_operation_lock = threading.Lock()
        self._load_durable_state()

    def _load_durable_state(self) -> None:
        state = self.repo.get_policy_backup_state()
        with self._state_lock:
            self._dirty = bool(
                int(state.get("pending_count") or 0) > 0
                or bool(state.get("reconciliation_required"))
            )
            self._reasons = {
                str(item.get("reason") or "")
                for item in self.repo.list_policy_backup_outbox()
                if str(item.get("status") or "") == "pending" and str(item.get("reason") or "")
            }

    def _has_durable_pending(self) -> bool:
        state = self.repo.get_policy_backup_state()
        return bool(
            int(state.get("pending_count") or 0) > 0
            or bool(state.get("reconciliation_required"))
        )

    def _wake_worker(self) -> None:
        event = self._event
        if event is None:
            return
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(event.set)
        else:
            event.set()

    def _reload_dirty_state(self) -> dict[str, object]:
        """Refresh in-memory hints from the durable outbox.

        A mutation can arrive while a Git sync is exporting a snapshot.  The
        sync only acknowledges the generation it captured before export; the
        next generation must remain visible to the worker instead of having
        its reason accidentally cleared by the completed sync.
        """
        state = self.repo.get_policy_backup_state()
        pending_reasons = {
            str(item.get("reason") or "")
            for item in self.repo.list_policy_backup_outbox()
            if str(item.get("status") or "") == "pending" and str(item.get("reason") or "")
        }
        with self._state_lock:
            self._dirty = bool(
                int(state.get("pending_count") or 0) > 0
                or bool(state.get("reconciliation_required"))
            )
            self._reasons = pending_reasons
        return state

    async def ensure_started(self) -> None:
        self._load_durable_state()
        if self._worker_task and not self._worker_task.done():
            return
        self.runtime_monitor.register("policy_backup.worker", required=True)
        self._loop = asyncio.get_running_loop()
        self._event = asyncio.Event()
        self._startup_ready = asyncio.Event()
        self._shutdown = False
        self._worker_task = asyncio.create_task(self._worker(), name="policy-backup-worker")
        self._startup_reconcile_task = asyncio.create_task(
            self._startup_reconcile(), name="policy-backup-startup-reconcile"
        )
        self.runtime_monitor.watch("policy_backup.worker", self._worker_task)
        self.runtime_monitor.startup_success("policy_backup.worker")
        if self._has_durable_pending() or bool(self.repo.get_policy_backup_state().get("reconciliation_required")):
            self._event.set()

    async def shutdown(self) -> None:
        self._shutdown = True
        if self._event:
            self._event.set()
        if self._startup_ready:
            self._startup_ready.set()
        if self._startup_reconcile_task:
            self._startup_reconcile_task.cancel()
            try:
                await self._startup_reconcile_task
            except asyncio.CancelledError:
                pass
            self._startup_reconcile_task = None
        if self._worker_task:
            self.runtime_monitor.expect_stop("policy_backup.worker")
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        self.runtime_monitor.stopped("policy_backup.worker")

    def suspend_dirty_notifications(self) -> None:
        with self._state_lock:
            self._suspend_dirty += 1

    def resume_dirty_notifications(self) -> None:
        with self._state_lock:
            self._suspend_dirty = max(0, self._suspend_dirty - 1)

    def is_enabled(self) -> bool:
        return bool(self.settings.policy_backup_enabled)

    def is_configured(self) -> bool:
        if not self.is_enabled():
            return False
        repo_url = _normalize_text(self.settings.policy_backup_repo_url)
        branch = _normalize_text(self.settings.policy_backup_branch) or "main"
        author_name = _normalize_text(self.settings.policy_backup_author_name)
        author_email = _normalize_text(self.settings.policy_backup_author_email)
        if not repo_url or not branch or not author_name or not author_email:
            return False
        if repo_url.startswith("http://") or repo_url.startswith("https://"):
            return bool(_normalize_text(self.settings.policy_backup_github_token))
        return True

    def mark_dirty(self, reason: str = "") -> None:
        with self._state_lock:
            if self._suspend_dirty > 0:
                return
            self._dirty = True
            self._dirty_generation += 1
            if reason:
                self._reasons.add(reason)
        try:
            state = self.repo.record_policy_backup_dirty(reason)
            with self._state_lock:
                self._dirty = bool(
                    int(state.get("pending_count") or 0) > 0
                    or bool(state.get("reconciliation_required"))
                )
        except Exception as exc:
            detail = error_detail(exc, "policy_backup_outbox", uuid4().hex)
            _logger.error("policy backup dirty generation persistence failed: %s", detail)
            if self.alerts:
                self.alerts.emit_fatal(
                    "policy_backup.outbox",
                    "policy backup dirty generation could not be persisted",
                    details=detail,
                )
        if self._loop and self._event:
            self._wake_worker()

    def status(self) -> PolicyBackupStatus:
        raw = self.repo.get_runtime_setting(RUNTIME_KEY_POLICY_BACKUP_STATUS) or {}
        payload = raw if isinstance(raw, dict) else {}
        state = self.repo.get_policy_backup_state()
        return PolicyBackupStatus(
            enabled=self.is_enabled(),
            configured=self.is_configured(),
            repo_url=_normalize_text(self.settings.policy_backup_repo_url),
            branch=_normalize_text(self.settings.policy_backup_branch) or "main",
            subdir=_normalize_text(self.settings.policy_backup_subdir),
            dirty=bool(
                int(state.get("pending_count") or 0) > 0
                or bool(state.get("reconciliation_required"))
            ),
            syncing=self._syncing,
            last_result=_normalize_text(payload.get("last_result")) or "idle",
            last_sync_at=_normalize_text(payload.get("last_sync_at")),
            last_commit_sha=_normalize_text(payload.get("last_commit_sha")),
            last_error=_normalize_text(payload.get("last_error")),
            last_sync_run_id=_normalize_text(payload.get("last_sync_run_id")),
            last_error_detail=(
                payload.get("last_error_detail")
                if isinstance(payload.get("last_error_detail"), dict)
                else None
            ),
            dirty_generation=int(state.get("dirty_generation") or 0),
            acked_generation=int(state.get("acked_generation") or 0),
            outbox_pending_count=int(state.get("pending_count") or 0),
            outbox_oldest_at=str(state.get("oldest_pending_at") or ""),
            reconciliation_required=bool(state.get("reconciliation_required")),
            reconciliation_error=str(state.get("reconciliation_error") or ""),
            last_remote_probe_at=str(state.get("last_remote_probe_at") or ""),
            last_remote_digest=str(state.get("last_remote_digest") or ""),
            last_remote_commit_sha=str(state.get("last_remote_commit_sha") or ""),
        )

    async def sync_now(self, *, force: bool = False) -> dict[str, object]:
        if not self.is_enabled():
            raise ValueError("policy backup not enabled")
        if not self.is_configured():
            raise ValueError("policy backup not configured")
        result = await asyncio.to_thread(self._sync_now_blocking, force)
        if bool(result.get("ok")):
            # An operator-triggered reconciliation is also proof that the
            # resident policy-backup path recovered.  Clear the old degraded
            # heartbeat only after every generation is acknowledged; a
            # concurrent mutation must keep readiness degraded until its own
            # durable obligation is handled.
            try:
                state = self.repo.get_policy_backup_state()
                fully_reconciled = (
                    int(state.get("pending_count") or 0) == 0
                    and not bool(state.get("reconciliation_required"))
                )
            except Exception as exc:
                _logger.error("policy backup recovery state lookup failed: %s", exc)
                fully_reconciled = False
            if fully_reconciled and not self._worker_exit_is_unresolved():
                self.runtime_monitor.success(
                    "policy_backup.worker",
                    details={
                        "phase": "operator_sync_complete",
                        "reconciled": bool(result.get("reconciled")),
                    },
                )
        return result

    def _worker_exit_is_unresolved(self) -> bool:
        """Keep a fatal resident-task exit visible during operator recovery.

        ``sync_now`` may be called from an operator endpoint after the
        background worker has died.  A successful Git write only proves the
        policy obligation was reconciled; it does not prove that the worker
        is resident again.  Do not turn readiness green until a new worker
        has been started and explicitly marked successful.
        """
        task = self._worker_task
        if task is not None and task.done():
            return True
        try:
            heartbeat = self.repo.get_runtime_heartbeat("policy_backup.worker")
        except Exception as exc:
            _logger.error("policy backup worker heartbeat lookup failed: %s", exc)
            return True
        if not heartbeat:
            return False
        details = heartbeat.get("details")
        if isinstance(details, dict) and str(details.get("exit") or "").strip():
            return True
        return "resident task policy_backup.worker exited unexpectedly" in str(
            heartbeat.get("last_error") or ""
        )

    def export_snapshot(self) -> dict[str, object]:
        with self.repo.transaction():
            base = self._build_snapshot_without_manifest()
        manifest = self._build_manifest(base)
        snapshot = {
            "manifest": manifest.to_dict(),
            "global": base["global"],
            "categories": base["categories"],
            "scenarios": base["scenarios"],
        }
        return snapshot

    async def restore_preview(self, *, ref: str = "") -> dict[str, object]:
        remote = await asyncio.to_thread(self._load_snapshot_from_git, ref)
        current = self.export_snapshot()
        return self._build_restore_preview(current, remote, ref=ref)

    async def restore_apply(self, *, ref: str = "", expected_digest: str = "") -> dict[str, object]:
        if not expected_digest:
            raise RestoreSnapshotChanged("restore snapshot changed; preview again")
        remote = await asyncio.to_thread(self._load_snapshot_from_git, ref)
        preview = self._build_restore_preview(self.export_snapshot(), remote, ref=ref)
        if expected_digest != preview["snapshot_digest"]:
            raise RestoreSnapshotChanged("restore snapshot changed; preview again")
        await asyncio.to_thread(self._apply_snapshot, remote)
        self.mark_dirty("restore-apply")
        notify = getattr(self.repo, "_notify_policy_backup", None)
        if callable(notify):
            notify("restore-apply")
        return {
            "ok": True,
            "preview": preview,
            "applied": {
                "manual_categories": len(remote["categories"]["manual_categories"]),
                "global_custom_rules": len(remote["global"]["custom_rules"]),
                "scenario_count": len(remote["scenarios"]),
            },
        }

    async def _startup_reconcile(self) -> None:
        try:
            if self.is_enabled() and self.is_configured():
                self.runtime_monitor.heartbeat(
                    "policy_backup.worker",
                    details={"phase": "startup_reconcile"},
                )
                result = await asyncio.to_thread(self._reconcile_on_startup)
                if result.get("ok"):
                    self.runtime_monitor.success(
                        "policy_backup.worker",
                        details={"phase": "startup_reconcile_complete", "action": result.get("action", "")},
                    )
                else:
                    self.runtime_monitor.failure(
                        "policy_backup.worker",
                        "policy backup startup reconciliation did not complete",
                        details=result,
                    )
            else:
                self.runtime_monitor.success(
                    "policy_backup.worker",
                    details={"phase": "startup_reconcile", "enabled": self.is_enabled()},
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = error_detail(exc, "policy_backup_startup_reconcile", uuid4().hex)
            _logger.error("policy backup startup reconcile failed: %s", detail)
            self.repo.set_policy_backup_reconciliation(
                True,
                error=str(detail["message"]),
            )
            self.runtime_monitor.failure(
                "policy_backup.worker",
                "policy backup startup reconciliation failed",
                details=detail,
            )
        finally:
            if self._startup_ready:
                self._startup_ready.set()

    def _reconcile_on_startup(self) -> dict[str, object]:
        state = self.repo.get_policy_backup_state()
        pending = int(state.get("pending_count") or 0) > 0
        snapshot = self.export_snapshot()
        expected_digest = _normalize_text((snapshot.get("manifest") or {}).get("digest"))
        try:
            remote = self.backend.inspect_remote_manifest()
        except Exception as exc:
            detail = error_detail(exc, "policy_backup_git_probe", uuid4().hex)
            _logger.error("policy backup startup git probe failed: %s", detail)
            remote = _GitRemoteState(
                ok=False,
                error=str(detail["message"]),
                error_detail=detail,
            )
        if remote.ok and remote.manifest_digest == expected_digest:
            if pending:
                self.repo.acknowledge_policy_backup_generation(
                    int(state.get("dirty_generation") or 0),
                    commit_sha=remote.commit_sha,
                    remote_digest=remote.manifest_digest,
                )
            self.repo.set_policy_backup_reconciliation(
                False,
                remote_digest=remote.manifest_digest,
                remote_commit_sha=remote.commit_sha,
            )
            return {
                "ok": True,
                "action": "remote_already_matches",
                "commit_sha": remote.commit_sha,
                "remote_digest": remote.manifest_digest,
            }

        # The mutation callback can be interrupted after its policy commit but
        # before it appends an outbox row.  Comparing on every startup closes
        # that window: persist an obligation before attempting another Git
        # write, even when the previous durable state claimed to be clean.
        if not pending:
            self.repo.record_policy_backup_dirty("startup-reconcile")
            state = self.repo.get_policy_backup_state()
            pending = True
            self._wake_worker()
        self.repo.set_policy_backup_reconciliation(
            True,
            error=remote.error or "remote policy backup does not match local snapshot",
            remote_digest=remote.manifest_digest,
            remote_commit_sha=remote.commit_sha,
        )
        result = self._sync_now_blocking(force=False)
        return {"ok": bool(result.get("ok")), "action": "retry_push", "result": result}

    async def _worker(self) -> None:
        assert self._event is not None
        if self._startup_ready:
            await self._startup_ready.wait()
        debounce = max(int(self.settings.policy_backup_debounce_seconds), 1)
        while not self._shutdown:
            durable_obligation = self._has_durable_pending()
            self.runtime_monitor.heartbeat(
                "policy_backup.worker",
                details={"phase": "waiting", "pending": durable_obligation},
            )
            try:
                await asyncio.wait_for(
                    self._event.wait(),
                    timeout=max(int(getattr(self.settings, "runtime_heartbeat_interval_seconds", 30)), 5),
                )
                self._event.clear()
            except asyncio.TimeoutError:
                # Re-read the durable state after the wait.  An operator
                # sync (or a startup compare) can create only a
                # ``reconciliation_required`` obligation while this worker
                # is asleep and there may be no outbox row/event to wake it.
                # Reusing the pre-wait snapshot would strand that obligation
                # forever until another mutation or process restart.
                if self._has_durable_pending() and self.is_enabled() and self.is_configured():
                    self._event.set()
                continue
            if self._shutdown:
                return
            await self._sleep_with_heartbeat(debounce)
            should_sync = self._has_durable_pending() and self.is_enabled() and self.is_configured()
            if not should_sync:
                continue
            while self._has_durable_pending() and not self._shutdown:
                self.runtime_monitor.heartbeat(
                    "policy_backup.worker",
                    details={"phase": "syncing", "pending": True},
                )
                try:
                    result = await self.sync_now()
                except Exception as exc:
                    sync_run_id = uuid4().hex
                    diagnostic = error_detail(exc, "policy_backup_worker", sync_run_id)
                    _logger.error("policy backup worker failed: %s", diagnostic)
                    self.runtime_monitor.failure(
                        "policy_backup.worker",
                        "policy backup worker failed",
                        details=diagnostic,
                    )
                    result = {"ok": False, "error": str(diagnostic["message"])}
                # A completed Git attempt is meaningful progress even when
                # the result is a retryable failure.  Record it before the
                # success/failure transition so a long sequence of backend
                # operations remains observable between attempts.
                self.runtime_monitor.heartbeat(
                    "policy_backup.worker",
                    details={
                        "phase": "sync_result",
                        "ok": bool(result.get("ok")),
                        "ambiguous": bool(result.get("ambiguous")),
                    },
                )
                if bool(result.get("busy")):
                    # A concurrent manual sync owns the worker.  Treating
                    # this as success leaves the durable generation pending
                    # and spins a tight to_thread/SQLite loop until the other
                    # sync finishes.  Back off in the event loop and let the
                    # next pass observe the generation again.
                    await self._sleep_with_heartbeat(max(debounce, 1))
                    continue
                if result.get("ok"):
                    self.runtime_monitor.success(
                        "policy_backup.worker",
                        details={"phase": "sync_complete"},
                    )
                    continue
                self.runtime_monitor.failure(
                    "policy_backup.worker",
                    "policy backup sync failed",
                    details={
                        "error": str(result.get("error") or "unknown policy backup error"),
                        "sync_run_id": str(result.get("sync_run_id") or ""),
                        "ambiguous": bool(result.get("ambiguous")),
                    },
                )
                await self._sleep_with_heartbeat(
                    max(int(getattr(self.settings, "runtime_heartbeat_interval_seconds", 30)), 5)
                )

    async def _sleep_with_heartbeat(self, seconds: int) -> None:
        remaining = max(0, int(seconds))
        interval = max(int(getattr(self.settings, "runtime_heartbeat_interval_seconds", 30)), 5)
        while remaining > 0 and not self._shutdown:
            delay = min(remaining, interval)
            await asyncio.sleep(delay)
            remaining -= delay
            if not self._shutdown:
                self.runtime_monitor.heartbeat(
                    "policy_backup.worker",
                    details={"phase": "waiting"},
                )

    def _sync_now_blocking(self, force: bool) -> dict[str, object]:
        sync_run_id = uuid4().hex
        durable_state = self.repo.get_policy_backup_state()
        generation = int(durable_state.get("dirty_generation") or 0)
        with self._state_lock:
            if self._syncing:
                return {"ok": False, "busy": True, "retryable": True}
            self._syncing = True
            reasons = sorted(self._reasons)
        try:
            snapshot = self.export_snapshot()
            expected_digest = _normalize_text((snapshot.get("manifest") or {}).get("digest"))
            files = self._snapshot_to_files(snapshot)
            commit_message = self._commit_message(snapshot)
            result = self.backend.sync_files(
                files,
                commit_message=commit_message,
                author_name=self.settings.policy_backup_author_name,
                author_email=self.settings.policy_backup_author_email,
                sync_run_id=sync_run_id,
            )
            if not result.ok:
                remote = self.backend.inspect_remote_manifest()
                if remote.ok and remote.manifest_digest == expected_digest:
                    self.repo.acknowledge_policy_backup_generation(
                        generation,
                        sync_run_id=sync_run_id,
                        commit_sha=remote.commit_sha,
                        remote_digest=remote.manifest_digest,
                    )
                    self.repo.set_policy_backup_reconciliation(
                        False,
                        remote_digest=remote.manifest_digest,
                        remote_commit_sha=remote.commit_sha,
                        sync_run_id=sync_run_id,
                    )
                    self._reload_dirty_state()
                    status = self.status().to_dict()
                    status.update(
                        {
                            "last_result": "reconciled",
                            "last_sync_at": _utc_now(),
                            "last_commit_sha": remote.commit_sha,
                            "last_error": "",
                            "last_sync_run_id": sync_run_id,
                            "last_error_detail": None,
                        }
                    )
                    self.repo.set_runtime_setting(RUNTIME_KEY_POLICY_BACKUP_STATUS, status)
                    return {
                        "ok": True,
                        "changed": False,
                        "reconciled": True,
                        "commit_sha": remote.commit_sha,
                        "sync_run_id": sync_run_id,
                    }
                self.repo.set_policy_backup_reconciliation(
                    True,
                    error=result.error,
                    remote_digest=remote.manifest_digest,
                    remote_commit_sha=remote.commit_sha,
                    sync_run_id=sync_run_id,
                )
                status = self.status().to_dict()
                status.update(
                    {
                        "last_result": "error",
                        "last_error": result.error,
                        "last_sync_run_id": sync_run_id,
                        "last_error_detail": result.error_detail,
                    }
                )
                self.repo.set_runtime_setting(RUNTIME_KEY_POLICY_BACKUP_STATUS, status)
                return {
                    "ok": False,
                    "error": result.error,
                    "dirty": True,
                    "sync_run_id": sync_run_id,
                    "ambiguous": result.ambiguous,
                    "error_detail": result.error_detail,
                }
            self.repo.acknowledge_policy_backup_generation(
                generation,
                sync_run_id=sync_run_id,
                commit_sha=result.commit_sha,
                remote_digest=result.remote_digest or expected_digest,
            )
            self.repo.set_policy_backup_reconciliation(
                False,
                remote_digest=result.remote_digest or expected_digest,
                remote_commit_sha=result.commit_sha,
                sync_run_id=sync_run_id,
            )
            self._reload_dirty_state()
            status = self.status().to_dict()
            status.update(
                {
                    "last_result": "ok",
                    "last_sync_at": _utc_now(),
                    "last_commit_sha": result.commit_sha or status.get("last_commit_sha", ""),
                    "last_error": "",
                    "last_sync_run_id": sync_run_id,
                    "last_error_detail": None,
                }
            )
            self.repo.set_runtime_setting(RUNTIME_KEY_POLICY_BACKUP_STATUS, status)
            return {
                "ok": True,
                "changed": bool(result.changed),
                "commit_sha": result.commit_sha,
                "reasons": reasons,
                "sync_run_id": sync_run_id,
            }
        except Exception as exc:
            diagnostic = error_detail(exc, "policy_backup_sync", sync_run_id)
            _logger.error("policy backup sync failed: %s", diagnostic)
            self.repo.set_policy_backup_reconciliation(
                True,
                error=str(diagnostic["message"]),
                sync_run_id=sync_run_id,
            )
            status = self.status().to_dict()
            status.update(
                {
                    "last_result": "error",
                    "last_error": str(diagnostic["message"]),
                    "last_sync_run_id": sync_run_id,
                    "last_error_detail": diagnostic,
                }
            )
            try:
                self.repo.set_runtime_setting(RUNTIME_KEY_POLICY_BACKUP_STATUS, status)
            except Exception as status_exc:
                status_detail = error_detail(status_exc, "policy_backup_status_persist", sync_run_id)
                _logger.error("policy backup failure status persistence failed: %s", status_detail)
            return {
                "ok": False,
                "error": str(diagnostic["message"]),
                "dirty": True,
                "sync_run_id": sync_run_id,
                "error_detail": diagnostic,
            }
        finally:
            with self._state_lock:
                self._syncing = False

    def _build_snapshot_without_manifest(self) -> dict[str, object]:
        global_categories = sorted(self.repo.list_rule_categories(), key=lambda item: item.name)
        manual_categories = [item for item in global_categories if item.category_type == RULE_CATEGORY_TYPE_MANUAL]
        manual_names = {item.name for item in manual_categories}
        global_custom_rules = [
            self._custom_rule_payload(item)
            for item in [
                entry
                for entry in sorted(
                    self.repo.list_custom_rules(),
                    key=lambda entry: (entry.category_name, entry.rule_type, entry.value, entry.target_group, entry.id),
                )
                if not (entry.category_name and entry.category_name in manual_names)
            ]
        ]
        manual_category_payloads = []
        for category in manual_categories:
            rules = [
                {
                    "rule_type": item.rule_type,
                    "value": item.value,
                }
                for item in sorted(
                    self.repo.list_custom_rules(category_name=category.name),
                    key=lambda entry: (entry.rule_type, entry.value, entry.id),
                )
            ]
            manual_category_payloads.append(
                {
                    "name": category.name,
                    "assigned_group": category.assigned_group,
                    "locked": bool(category.locked),
                    "lock_source": category.lock_source,
                    "rules": rules,
                }
            )

        global_by_name = {item.name: item for item in global_categories}
        global_bindings = {
            item.category_name: item.to_dict()
            for item in self.repo.list_service_catalog_entries()
        }
        scenarios: dict[str, object] = {}
        for scenario in sorted(self.repo.list_scenarios(), key=lambda item: (item.sort_order, item.id)):
            dir_name = _scenario_dir_name(scenario)
            scenario_categories = self.repo.list_scenario_categories(scenario.id)
            overrides = []
            for item in scenario_categories:
                baseline = global_by_name.get(item.name)
                if not baseline:
                    continue
                if (
                    item.assigned_group == baseline.assigned_group
                    and bool(item.locked) == bool(baseline.locked)
                    and _normalize_text(item.lock_source) == _normalize_text(baseline.lock_source)
                    and _normalize_text(item.override_group) == _normalize_text(baseline.override_group)
                    and bool(item.override_active) == bool(baseline.override_active)
                    and _normalize_text(item.directness_override) == _normalize_text(baseline.directness_override)
                ):
                    continue
                overrides.append(
                    {
                        "name": item.name,
                        "assigned_group": item.assigned_group,
                        "locked": bool(item.locked),
                        "lock_source": item.lock_source,
                        "override_group": item.override_group,
                        "override_active": bool(item.override_active),
                        "directness_override": item.directness_override,
                    }
                )
            overrides.sort(key=_category_key)

            explicit_rules = []
            if scenario.id != DEFAULT_SCENARIO_ID:
                explicit_rules = [
                    self._custom_rule_payload(item)
                    for item in sorted(
                        self.repo.list_explicit_scenario_custom_rules(scenario.id),
                        key=lambda entry: (entry.category_name, entry.rule_type, entry.value, entry.target_group, entry.id),
                    )
                ]

            contract_views = [
                {
                    "contract_id": item.contract_id,
                    "display_name": item.display_name,
                    "description": item.description,
                    "llm_routing_intent": item.llm_routing_intent,
                    "enabled": bool(item.enabled),
                    "sort_order": int(item.sort_order),
                    "is_default": bool(item.is_default),
                    "updated_at": item.updated_at,
                }
                for item in sorted(
                    self.repo.list_scenario_route_contract_views(scenario.id),
                    key=lambda entry: (int(entry.sort_order), entry.contract_id),
                )
            ]

            contract_definitions = [
                {
                    "id": item.id,
                    "display_name": item.display_name,
                    "description": item.description,
                    "llm_routing_intent": item.llm_routing_intent,
                    "routing_action": item.routing_action,
                    "strategy_type": item.strategy_type,
                    "primary_pools": list(item.primary_pools),
                    "fallback_pools": list(item.fallback_pools),
                    "failure_action": item.failure_action,
                    "enabled": bool(item.enabled),
                    "sort_order": int(item.sort_order),
                    "owner_scenario_id": item.owner_scenario_id,
                    "updated_at": item.updated_at,
                }
                for item in sorted(
                    self.repo.list_route_contracts(scenario.id),
                    key=lambda entry: (int(entry.sort_order), entry.id),
                )
                if (
                    (scenario.id == DEFAULT_SCENARIO_ID and not str(item.owner_scenario_id or "").strip())
                    or str(item.owner_scenario_id or "").strip() == scenario.id
                )
            ]

            pin_groups = [
                {
                    "group_name": _normalize_text(item.get("group_name")),
                    "sort_order": int(item.get("sort_order") or 0),
                    "mode": _normalize_text(item.get("mode")),
                    "description": _normalize_text(item.get("description")),
                }
                for item in self.repo.list_scenario_pin_groups(scenario.id)
            ]
            pin_groups.sort(key=lambda item: (int(item["sort_order"]), item["group_name"]))

            merged_bindings = self.repo.list_scenario_service_catalog_entries(scenario.id)
            bindings = []
            for item in merged_bindings:
                baseline = global_bindings.get(item.category_name)
                payload = {
                    "category_name": item.category_name,
                    "catalog_group": item.catalog_group,
                    "contract_id": item.contract_id,
                    "sort_order": int(item.sort_order),
                }
                if scenario.id != DEFAULT_SCENARIO_ID and baseline:
                    baseline_payload = {
                        "category_name": _normalize_text(baseline.get("category_name")),
                        "catalog_group": _normalize_text(baseline.get("catalog_group")),
                        "contract_id": _normalize_text(baseline.get("contract_id")),
                        "sort_order": int(baseline.get("sort_order") or 0),
                    }
                    if payload == baseline_payload:
                        continue
                bindings.append(payload)
            bindings.sort(key=lambda item: (item["catalog_group"], int(item["sort_order"]), item["category_name"]))

            scenarios[dir_name] = {
                "metadata": {
                    "id": scenario.id,
                    "slug": scenario.slug,
                    "name": scenario.name,
                    "description": scenario.description,
                    "enabled": bool(scenario.enabled),
                    "sort_order": int(scenario.sort_order),
                    "updated_at": scenario.updated_at,
                },
                "category_overrides": overrides,
                "custom_rules": explicit_rules,
                "contract_definitions": contract_definitions,
                "contract_views": contract_views,
                "pin_groups": pin_groups,
                "catalog_bindings": bindings,
            }

        return {
            "global": {
                "custom_rules": global_custom_rules,
            },
            "categories": {
                "manual_categories": manual_category_payloads,
            },
            "scenarios": scenarios,
        }

    def _build_manifest(self, base: dict[str, object]) -> PolicyBackupManifest:
        manifest_input = {
            "global": base["global"],
            "categories": base["categories"],
            "scenarios": base["scenarios"],
        }
        counts = {
            "manual_categories": len(base["categories"]["manual_categories"]),  # type: ignore[index]
            "global_custom_rules": len(base["global"]["custom_rules"]),  # type: ignore[index]
            "scenarios": len(base["scenarios"]),  # type: ignore[arg-type]
            "scenario_contract_views": sum(
                len((item or {}).get("contract_views") or [])
                for item in (base["scenarios"] or {}).values()  # type: ignore[union-attr]
                if isinstance(item, dict)
            ),
        }
        digest = _sha256_text(_stable_json(manifest_input))
        return PolicyBackupManifest(
            schema_version=POLICY_BACKUP_MANIFEST_SCHEMA,
            exported_at=_utc_now(),
            app_name=self.settings.app_name,
            app_version=self.settings.app_version,
            source_repo=self.backend.current_source_repo(),
            scenario_ids=[
                _normalize_text(item["metadata"]["id"])
                for item in (base["scenarios"] or {}).values()  # type: ignore[union-attr]
            ],
            counts=counts,
            digest=digest,
        )

    def _custom_rule_payload(self, item: CustomRule) -> dict[str, object]:
        return {
            "rule_type": item.rule_type,
            "value": item.value,
            "target_contract_id": item.resolved_target_contract_id(),
            "target_group": item.display_target_group(),
            "category_name": item.category_name,
            "created_at": item.created_at,
        }

    def _snapshot_to_files(self, snapshot: dict[str, object]) -> dict[str, str]:
        files: dict[str, str] = {}
        prefix = Path(_normalize_text(self.settings.policy_backup_subdir)) if _normalize_text(self.settings.policy_backup_subdir) else Path(".")

        def add(relpath: str, content: str) -> None:
            rel = str((prefix / relpath).as_posix()).lstrip("./")
            files[rel] = content

        add("manifest.json", json.dumps(snapshot["manifest"], ensure_ascii=False, indent=2, sort_keys=False) + "\n")
        add("README.md", self._build_readme(snapshot))
        add("global/custom-rules.yaml", _ordered_yaml(snapshot["global"]))
        add("categories/manual-categories.yaml", _ordered_yaml(snapshot["categories"]))
        scenarios = snapshot["scenarios"] if isinstance(snapshot.get("scenarios"), dict) else {}
        for scenario_dir, payload in scenarios.items():
            if not isinstance(payload, dict):
                continue
            add(f"scenarios/{scenario_dir}/metadata.yaml", _ordered_yaml(payload.get("metadata") or {}))
            add(
                f"scenarios/{scenario_dir}/category-overrides.yaml",
                _ordered_yaml({"category_overrides": payload.get("category_overrides") or []}),
            )
            add(
                f"scenarios/{scenario_dir}/custom-rules.yaml",
                _ordered_yaml({"custom_rules": payload.get("custom_rules") or []}),
            )
            add(
                f"scenarios/{scenario_dir}/contract-definitions.yaml",
                _ordered_yaml({"contract_definitions": payload.get("contract_definitions") or []}),
            )
            add(
                f"scenarios/{scenario_dir}/contract-views.yaml",
                _ordered_yaml({"contract_views": payload.get("contract_views") or []}),
            )
            add(
                f"scenarios/{scenario_dir}/pin-groups.yaml",
                _ordered_yaml({"pin_groups": payload.get("pin_groups") or []}),
            )
            add(
                f"scenarios/{scenario_dir}/catalog-bindings.yaml",
                _ordered_yaml({"catalog_bindings": payload.get("catalog_bindings") or []}),
            )
        return files

    def _build_readme(self, snapshot: dict[str, object]) -> str:
        manifest = snapshot["manifest"] if isinstance(snapshot.get("manifest"), dict) else {}
        return "\n".join(
            [
                "# SubHub Policy Backup",
                "",
                "This repository stores owned routing policy assets exported from the running SubHub service.",
                "",
                "Managed roots:",
                "",
                "- `manifest.json`",
                "- `global/custom-rules.yaml`",
                "- `categories/manual-categories.yaml`",
                "- `scenarios/<scenario>/...`",
                "- `scenarios/<scenario>/contract-views.yaml`",
                "",
                "Manifest:",
                "",
                f"- Schema: `{_normalize_text(manifest.get('schema_version'))}`",
                f"- Exported At: `{_normalize_text(manifest.get('exported_at'))}`",
                f"- App: `{_normalize_text(manifest.get('app_name'))}` `{_normalize_text(manifest.get('app_version'))}`",
                f"- Digest: `{_normalize_text(manifest.get('digest'))}`",
                "",
            ]
        ) + "\n"

    def _commit_message(self, snapshot: dict[str, object]) -> str:
        manifest = snapshot["manifest"] if isinstance(snapshot.get("manifest"), dict) else {}
        exported_at = _normalize_text(manifest.get("exported_at")) or _utc_now()
        manual = len(snapshot["categories"]["manual_categories"])  # type: ignore[index]
        global_rules = len(snapshot["global"]["custom_rules"])  # type: ignore[index]
        scenarios = len(snapshot["scenarios"])  # type: ignore[arg-type]
        return (
            f"backup(policy): {exported_at} "
            f"manual={manual} global={global_rules} scenarios={scenarios}"
        )

    def _load_snapshot_from_git(self, ref: str = "") -> dict[str, object]:
        prefix = Path(_normalize_text(self.settings.policy_backup_subdir)) if _normalize_text(self.settings.policy_backup_subdir) else Path(".")

        def read(relpath: str) -> str:
            path = str((prefix / relpath).as_posix()).lstrip("./")
            return self.backend.read_file(path, ref=ref or None)

        def read_yaml(relpath: str, *, optional: bool = False) -> dict[str, object]:
            try:
                payload = yaml.safe_load(read(relpath)) or {}
            except (FileNotFoundError, KeyError):
                if optional:
                    return {}
                raise
            return payload if isinstance(payload, dict) else {}

        manifest = json.loads(read("manifest.json"))
        if manifest.get("schema_version") not in {"subhub.policy-backup.v1", POLICY_BACKUP_MANIFEST_SCHEMA}:
            raise ValueError("unsupported policy backup schema")
        scenarios_section: dict[str, object] = {}
        for scenario_id in manifest.get("scenario_ids") or []:
            safe_id = _normalize_text(scenario_id)
            scenario_dir = DEFAULT_SCENARIO_SLUG if safe_id == DEFAULT_SCENARIO_ID else safe_id
            scenarios_section[scenario_dir] = {
                "metadata": read_yaml(f"scenarios/{scenario_dir}/metadata.yaml"),
                "category_overrides": read_yaml(f"scenarios/{scenario_dir}/category-overrides.yaml").get("category_overrides") or [],
                "custom_rules": read_yaml(f"scenarios/{scenario_dir}/custom-rules.yaml").get("custom_rules") or [],
                "contract_definitions": read_yaml(f"scenarios/{scenario_dir}/contract-definitions.yaml", optional=manifest.get("schema_version") != POLICY_BACKUP_MANIFEST_SCHEMA).get("contract_definitions") or [],
                "contract_views": read_yaml(f"scenarios/{scenario_dir}/contract-views.yaml", optional=manifest.get("schema_version") != POLICY_BACKUP_MANIFEST_SCHEMA).get("contract_views") or [],
                "pin_groups": read_yaml(f"scenarios/{scenario_dir}/pin-groups.yaml").get("pin_groups") or [],
                "catalog_bindings": read_yaml(f"scenarios/{scenario_dir}/catalog-bindings.yaml").get("catalog_bindings") or [],
            }
        snapshot = {
            "manifest": manifest,
            "global": read_yaml("global/custom-rules.yaml") or {"custom_rules": []},
            "categories": read_yaml("categories/manual-categories.yaml") or {"manual_categories": []},
            "scenarios": scenarios_section,
        }
        return snapshot

    def _build_restore_preview(self, current: dict[str, object], target: dict[str, object], *, ref: str = "") -> dict[str, object]:
        sections: list[_RestorePreviewSection] = []
        sections.append(
            self._compare_named_sections(
                "manual_categories",
                current["categories"]["manual_categories"],  # type: ignore[index]
                target["categories"]["manual_categories"],  # type: ignore[index]
                key_fn=_category_key,
            )
        )
        sections.append(
            self._compare_named_sections(
                "global_custom_rules",
                current["global"]["custom_rules"],  # type: ignore[index]
                target["global"]["custom_rules"],  # type: ignore[index]
                key_fn=lambda item: "|".join(_rule_key(item)),
            )
        )
        current_scenarios = current["scenarios"] if isinstance(current.get("scenarios"), dict) else {}
        target_scenarios = target["scenarios"] if isinstance(target.get("scenarios"), dict) else {}
        for scenario_dir in sorted(set(current_scenarios) | set(target_scenarios)):
            current_payload = current_scenarios.get(scenario_dir) or {}
            target_payload = target_scenarios.get(scenario_dir) or {}
            sections.append(
                self._compare_named_sections(
                    f"{scenario_dir}.category_overrides",
                    current_payload.get("category_overrides") or [],
                    target_payload.get("category_overrides") or [],
                    key_fn=_category_key,
                )
            )
            sections.append(
                self._compare_named_sections(
                    f"{scenario_dir}.custom_rules",
                    current_payload.get("custom_rules") or [],
                    target_payload.get("custom_rules") or [],
                    key_fn=lambda item: "|".join(_rule_key(item)),
                )
            )
            sections.append(
                self._compare_named_sections(
                    f"{scenario_dir}.contract_definitions",
                    current_payload.get("contract_definitions") or [],
                    target_payload.get("contract_definitions") or [],
                    key_fn=lambda item: _normalize_text(item.get("id")),
                )
            )
            sections.append(
                self._compare_named_sections(
                    f"{scenario_dir}.contract_views",
                    current_payload.get("contract_views") or [],
                    target_payload.get("contract_views") or [],
                    key_fn=_contract_view_key,
                )
            )
            sections.append(
                self._compare_named_sections(
                    f"{scenario_dir}.pin_groups",
                    current_payload.get("pin_groups") or [],
                    target_payload.get("pin_groups") or [],
                    key_fn=_pin_group_key,
                )
            )
            sections.append(
                self._compare_named_sections(
                    f"{scenario_dir}.catalog_bindings",
                    current_payload.get("catalog_bindings") or [],
                    target_payload.get("catalog_bindings") or [],
                    key_fn=lambda item: "|".join(_binding_key(item)),
                )
            )
        changed = [item.to_dict() for item in sections if item.added or item.removed or item.changed]
        return {
            "ok": True,
            "ref": ref or "",
            "source_digest": _normalize_text((target.get("manifest") or {}).get("digest")),
            "snapshot_digest": _sha256_text(_stable_json(target)),
            "changed": bool(changed),
            "sections": changed,
        }

    def _compare_named_sections(
        self,
        name: str,
        current: list[dict[str, object]],
        target: list[dict[str, object]],
        *,
        key_fn,
    ) -> _RestorePreviewSection:
        current_map = {key_fn(item): item for item in current}
        target_map = {key_fn(item): item for item in target}
        section = _RestorePreviewSection(name=name)
        for key in sorted(set(target_map) - set(current_map)):
            section.added.append(key)
        for key in sorted(set(current_map) - set(target_map)):
            section.removed.append(key)
        for key in sorted(set(current_map) & set(target_map)):
            if _stable_json(current_map[key]) != _stable_json(target_map[key]):
                section.changed.append(key)
        return section

    def _apply_snapshot(self, snapshot: dict[str, object]) -> None:
        with self._restore_operation_lock:
            self._apply_snapshot_serialized(snapshot)

    def _apply_snapshot_serialized(self, snapshot: dict[str, object]) -> None:
        """Apply a policy snapshot through a staged SQLite database.

        Existing repository helpers commit independently because they are also
        used by ordinary management requests.  Running them against a cloned
        database and atomically swapping that file keeps a SIGKILL from
        exposing the reset-then-apply sequence to live readers.  The clone is
        prepared without holding the live repository lock; a change-token CAS
        at promotion retries from a newer live snapshot when a management or
        runtime write raced the preparation, so those writes are never copied
        out of the database by the final replacement.
        """
        max_cas_retries = 3
        for attempt in range(1, max_cas_retries + 1):
            stage_root: Path | None = None
            staged_repo: SqliteRepo | None = None
            try:
                stage_root = Path(mkdtemp(dir=self.repo.root))
                staged_db = stage_root / "data" / "subhub.db"
                baseline = self.repo.backup_database(staged_db, change_token_scope="policy")
                stage_settings = dataclass_replace(self.settings, storage_root=str(stage_root))
                cipher = getattr(self.repo, "_cipher", None)
                staged_repo = SqliteRepo(stage_settings, cipher=cipher)
                staged_service = object.__new__(type(self))
                staged_service.__dict__ = dict(self.__dict__)
                staged_service.repo = staged_repo
                staged_service._suspend_dirty = 0
                staged_service._state_lock = threading.Lock()
                staged_service._apply_snapshot_in_place(snapshot)
                staged_repo.close()
                staged_repo = None
                fault = os.getenv("SUBHUB_RESTORE_FAULT_INJECTION", "").strip() or None
                promotion = self.repo.promote_staged_database(
                    staged_db,
                    expected_change_token=str(baseline.get("change_token") or ""),
                    change_token_scope="policy",
                    fault_injection=fault,
                )
                if bool(promotion.get("promoted")):
                    return
                _logger.warning(
                    "policy restore CAS lost to a concurrent live write; retrying attempt %s/%s",
                    attempt,
                    max_cas_retries,
                )
            except Exception as exc:
                diagnostic = error_detail(exc, "policy_backup_restore", uuid4().hex)
                _logger.error("policy backup restore failed: %s", diagnostic)
                if self.alerts:
                    self.alerts.emit_fatal(
                        "policy_backup.restore",
                        "policy backup restore failed before the database became ready",
                        details=diagnostic,
                    )
                raise
            finally:
                if staged_repo is not None:
                    staged_repo.close()
                if stage_root is not None:
                    shutil.rmtree(stage_root, ignore_errors=True)

        raise RuntimeError("policy backup restore could not promote after concurrent live writes")

    def _apply_snapshot_in_place(self, snapshot: dict[str, object]) -> None:
        self.suspend_dirty_notifications()
        try:
            schema_version = (snapshot.get("manifest") or {}).get("schema_version")
            if schema_version not in {None, "subhub.policy-backup.v1", POLICY_BACKUP_MANIFEST_SCHEMA}:
                raise ValueError("unsupported policy backup schema")
            complete_catalog = schema_version == POLICY_BACKUP_MANIFEST_SCHEMA
            if complete_catalog:
                definitions = {}
                for payload in (snapshot.get("scenarios") or {}).values():
                    for item in payload.get("contract_definitions") or []:
                        contract_id = _normalize_text(item.get("id"))
                        if not contract_id or contract_id in definitions:
                            raise ValueError("v2 contract definitions must have unique nonempty ids")
                        definitions[contract_id] = item
                for source in self.repo.list_standard_sources():
                    target_id = source.resolved_target_contract_id()
                    if target_id:
                        definition = definitions.get(target_id)
                        if definition is None or definition.get("routing_action", "proxy") != "proxy":
                            raise ValueError(f"backup would invalidate standard source {source.id}; rebind before restoring")
            self.repo.reset_policy_backup_owned_state(clear_contracts=complete_catalog)

            manual_categories = snapshot["categories"]["manual_categories"]  # type: ignore[index]
            for item in manual_categories:
                created = self.repo.create_manual_rule_category(
                    _normalize_text(item.get("name")),
                    _normalize_text(item.get("assigned_group")),
                    locked=bool(item.get("locked")),
                )
                if not created:
                    continue
                for rule in item.get("rules") or []:
                    self.repo.save_custom_rule(
                        CustomRule(
                            id=uuid4().hex,
                            rule_type=_normalize_text(rule.get("rule_type")),
                            value=_normalize_text(rule.get("value")),
                            target_group="",
                            category_name=created.name,
                            created_at=_utc_now(),
                        )
                    )

            for item in snapshot["global"]["custom_rules"]:  # type: ignore[index]
                self.repo.save_custom_rule(
                    CustomRule(
                        id=uuid4().hex,
                        rule_type=_normalize_text(item.get("rule_type")),
                        value=_normalize_text(item.get("value")),
                        target_contract_id=_normalize_text(item.get("target_contract_id") or item.get("target_group")),
                        target_group=_normalize_text(item.get("target_group")),
                        category_name=_normalize_text(item.get("category_name")),
                        created_at=_normalize_text(item.get("created_at")) or _utc_now(),
                    )
                )

            scenarios = snapshot["scenarios"] if isinstance(snapshot.get("scenarios"), dict) else {}
            for scenario_dir, payload in scenarios.items():
                metadata = payload.get("metadata") or {}
                scenario_id = _normalize_text(metadata.get("id"))
                if not scenario_id:
                    scenario_id = DEFAULT_SCENARIO_ID if scenario_dir == DEFAULT_SCENARIO_SLUG else scenario_dir
                current = self.repo.get_scenario(scenario_id)
                settings = current.settings if current else {}
                editor_state = current.editor_state if current else {}
                self.repo.save_scenario(
                    ScenarioProfile(
                        id=scenario_id,
                        slug=_normalize_text(metadata.get("slug")) or (DEFAULT_SCENARIO_SLUG if scenario_id == DEFAULT_SCENARIO_ID else scenario_id),
                        name=_normalize_text(metadata.get("name")) or (current.name if current else "未命名场景"),
                        description=_normalize_text(metadata.get("description")) or (current.description if current else ""),
                        enabled=bool(metadata.get("enabled", True if current is None else current.enabled)),
                        sort_order=int(metadata.get("sort_order") or (current.sort_order if current else 0)),
                        settings=settings,
                        editor_state=editor_state,
                        updated_at=current.updated_at if current else "",
                    )
                )

            if not complete_catalog:
                # v1 omitted the fixed preset definitions. Resolve only IDs
                # actually present in that explicit historical snapshot.
                legacy_ids = {
                    _normalize_text(item.get("contract_id"))
                    for payload in scenarios.values()
                    for item in [*(payload.get("contract_views") or []), *(payload.get("catalog_bindings") or [])]
                }
                legacy_ids.update(
                    _normalize_text(item.get("target_contract_id"))
                    for item in (snapshot.get("global") or {}).get("custom_rules") or []
                )
                for template in initial_route_contract_templates():
                    if template.id in legacy_ids and self.repo.get_route_contract(template.id) is None:
                        self.repo.create_route_contract(template)

            for scenario_dir, payload in scenarios.items():
                metadata = payload.get("metadata") or {}
                scenario_id = _normalize_text(metadata.get("id"))
                if not scenario_id:
                    scenario_id = DEFAULT_SCENARIO_ID if scenario_dir == DEFAULT_SCENARIO_SLUG else scenario_dir
                owner_scenario_id = "" if scenario_id == DEFAULT_SCENARIO_ID else scenario_id
                for item in payload.get("contract_definitions") or []:
                    contract_id = _normalize_text(item.get("id"))
                    if not contract_id:
                        raise ValueError("contract definition id is required")
                    if complete_catalog and not _normalize_text(item.get("routing_action")):
                        raise ValueError("routing_action is required in v2 contract definitions")
                    existing_contract = self.repo.get_route_contract(contract_id)
                    contract_payload = RouteContract(
                        id=contract_id,
                        display_name=_normalize_text(item.get("display_name")),
                        description=_normalize_text(item.get("description")),
                        routing_action=_normalize_text(item.get("routing_action")) or ("direct" if contract_id == "direct" else "reject" if contract_id == "ad_block" else "proxy"),
                        strategy_type=_normalize_text(item.get("strategy_type")) or "strict",
                        primary_pools=[_normalize_text(pool) for pool in item.get("primary_pools") or []],
                        fallback_pools=[_normalize_text(pool) for pool in item.get("fallback_pools") or []],
                        failure_action=_normalize_text(item.get("failure_action")) or "interrupt",
                        editable=True,
                        enabled=bool(item.get("enabled", True)),
                        sort_order=int(item.get("sort_order") or 0),
                        owner_scenario_id=owner_scenario_id,
                        is_system=False,
                        updated_at=_normalize_text(item.get("updated_at")),
                    )
                    if existing_contract is None:
                        self.repo.create_route_contract(contract_payload)
                    else:
                        self.repo.save_route_contract(contract_payload)

            for scenario_dir, payload in scenarios.items():
                metadata = payload.get("metadata") or {}
                scenario_id = _normalize_text(metadata.get("id"))
                if not scenario_id:
                    scenario_id = DEFAULT_SCENARIO_ID if scenario_dir == DEFAULT_SCENARIO_SLUG else scenario_dir
                for item in payload.get("contract_views") or []:
                    contract_id = _normalize_text(item.get("contract_id"))
                    if not contract_id or not self.repo.get_route_contract(contract_id):
                        raise ValueError(f"unknown contract_id in backup: {contract_id or 'missing'}")
                    self.repo.save_scenario_route_contract_view(
                        scenario_id,
                        RouteContractView(
                            scenario_id=scenario_id,
                            contract_id=contract_id,
                            display_name=_normalize_text(item.get("display_name")),
                            description=_normalize_text(item.get("description")),
                            llm_routing_intent=_normalize_text(item.get("llm_routing_intent")),
                            enabled=bool(item.get("enabled", True)),
                            sort_order=int(item.get("sort_order") or 0),
                            is_default=bool(item.get("is_default")),
                            updated_at=_normalize_text(item.get("updated_at")),
                        ),
                    )

            default_payload = scenarios.get(DEFAULT_SCENARIO_SLUG) or {}
            for group in default_payload.get("pin_groups") or []:
                self.repo.create_pin_group(
                    _normalize_text(group.get("group_name")),
                    mode=_normalize_text(group.get("mode")) or "standard",
                    description=_normalize_text(group.get("description")),
                )
            if default_payload.get("pin_groups"):
                self.repo.save_pin_group_order(default_payload.get("pin_groups") or [])

            for binding in default_payload.get("catalog_bindings") or []:
                self.repo.save_service_catalog_entry(
                    ServiceCatalogEntry(
                        category_name=_normalize_text(binding.get("category_name")),
                        catalog_group=_normalize_text(binding.get("catalog_group")),
                        contract_id=_normalize_text(binding.get("contract_id")),
                        sort_order=int(binding.get("sort_order") or 0),
                        source="manual",
                    )
                )

            for state in default_payload.get("category_overrides") or []:
                name = _normalize_text(state.get("name"))
                assigned_group = _normalize_text(state.get("assigned_group"))
                self.repo.set_rule_category_override_group(name, assigned_group)
                if bool(state.get("locked")):
                    self.repo.update_rule_category_locked(
                        name,
                        True,
                        lock_source=_normalize_text(state.get("lock_source")) or "manual",
                    )

            for item in default_payload.get("custom_rules") or []:
                self.repo.save_scenario_custom_rule(
                    DEFAULT_SCENARIO_ID,
                    CustomRule(
                        id=uuid4().hex,
                        rule_type=_normalize_text(item.get("rule_type")),
                        value=_normalize_text(item.get("value")),
                        target_contract_id=_normalize_text(item.get("target_contract_id") or item.get("target_group")),
                        target_group=_normalize_text(item.get("target_group")),
                        category_name=_normalize_text(item.get("category_name")),
                        created_at=_normalize_text(item.get("created_at")) or _utc_now(),
                    ),
                )

            for scenario_dir, payload in scenarios.items():
                metadata = payload.get("metadata") or {}
                scenario_id = _normalize_text(metadata.get("id"))
                if not scenario_id:
                    scenario_id = DEFAULT_SCENARIO_ID if scenario_dir == DEFAULT_SCENARIO_SLUG else scenario_dir
                if scenario_id == DEFAULT_SCENARIO_ID:
                    continue
                for group in payload.get("pin_groups") or []:
                    self.repo.create_scenario_pin_group(
                        scenario_id,
                        _normalize_text(group.get("group_name")),
                        mode=_normalize_text(group.get("mode")) or "standard",
                        description=_normalize_text(group.get("description")),
                    )
                if payload.get("pin_groups"):
                    self.repo.save_scenario_pin_group_order(scenario_id, payload.get("pin_groups") or [])
                for binding in payload.get("catalog_bindings") or []:
                    self.repo.save_scenario_service_catalog_entry(
                        scenario_id,
                        ServiceCatalogEntry(
                            category_name=_normalize_text(binding.get("category_name")),
                            catalog_group=_normalize_text(binding.get("catalog_group")),
                            contract_id=_normalize_text(binding.get("contract_id")),
                            sort_order=int(binding.get("sort_order") or 0),
                            source="manual",
                        )
                    )
                for state in payload.get("category_overrides") or []:
                    name = _normalize_text(state.get("name"))
                    assigned_group = _normalize_text(state.get("assigned_group"))
                    self.repo.update_scenario_category_assignment(scenario_id, name, assigned_group)
                    if bool(state.get("locked")):
                        self.repo.update_scenario_category_locked(
                            scenario_id,
                            name,
                            True,
                            lock_source=_normalize_text(state.get("lock_source")) or "manual",
                        )
                for item in payload.get("custom_rules") or []:
                    self.repo.save_scenario_custom_rule(
                        scenario_id,
                        CustomRule(
                            id=uuid4().hex,
                            rule_type=_normalize_text(item.get("rule_type")),
                            value=_normalize_text(item.get("value")),
                            target_contract_id=_normalize_text(item.get("target_contract_id") or item.get("target_group")),
                            target_group=_normalize_text(item.get("target_group")),
                            category_name=_normalize_text(item.get("category_name")),
                            created_at=_normalize_text(item.get("created_at")) or _utc_now(),
                        ),
                    )
            if complete_catalog:
                for source in self.repo.list_standard_sources():
                    target_id = source.resolved_target_contract_id()
                    if not target_id:
                        continue
                    definition = self.repo.get_route_contract(target_id)
                    contract = scenario_route_contract(self.repo, definition.owner_scenario_id or DEFAULT_SCENARIO_ID, target_id) if definition else None
                    if contract is None or not contract.can_bind_standard_source():
                        raise ValueError(f"backup would invalidate standard source {source.id}; rebind before restoring")
        finally:
            self.resume_dirty_notifications()
