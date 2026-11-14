from __future__ import annotations

import json
import hashlib
import os
import signal
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.storage.base import standard_source_diagnostics_key
from app.services.field_cipher import FieldCipher
from app.services.subscription_ids import generate_public_subscription_id
from app.models import (
    BUSINESS_GROUP_MODE_AD_BLOCK,
    BUSINESS_GROUP_MODE_STANDARD,
    BUSINESS_GROUP_MODES,
    CONTRACT_AD_BLOCK,
    CONTRACT_BULK,
    CONTRACT_CHAIN_HOME,
    CONTRACT_DIRECT,
    CONTRACT_DISPLAY_NAMES,
    CONTRACT_FAILURE_ACTIONS,
    CONTRACT_FAILURE_INTERRUPT,
    CONTRACT_HQ_PREMIUM,
    CONTRACT_HQ_STANDARD,
    CONTRACT_ID_TO_LEGACY_GROUP,
    CONTRACT_MEDIUM,
    CONTRACT_STRATEGIES,
    CONTRACT_STRATEGY_FAILOVER,
    CONTRACT_STRATEGY_STRICT,
    DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE,
    GeneralProfile,
    POOL_BULK,
    POOL_CHAIN_HOME,
    POOL_DIRECT,
    POOL_HQ_PREMIUM,
    POOL_HQ_STANDARD,
    POOL_IDS,
    POOL_MEDIUM,
    PoolStatus,
    RULE_CATEGORY_TYPE_AUTO,
    RULE_CATEGORY_TYPE_MANUAL,
    RULE_CATEGORY_TYPES,
    RULE_DIRECTNESS_CHOICES,
    RULE_DIRECTNESS_DIRECT,
    RULE_DIRECTNESS_PROXY,
    RULE_DIRECTNESS_REVIEW_STATUSES,
    RULE_DIRECTNESS_REVIEW_STATUS_PENDING,
    RULE_LOCK_SOURCE_MANUAL,
    RULE_LOCK_SOURCE_SYSTEM,
    RULE_LOCK_SOURCES,
    ROUTE_NATIVE_DIRECT_TARGET,
    ROUTE_NATIVE_REJECT_TARGET,
    ROUTE_RENDERER_RESERVED_GROUP_NAMES,
    STANDARD_SOURCE_AUTO_PULL_FAILURE_EXPIRED_THRESHOLD,
    STANDARD_SOURCE_INGEST_KINDS,
    STANDARD_SOURCE_INGEST_REMOTE_SUBSCRIPTION,
    STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT,
    STANDARD_SOURCE_MODE_ROUTE_CONTRACT,
    STANDARD_SOURCE_MODES,
    STANDARD_SOURCE_PULL_NETWORK_MODES,
    STANDARD_SOURCE_QR_FIELDS,
    QUALITY_GROUPS,
    POOL_ID_TO_LEGACY_QUALITY,
    RESERVED_ROUTE_ACTION_IDS,
    ROUTE_ACTION_DIRECT,
    ROUTE_ACTION_PROXY,
    ROUTE_ACTION_REJECT,
    ROUTE_ACTIONS,
    RouteContract,
    RouteContractView,
    ServiceCatalogEntry,
    CustomRule,
    DeviceSubscription,
    GoRelayAccount,
    GoRelayAccountSnapshot,
    GoRelayAccountSnapshotPayload,
    GoRelayDeviceProfile,
    GoRelayDeviceSubscription,
    GoRelayDomainBinding,
    GoRelayDomainImportHistory,
    GoRelayEntryMultiplierOverride,
    GoRelaySource,
    NodeRecord,
    RuleCategory,
    RuleCategoryDirectnessReview,
    ScenarioProfile,
    StandardSource,
    StandardSourceQrAsset,
    contract_description,
    contract_display_name,
    contract_legacy_group,
    normalize_contract_id,
    resolve_legacy_route_target,
    normalize_route_action,
    normalize_standard_source_ingest_kind,
    normalize_standard_source_mode,
)
from app.services.lazycat_profile import (
    backfill_legacy_mihomo_mainline_settings,
    normalize_lazycat_profile_settings,
)
from app.services.profile_editor_schema import (
    default_profile_editor_state,
    normalize_profile_editor_state,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _json_loads(text: str) -> Any:
    return json.loads(text) if text else None


def _normalize_business_group_mode(value: object) -> str:
    text = str(value or "").strip()
    return text if text in BUSINESS_GROUP_MODES else BUSINESS_GROUP_MODE_STANDARD


_SCENARIO_CATALOG_GROUP_INHERIT = "__scenario_inherit__"

_POLICY_BACKUP_STATE_KEY = "policy_backup.state"
_POLICY_BACKUP_OUTBOX_PENDING = "pending"
_POLICY_BACKUP_OUTBOX_ACKED = "acked"


_SYSTEM_ROUTE_CONTRACT_SPECS: tuple[dict[str, object], ...] = (
    {
        "id": CONTRACT_DIRECT,
        "display_name": contract_display_name(CONTRACT_DIRECT),
        "description": contract_description(CONTRACT_DIRECT),
        "strategy_type": CONTRACT_STRATEGY_STRICT,
        "primary_pools": [],
        "fallback_pools": [],
        "failure_action": CONTRACT_FAILURE_INTERRUPT,
        "routing_action": ROUTE_ACTION_DIRECT,
        "editable": True,
        "enabled": True,
        "sort_order": 0,
        "is_system": False,
    },
    {
        "id": CONTRACT_HQ_PREMIUM,
        "display_name": contract_display_name(CONTRACT_HQ_PREMIUM),
        "description": contract_description(CONTRACT_HQ_PREMIUM),
        "strategy_type": CONTRACT_STRATEGY_FAILOVER,
        "primary_pools": [POOL_HQ_PREMIUM],
        "fallback_pools": [POOL_HQ_STANDARD, POOL_CHAIN_HOME],
        "failure_action": CONTRACT_FAILURE_INTERRUPT,
        "routing_action": ROUTE_ACTION_PROXY,
        "editable": True,
        "enabled": True,
        "sort_order": 1,
        "is_system": False,
    },
    {
        "id": CONTRACT_HQ_STANDARD,
        "display_name": contract_display_name(CONTRACT_HQ_STANDARD),
        "description": contract_description(CONTRACT_HQ_STANDARD),
        "strategy_type": CONTRACT_STRATEGY_FAILOVER,
        "primary_pools": [POOL_HQ_STANDARD],
        "fallback_pools": [POOL_HQ_PREMIUM, POOL_CHAIN_HOME],
        "failure_action": CONTRACT_FAILURE_INTERRUPT,
        "routing_action": ROUTE_ACTION_PROXY,
        "editable": True,
        "enabled": True,
        "sort_order": 2,
        "is_system": False,
    },
    {
        "id": CONTRACT_MEDIUM,
        "display_name": contract_display_name(CONTRACT_MEDIUM),
        "description": contract_description(CONTRACT_MEDIUM),
        "strategy_type": CONTRACT_STRATEGY_STRICT,
        "primary_pools": [POOL_MEDIUM],
        "fallback_pools": [],
        "failure_action": CONTRACT_FAILURE_INTERRUPT,
        "routing_action": ROUTE_ACTION_PROXY,
        "editable": True,
        "enabled": True,
        "sort_order": 3,
        "is_system": False,
    },
    {
        "id": CONTRACT_BULK,
        "display_name": contract_display_name(CONTRACT_BULK),
        "description": contract_description(CONTRACT_BULK),
        "strategy_type": CONTRACT_STRATEGY_STRICT,
        "primary_pools": [POOL_BULK],
        "fallback_pools": [],
        "failure_action": CONTRACT_FAILURE_INTERRUPT,
        "routing_action": ROUTE_ACTION_PROXY,
        "editable": True,
        "enabled": True,
        "sort_order": 4,
        "is_system": False,
    },
    {
        "id": CONTRACT_CHAIN_HOME,
        "display_name": contract_display_name(CONTRACT_CHAIN_HOME),
        "description": contract_description(CONTRACT_CHAIN_HOME),
        "strategy_type": CONTRACT_STRATEGY_STRICT,
        "primary_pools": [POOL_CHAIN_HOME],
        "fallback_pools": [],
        "failure_action": CONTRACT_FAILURE_INTERRUPT,
        "routing_action": ROUTE_ACTION_PROXY,
        "editable": True,
        "enabled": True,
        "sort_order": 5,
        "is_system": False,
    },
    {
        "id": CONTRACT_AD_BLOCK,
        "display_name": contract_display_name(CONTRACT_AD_BLOCK),
        "description": contract_description(CONTRACT_AD_BLOCK),
        "strategy_type": CONTRACT_STRATEGY_STRICT,
        "primary_pools": [],
        "fallback_pools": [],
        "failure_action": CONTRACT_FAILURE_INTERRUPT,
        "routing_action": ROUTE_ACTION_REJECT,
        "editable": True,
        "enabled": True,
        "sort_order": 6,
        "is_system": False,
    },
)
_DEFAULT_GENERAL_PROFILE_ID = "lazycat-default"
_DEFAULT_SCENARIO_ID = "scenario-default"
_DEFAULT_SCENARIO_SLUG = "default"
_ROUTE_CONTRACTS_SEEDED_SETTING = "route_contracts.seeded"
_SCENARIO_ROUTE_CONTRACT_VIEWS_SEEDED_SETTING = "scenario_route_contract_views.seeded"


def _default_route_contracts() -> list[RouteContract]:
    return [RouteContract(**dict(item)) for item in _SYSTEM_ROUTE_CONTRACT_SPECS]


def initial_route_contract_templates() -> list[RouteContract]:
    """Return the historical initial templates for explicit legacy restores."""
    return [replace(item) for item in _default_route_contracts()]


class _TransactionConnection(sqlite3.Connection):
    defer_commit = False

    def commit(self) -> None:
        if not self.defer_commit:
            super().commit()


class SqliteRepo:
    def __init__(self, settings: Settings, cipher: FieldCipher | None = None) -> None:
        self.settings = settings
        self._cipher = cipher
        # A restore closes and reopens the SQLite connection while holding the
        # repository lock.  RLock keeps that operation atomic without making
        # every existing repository helper aware of the swap boundary.
        self._lock = threading.RLock()
        self._transaction_notifications: set[str] = set()
        self._policy_backup_notifier: Callable[[str], None] | None = None
        self._route_contracts_table_preexisting = False

        root = Path(settings.storage_root)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"storage_root is not writable: {root}. "
                "Set STORAGE_ROOT=./var for local dev; STORAGE_ROOT=/lzcapp/var for LazyCat."
            ) from exc

        self.root = root
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "subhub.db"
        self._promotion_journal_path = self.data_dir / ".subhub-db-promotion.json"
        # Promotion closes the live connection before replacing its inode.
        # A SIGKILL in that small window must not turn a committed WAL into
        # data loss.  Recover a journaled staged database before opening the
        # active connection, then remove only stale unreferenced stage files.
        self._recover_pending_promotion()
        if not self._promotion_journal_path.exists():
            # A SIGKILL before the promotion journal is durable can leave only
            # an unreferenced staged file.  It is safe to remove those
            # app-owned artifacts; the active database is never selected by
            # this glob.
            for staged_path in self.data_dir.glob(".subhub-restore-*.db"):
                try:
                    staged_path.unlink()
                except OSError:
                    pass
        # ``PRAGMA data_version`` is scoped to one observer connection and
        # therefore resets when an atomic restore reopens that connection.
        # Include a process-unique generation and replacement counter in the
        # CAS token so two overlapping staged restores cannot both validate
        # against the same pre-replacement identity.
        self._database_generation = uuid4().hex
        self._connection_replacement_count = 0
        self._conn = self._open_connection(self.db_path)
        self._initialize_database()
        # A separate observer connection gives staged restore a cheap CAS
        # token.  SQLite's data_version changes when the application's main
        # connection (or another process) commits, while querying it does not
        # hold the application writer lock during long staging work.
        self._cas_conn = self._open_connection(self.db_path)

    @staticmethod
    def _open_connection(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(path), timeout=30, check_same_thread=False, factory=_TransactionConnection
        )
        connection.row_factory = sqlite3.Row
        # Keep every reopened connection (including a post-CAS promotion
        # connection) on the same referential-integrity contract as the
        # initial repository connection.  ``PRAGMA foreign_keys`` is per
        # connection and is otherwise reset to OFF after an atomic swap.
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _write_promotion_journal(
        self,
        staged_path: Path,
        restore_id: str,
        *,
        live_files_sha256: str = "",
    ) -> None:
        """Durably record the staged file before touching the live database.

        The journal is deliberately a tiny app-owned file in the same
        directory as the active database.  Its atomic rename and directory
        fsync make the staged path discoverable after a process-kill even if
        the live WAL/SHM pair has already been closed or removed.
        """
        journal_tmp = self.data_dir / f".{self._promotion_journal_path.name}.{uuid4().hex}.tmp"
        payload = {
            "version": 1,
            "db_path": str(self.db_path.resolve()),
            "staged_path": str(staged_path.resolve()),
            "staged_sha256": self._file_sha256(staged_path),
            "live_files_sha256": str(live_files_sha256 or ""),
            "live_main_sha256": (
                self._file_sha256(self.db_path) if self.db_path.is_file() else ""
            ),
            "phase": "prepared",
            "restore_id": str(restore_id or ""),
        }
        try:
            journal_tmp.write_text(_json_dumps(payload), encoding="utf-8")
            self._fsync_file(journal_tmp)
            os.replace(journal_tmp, self._promotion_journal_path)
            self._fsync_directory(self.data_dir)
        finally:
            if journal_tmp.exists():
                journal_tmp.unlink()

    def _mark_promotion_installed(self) -> None:
        """Record that the atomic main-file replacement has completed."""
        try:
            payload = _json_loads(self._promotion_journal_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            payload["phase"] = "installed"
            journal_tmp = self.data_dir / f".{self._promotion_journal_path.name}.{uuid4().hex}.tmp"
            try:
                journal_tmp.write_text(_json_dumps(payload), encoding="utf-8")
                self._fsync_file(journal_tmp)
                os.replace(journal_tmp, self._promotion_journal_path)
                self._fsync_directory(self.data_dir)
            finally:
                if journal_tmp.exists():
                    journal_tmp.unlink()
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            # The prepared journal plus staged hash remains sufficient for a
            # startup that dies immediately after os.replace.
            return

    def _clear_promotion_journal(self) -> None:
        try:
            self._promotion_journal_path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return
        self._fsync_directory(self.data_dir)

    def _remove_live_sidecars(self) -> None:
        failures: list[str] = []
        for sidecar in (Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm")):
            try:
                sidecar.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                failures.append(f"{sidecar.name}: {exc}")
        if failures:
            # A restored main file paired with the old WAL can make SQLite
            # replay transactions from the pre-restore inode.  Never let a
            # failed unlink look like a completed promotion: callers must
            # leave the journal durable and fail closed until a later startup
            # can remove the sidecars.
            raise RuntimeError(
                "SQLite promotion could not remove live sidecars: " + "; ".join(failures)
            )

    def _read_promotion_journal(self) -> dict[str, object] | None:
        if not self._promotion_journal_path.is_file():
            return None
        payload = _json_loads(self._promotion_journal_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("SQLite promotion journal is not an object")
        return payload

    def _promotion_state_after_exception(self, staged_path: Path) -> str:
        """Classify an interrupted promotion before reconnecting SQLite.

        ``os.replace`` is atomic but the process can die before the journal is
        changed from ``prepared`` (for example while fsyncing the new main
        file).  A missing stage therefore does not by itself prove that the
        replacement happened.  The staged hash in the journal is the proof;
        only after that proof and successful sidecar cleanup may a caller
        reopen the repository.
        """
        try:
            journal = self._read_promotion_journal()
        except (OSError, ValueError, TypeError, json.JSONDecodeError, RuntimeError):
            # The caller is already on an exception path.  A malformed or
            # unreadable journal cannot prove which inode is active, so leave
            # the repository closed instead of masking the original failure
            # with a guessed reconnect.
            return "unknown"
        stage_exists = staged_path.is_file()
        if journal is None:
            if stage_exists:
                return "not_installed"
            return "not_started"

        journal_stage = Path(str(journal.get("staged_path") or "")).expanduser().resolve()
        if journal_stage != staged_path.resolve():
            return "unknown"
        phase = str(journal.get("phase") or "prepared").strip().lower()
        if stage_exists:
            if phase == "installed":
                return "unknown"
            # The atomic replacement did not consume the stage.  The active
            # database/WAL pair is still the old, coherent pair.
            self._clear_promotion_journal()
            return "not_installed"

        staged_sha256 = str(journal.get("staged_sha256") or "").strip().lower()
        current_sha256 = (
            self._file_sha256(self.db_path).lower() if self.db_path.is_file() else ""
        )
        if not staged_sha256 or current_sha256 != staged_sha256:
            # The stage is gone but the active main file cannot prove that the
            # atomic replacement completed.  Reopening it could replay an old
            # WAL over an unrelated inode, so fail closed with the journal
            # untouched for operator/startup reconciliation.
            return "unknown"

        # The staged hash proves that os.replace installed the new main file,
        # regardless of whether the installed marker fsync completed.  The
        # old sidecars must still be removed successfully before reconnecting.
        try:
            self._remove_live_sidecars()
        except (OSError, RuntimeError):
            return "unknown"
        if phase != "installed":
            self._mark_promotion_installed()
        self._clear_promotion_journal()
        return "installed"

    def _reopen_after_promotion(self) -> None:
        if self._conn is None:
            self._conn = self._open_connection(self.db_path)
            self._initialize_database()
        if self._cas_conn is None:
            self._cas_conn = self._open_connection(self.db_path)

    def _recover_pending_promotion(self) -> None:
        """Complete or safely abandon an interrupted staged promotion."""
        journal_path = self._promotion_journal_path
        if not journal_path.is_file():
            return
        try:
            payload = self._read_promotion_journal()
            if payload is None:
                return
            target = Path(str(payload.get("db_path") or "")).expanduser().resolve()
            staged = Path(str(payload.get("staged_path") or "")).expanduser().resolve()
            if target != self.db_path.resolve() or not str(payload.get("staged_path") or ""):
                raise RuntimeError("SQLite promotion journal has an invalid database target")

            # If the staged file is still present, the swap did not complete.
            # Verify it before replacing anything.  Replace the complete
            # main file first and only then remove old sidecars, preserving a
            # recoverable database/WAL pair across every kill window.
            if staged.is_file():
                metadata = self.inspect_database_file(staged)
                if not bool(metadata.get("ok")):
                    return
                expected_live = str(payload.get("live_files_sha256") or "").strip().lower()
                if expected_live:
                    current_live = self._live_database_files_digest().lower()
                    if current_live != expected_live:
                        # Closing the last SQLite connection can passively
                        # checkpoint and remove a WAL/SHM pair after the
                        # journal is durable.  That benign transition keeps
                        # the main inode byte-for-byte identical.  Accept it
                        # only when both sidecars are gone and the main hash
                        # still matches; any remaining sidecar or main-file
                        # change proves that another writer may have advanced
                        # the live database, so do not overwrite it.
                        expected_main = str(payload.get("live_main_sha256") or "").strip().lower()
                        current_main = (
                            self._file_sha256(self.db_path).lower()
                            if self.db_path.is_file()
                            else ""
                        )
                        sidecars_present = any(
                            Path(f"{self.db_path}{suffix}").is_file()
                            for suffix in ("-wal", "-shm")
                        )
                        if (
                            not expected_main
                            or current_main != expected_main
                            or sidecars_present
                        ):
                            # A different process committed after the journal
                            # was prepared.  Do not overwrite that newer
                            # state; leave the durable obligation for an
                            # explicit reconcile.
                            return
                os.replace(staged, self.db_path)
                self._fsync_file(self.db_path)
                self._fsync_directory(self.data_dir)
                self._remove_live_sidecars()

            # A journal with no staged file normally means os.replace
            # completed before the previous process died.  Verify the active
            # file identity before deleting its sidecars: if an external
            # cleanup removed the stage before replacement, the old WAL must
            # remain available rather than being mistaken for a completed
            # promotion.
            staged_sha256 = str(payload.get("staged_sha256") or "").strip().lower()
            if not staged_sha256 or not self.db_path.is_file():
                raise RuntimeError(
                    "SQLite promotion journal cannot prove the installed main database"
                )
            if self._file_sha256(self.db_path).lower() != staged_sha256:
                raise RuntimeError(
                    "SQLite promotion journal has an ambiguous installed main database"
                )
            self._remove_live_sidecars()
            self._fsync_directory(self.data_dir)
            self._clear_promotion_journal()
        except RuntimeError:
            # Sidecar failures and ambiguous replacement outcomes are
            # intentionally fatal.  Opening SQLite in either state could
            # replay a WAL belonging to the pre-replacement inode.
            raise
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            # Leave the journal in place, but do not open SQLite while the
            # replacement outcome or sidecar cleanup is unresolved.  An old
            # WAL paired with the newly installed main file can replay
            # pre-restore pages and make a startup appear healthy while
            # silently returning stale data.
            raise RuntimeError(
                "SQLite promotion recovery failed; repository left unopened"
            ) from exc

    def _initialize_database(self) -> None:
        self._init_db()
        self._migrate_profile_editor_state()
        self._migrate_gorelay_sources_to_accounts()
        self._migrate_encrypt_plaintext()
        self._seed_route_contracts()
        self._migrate_general_profile_defaults()
        self._pin_existing_mihomo_mainline_defaults()
        self._migrate_default_scenario()
        self._seed_scenario_route_contract_views()
        self._backfill_service_catalog_entries()

    def set_policy_backup_notifier(self, callback: Callable[[str], None] | None) -> None:
        self._policy_backup_notifier = callback

    @contextmanager
    def restore_barrier(self) -> Iterator[None]:
        """Protect a short repository critical section during restore.

        All live ``SqliteRepo`` reads and writes use ``_lock``.  Staged policy
        restores deliberately do not hold this context across backup or
        snapshot application: they prepare an isolated database and use the
        short CAS promotion in :meth:`promote_staged_database`, so an async
        heartbeat or management request cannot wait behind long work.  The
        context remains for callers that need to compose a short atomic
        repository operation, and its reentrant lock keeps nested helpers
        safe.
        """
        with self._lock:
            yield

    @contextmanager
    def policy_transaction(self) -> Iterator["SqliteRepo"]:
        """Group policy writes and notify only after the commit succeeds."""
        with self.transaction():
            yield self

    def _notify_policy_backup(self, reason: str) -> None:
        with self._lock:
            if self._conn.defer_commit:
                self._transaction_notifications.add(reason)
                return
        self._call_policy_backup_notifier(reason)

    def _call_policy_backup_notifier(self, reason: str) -> None:
        callback = self._policy_backup_notifier
        if callback is None:
            return
        try:
            callback(reason)
        except Exception:
            return

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit repository writes together and notify only after success."""
        notifications: list[str] = []
        with self._lock:
            if self._conn.defer_commit:
                raise RuntimeError("nested repository transactions are not supported")
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.defer_commit = True
            try:
                yield
                sqlite3.Connection.commit(self._conn)
                notifications = sorted(self._transaction_notifications)
            except BaseException:
                sqlite3.Connection.rollback(self._conn)
                raise
            finally:
                self._conn.defer_commit = False
                self._transaction_notifications.clear()
        for reason in notifications:
            self._call_policy_backup_notifier(reason)

    # -- field-level encryption helpers --

    def _enc(self, value: str | None) -> str:
        """Encrypt a value before writing to the database."""
        if not value:
            return value or ""
        if self._cipher is None:
            return value
        return self._cipher.encrypt(value)

    def _dec(self, value: str | None) -> str:
        """Decrypt a value after reading from the database."""
        if not value:
            return value or ""
        if self._cipher is None:
            return value
        return self._cipher.decrypt(value)

    def _has_column(self, table: str, column: str) -> bool:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(str(row["name"]) == column for row in rows)

    def _init_db(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA foreign_keys=ON;")
            self._route_contracts_table_preexisting = (
                cur.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='route_contracts'"
                ).fetchone()
                is not None
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gorelay_sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    login_url TEXT NOT NULL,
                    gorelay_username TEXT NOT NULL,
                    gorelay_password TEXT NOT NULL,
                    proxy_username TEXT NOT NULL DEFAULT '',
                    proxy_password TEXT NOT NULL DEFAULT '',
                    selectors_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gorelay_accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    login_url TEXT NOT NULL,
                    rules_url TEXT NOT NULL DEFAULT '',
                    gorelay_username TEXT NOT NULL,
                    gorelay_password TEXT NOT NULL,
                    proxy_username_default TEXT NOT NULL DEFAULT '',
                    proxy_password_default TEXT NOT NULL DEFAULT '',
                    selectors_json TEXT NOT NULL DEFAULT '{}',
                    mcp_url TEXT NOT NULL DEFAULT '',
                    auth_header TEXT NOT NULL DEFAULT '',
                    login_tool TEXT NOT NULL DEFAULT 'auth_login',
                    nodes_tool TEXT NOT NULL DEFAULT 'list_nodes',
                    login_args_json TEXT NOT NULL DEFAULT '{"username":"{username}","password":"{password}"}',
                    nodes_args_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                )
                """
            )
            if not self._has_column("gorelay_accounts", "mcp_url"):
                cur.execute(
                    "ALTER TABLE gorelay_accounts ADD COLUMN mcp_url TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("gorelay_accounts", "auth_header"):
                cur.execute(
                    "ALTER TABLE gorelay_accounts ADD COLUMN auth_header TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("gorelay_accounts", "login_tool"):
                cur.execute(
                    "ALTER TABLE gorelay_accounts ADD COLUMN login_tool TEXT NOT NULL DEFAULT 'auth_login'"
                )
            if not self._has_column("gorelay_accounts", "nodes_tool"):
                cur.execute(
                    "ALTER TABLE gorelay_accounts ADD COLUMN nodes_tool TEXT NOT NULL DEFAULT 'list_nodes'"
                )
            if not self._has_column("gorelay_accounts", "login_args_json"):
                cur.execute(
                    "ALTER TABLE gorelay_accounts ADD COLUMN login_args_json TEXT NOT NULL DEFAULT '{\"username\":\"{username}\",\"password\":\"{password}\"}'"
                )
            if not self._has_column("gorelay_accounts", "nodes_args_json"):
                cur.execute(
                    "ALTER TABLE gorelay_accounts ADD COLUMN nodes_args_json TEXT NOT NULL DEFAULT '{}'"
                )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gorelay_device_profiles (
                    account_id TEXT NOT NULL,
                    device_key TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    proxy_username_override TEXT NOT NULL DEFAULT '',
                    proxy_password_override TEXT NOT NULL DEFAULT '',
                    strategy_preset TEXT NOT NULL DEFAULT 'balanced',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, device_key)
                )
                """
            )
            if not self._has_column("gorelay_device_profiles", "strategy_preset"):
                cur.execute(
                    "ALTER TABLE gorelay_device_profiles ADD COLUMN strategy_preset TEXT NOT NULL DEFAULT 'balanced'"
                )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gorelay_device_subscriptions (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    device_key TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    public_id TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_seen_at TEXT,
                    last_seen_ip TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(account_id, device_key)
                )
                """
            )
            if not self._has_column("gorelay_device_subscriptions", "public_id"):
                cur.execute(
                    "ALTER TABLE gorelay_device_subscriptions ADD COLUMN public_id TEXT NOT NULL DEFAULT ''"
                )
            for row in cur.execute(
                "SELECT id FROM gorelay_device_subscriptions WHERE COALESCE(public_id,'')=''"
            ).fetchall():
                cur.execute(
                    "UPDATE gorelay_device_subscriptions SET public_id=? WHERE id=?",
                    (generate_public_subscription_id(), str(row["id"])),
                )
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_gorelay_device_subscriptions_public_id ON gorelay_device_subscriptions(public_id)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gorelay_domain_bindings (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    entry_name TEXT NOT NULL,
                    isp TEXT NOT NULL,
                    ip_version TEXT NOT NULL,
                    host_value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(account_id, entry_name, isp, ip_version)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gorelay_domain_import_histories (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    parsed_count INTEGER NOT NULL,
                    changed_count INTEGER NOT NULL,
                    multiplier_hint_count INTEGER NOT NULL,
                    applied_bindings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gorelay_account_snapshots (
                    account_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    node_count INTEGER NOT NULL,
                    device_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (account_id, snapshot_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gorelay_active_snapshots (
                    account_id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gorelay_entry_multiplier_overrides (
                    account_id TEXT NOT NULL,
                    entry_key TEXT NOT NULL,
                    multiplier TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(account_id, entry_key)
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS standard_sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    clash_url TEXT NOT NULL,
                    shadowrocket_url TEXT NOT NULL,
                    surge_url TEXT NOT NULL DEFAULT '',
                    login_url TEXT NOT NULL DEFAULT '',
                    quality_group TEXT NOT NULL,
                    target_contract_id TEXT NOT NULL DEFAULT '',
                    source_mode TEXT NOT NULL DEFAULT 'route_contract',
                    ingest_kind TEXT NOT NULL DEFAULT 'remote_subscription',
                    manual_nodes_text TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_pull_attempt_at TEXT,
                    last_success_at TEXT,
                    last_pull_ok INTEGER,
                    last_pull_method TEXT NOT NULL DEFAULT '',
                    last_pull_node_count INTEGER NOT NULL DEFAULT 0,
                    last_pull_error TEXT NOT NULL DEFAULT '',
                    last_pull_reasons TEXT NOT NULL DEFAULT '[]',
                    pull_network_mode TEXT NOT NULL DEFAULT 'direct_then_proxy',
                    auto_pull_consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    auto_pull_expired INTEGER NOT NULL DEFAULT 0,
                    auto_pull_expired_at TEXT,
                    last_success_config_fingerprint TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            if not self._has_column("standard_sources", "surge_url"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN surge_url TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("standard_sources", "target_contract_id"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN target_contract_id TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("standard_sources", "source_mode"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN source_mode TEXT NOT NULL DEFAULT 'route_contract'"
                )
            if not self._has_column("standard_sources", "ingest_kind"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN ingest_kind TEXT NOT NULL DEFAULT 'remote_subscription'"
                )
            if not self._has_column("standard_sources", "manual_nodes_text"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN manual_nodes_text TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("standard_sources", "last_pull_attempt_at"):
                cur.execute("ALTER TABLE standard_sources ADD COLUMN last_pull_attempt_at TEXT")
            if not self._has_column("standard_sources", "last_success_at"):
                cur.execute("ALTER TABLE standard_sources ADD COLUMN last_success_at TEXT")
            if not self._has_column("standard_sources", "last_pull_ok"):
                cur.execute("ALTER TABLE standard_sources ADD COLUMN last_pull_ok INTEGER")
            if not self._has_column("standard_sources", "last_pull_method"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN last_pull_method TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("standard_sources", "last_pull_node_count"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN last_pull_node_count INTEGER NOT NULL DEFAULT 0"
                )
            if not self._has_column("standard_sources", "last_pull_error"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN last_pull_error TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("standard_sources", "last_pull_reasons"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN last_pull_reasons TEXT NOT NULL DEFAULT '[]'"
                )
            if not self._has_column("standard_sources", "pull_network_mode"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN pull_network_mode TEXT NOT NULL DEFAULT 'direct_then_proxy'"
                )
            if not self._has_column("standard_sources", "auto_pull_consecutive_failures"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN auto_pull_consecutive_failures INTEGER NOT NULL DEFAULT 0"
                )
            if not self._has_column("standard_sources", "auto_pull_expired"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN auto_pull_expired INTEGER NOT NULL DEFAULT 0"
                )
            if not self._has_column("standard_sources", "auto_pull_expired_at"):
                cur.execute("ALTER TABLE standard_sources ADD COLUMN auto_pull_expired_at TEXT")
            if not self._has_column("standard_sources", "last_success_config_fingerprint"):
                cur.execute(
                    "ALTER TABLE standard_sources ADD COLUMN last_success_config_fingerprint TEXT NOT NULL DEFAULT ''"
                )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS standard_source_qr_assets (
                    source_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    file_relpath TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    detected_url TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, field)
                )
                """
            )
            if not self._has_column("standard_source_qr_assets", "detected_url"):
                cur.execute(
                    "ALTER TABLE standard_source_qr_assets ADD COLUMN detected_url TEXT NOT NULL DEFAULT ''"
                )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS rule_categories (
                    name TEXT PRIMARY KEY,
                    assigned_group TEXT NOT NULL DEFAULT '',
                    rule_count INTEGER NOT NULL DEFAULT 0,
                    rule_source TEXT NOT NULL DEFAULT '',
                    category_type TEXT NOT NULL DEFAULT 'auto',
                    updated_at TEXT NOT NULL,
                    locked INTEGER NOT NULL DEFAULT 0,
                    system_directness TEXT NOT NULL DEFAULT 'PROXY',
                    system_default_group TEXT NOT NULL DEFAULT '',
                    system_default_locked INTEGER NOT NULL DEFAULT 0,
                    override_group TEXT NOT NULL DEFAULT '',
                    override_active INTEGER NOT NULL DEFAULT 0,
                    directness_override TEXT NOT NULL DEFAULT '',
                    lock_source TEXT NOT NULL DEFAULT ''
                )
                """
            )
            if not self._has_column("rule_categories", "rule_source"):
                cur.execute(
                    "ALTER TABLE rule_categories ADD COLUMN rule_source TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("rule_categories", "category_type"):
                cur.execute(
                    "ALTER TABLE rule_categories ADD COLUMN category_type TEXT NOT NULL DEFAULT 'auto'"
                )
            if not self._has_column("rule_categories", "locked"):
                cur.execute(
                    "ALTER TABLE rule_categories ADD COLUMN locked INTEGER NOT NULL DEFAULT 0"
                )
            if not self._has_column("rule_categories", "system_directness"):
                cur.execute(
                    "ALTER TABLE rule_categories ADD COLUMN system_directness TEXT NOT NULL DEFAULT 'PROXY'"
                )
            if not self._has_column("rule_categories", "system_default_group"):
                cur.execute(
                    "ALTER TABLE rule_categories ADD COLUMN system_default_group TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("rule_categories", "system_default_locked"):
                cur.execute(
                    "ALTER TABLE rule_categories ADD COLUMN system_default_locked INTEGER NOT NULL DEFAULT 0"
                )
            if not self._has_column("rule_categories", "override_group"):
                cur.execute(
                    "ALTER TABLE rule_categories ADD COLUMN override_group TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("rule_categories", "override_active"):
                cur.execute(
                    "ALTER TABLE rule_categories ADD COLUMN override_active INTEGER NOT NULL DEFAULT 0"
                )
            if not self._has_column("rule_categories", "directness_override"):
                cur.execute(
                    "ALTER TABLE rule_categories ADD COLUMN directness_override TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("rule_categories", "lock_source"):
                cur.execute(
                    "ALTER TABLE rule_categories ADD COLUMN lock_source TEXT NOT NULL DEFAULT ''"
                )
            # Backfill legacy auto DIRECT rows as system locks.
            cur.execute(
                """
                UPDATE rule_categories
                SET system_directness='DIRECT',
                    lock_source='system',
                    locked=1
                WHERE assigned_group='DIRECT' AND locked=1 AND COALESCE(lock_source,'')=''
                """
            )
            cur.execute(
                """
                UPDATE rule_categories
                SET system_default_group=CASE
                        WHEN COALESCE(system_directness,'PROXY')='DIRECT' THEN 'DIRECT'
                        ELSE ''
                    END,
                    system_default_locked=CASE
                        WHEN COALESCE(system_directness,'PROXY')='DIRECT' THEN 1
                        ELSE 0
                    END
                WHERE COALESCE(system_default_group,'')=''
                  AND COALESCE(system_default_locked,0)=0
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS rule_category_directness_reviews (
                    id TEXT PRIMARY KEY,
                    category_name TEXT NOT NULL,
                    proposed_decision TEXT NOT NULL,
                    confidence TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'llm-import',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    decided_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_rule_category_directness_reviews_status "
                "ON rule_category_directness_reviews(status, category_name)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS rule_category_cache (
                    name TEXT PRIMARY KEY,
                    clash_rules_json TEXT NOT NULL,
                    rule_count INTEGER NOT NULL DEFAULT 0,
                    source_sha TEXT NOT NULL DEFAULT '',
                    source_path TEXT NOT NULL DEFAULT '',
                    fetched_at TEXT NOT NULL
                )
                """
            )
            if not self._has_column("rule_category_cache", "rule_count"):
                cur.execute(
                    "ALTER TABLE rule_category_cache ADD COLUMN rule_count INTEGER NOT NULL DEFAULT 0"
                )
            if not self._has_column("rule_category_cache", "source_sha"):
                cur.execute(
                    "ALTER TABLE rule_category_cache ADD COLUMN source_sha TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("rule_category_cache", "source_path"):
                cur.execute(
                    "ALTER TABLE rule_category_cache ADD COLUMN source_path TEXT NOT NULL DEFAULT ''"
                )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_rules (
                    id TEXT PRIMARY KEY,
                    rule_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    target_contract_id TEXT NOT NULL DEFAULT '',
                    target_group TEXT NOT NULL,
                    category_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            if not self._has_column("custom_rules", "target_contract_id"):
                cur.execute(
                    "ALTER TABLE custom_rules ADD COLUMN target_contract_id TEXT NOT NULL DEFAULT ''"
                )
            for row in cur.execute(
                "SELECT id, target_group FROM custom_rules WHERE COALESCE(target_contract_id,'')=''"
            ).fetchall():
                cur.execute(
                    "UPDATE custom_rules SET target_contract_id=? WHERE id=?",
                    (resolve_legacy_route_target(row["target_group"]), str(row["id"] or "")),
                )
            if not self._has_column("custom_rules", "category_name"):
                cur.execute(
                    "ALTER TABLE custom_rules ADD COLUMN category_name TEXT NOT NULL DEFAULT ''"
                )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS device_subscriptions (
                    id TEXT PRIMARY KEY,
                    device_key TEXT NOT NULL UNIQUE,
                    device_name TEXT NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    public_id TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_seen_at TEXT,
                    last_seen_ip TEXT
                )
                """
            )
            if not self._has_column("device_subscriptions", "public_id"):
                cur.execute(
                    "ALTER TABLE device_subscriptions ADD COLUMN public_id TEXT NOT NULL DEFAULT ''"
                )
            for row in cur.execute(
                "SELECT id FROM device_subscriptions WHERE COALESCE(public_id,'')=''"
            ).fetchall():
                cur.execute(
                    "UPDATE device_subscriptions SET public_id=? WHERE id=?",
                    (generate_public_subscription_id(), str(row["id"])),
                )
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_device_subscriptions_public_id ON device_subscriptions(public_id)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gorelay_node_cache (
                    source_id TEXT NOT NULL,
                    device_key TEXT NOT NULL,
                    nodes_json TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, device_key)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS standard_node_cache (
                    source_id TEXT PRIMARY KEY,
                    nodes_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS lazycat_profile_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    settings_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS general_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    editor_state_json TEXT NOT NULL DEFAULT '{}',
                    is_system_default INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_profiles (
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    settings_json TEXT NOT NULL,
                    editor_state_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            if not self._has_column("general_profiles", "editor_state_json"):
                cur.execute(
                    "ALTER TABLE general_profiles ADD COLUMN editor_state_json TEXT NOT NULL DEFAULT '{}'"
                )
            if not self._has_column("scenario_profiles", "editor_state_json"):
                cur.execute(
                    "ALTER TABLE scenario_profiles ADD COLUMN editor_state_json TEXT NOT NULL DEFAULT '{}'"
                )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_category_states (
                    scenario_id TEXT NOT NULL,
                    category_name TEXT NOT NULL,
                    assigned_group TEXT NOT NULL DEFAULT '',
                    contract_id TEXT NOT NULL DEFAULT '',
                    catalog_group TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    rule_count INTEGER NOT NULL DEFAULT 0,
                    rule_source TEXT NOT NULL DEFAULT '',
                    category_type TEXT NOT NULL DEFAULT 'auto',
                    updated_at TEXT NOT NULL,
                    locked INTEGER NOT NULL DEFAULT 0,
                    system_directness TEXT NOT NULL DEFAULT 'PROXY',
                    system_default_group TEXT NOT NULL DEFAULT '',
                    system_default_locked INTEGER NOT NULL DEFAULT 0,
                    override_group TEXT NOT NULL DEFAULT '',
                    override_active INTEGER NOT NULL DEFAULT 0,
                    directness_override TEXT NOT NULL DEFAULT '',
                    lock_source TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (scenario_id, category_name)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_pin_groups (
                    scenario_id TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    mode TEXT NOT NULL DEFAULT 'standard',
                    description TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scenario_id, group_name)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_custom_rules (
                    scenario_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    target_contract_id TEXT NOT NULL DEFAULT '',
                    target_group TEXT NOT NULL,
                    category_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (scenario_id, id)
                )
                """
            )
            if not self._has_column("scenario_custom_rules", "target_contract_id"):
                cur.execute(
                    "ALTER TABLE scenario_custom_rules ADD COLUMN target_contract_id TEXT NOT NULL DEFAULT ''"
                )
            for row in cur.execute(
                "SELECT scenario_id, id, target_group FROM scenario_custom_rules WHERE COALESCE(target_contract_id,'')=''"
            ).fetchall():
                cur.execute(
                    "UPDATE scenario_custom_rules SET target_contract_id=? WHERE scenario_id=? AND id=?",
                    (
                        resolve_legacy_route_target(row["target_group"]),
                        str(row["scenario_id"] or ""),
                        str(row["id"] or ""),
                    ),
                )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_process_rules (
                    scenario_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    contract_id TEXT NOT NULL,
                    business_group TEXT NOT NULL DEFAULT '',
                    match_type TEXT NOT NULL,
                    value TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scenario_id, id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_external_proxy_programs (
                    scenario_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    contract_id TEXT NOT NULL,
                    business_group TEXT NOT NULL DEFAULT '',
                    program_path TEXT NOT NULL,
                    args_json TEXT NOT NULL DEFAULT '[]',
                    local_port INTEGER NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scenario_id, id)
                )
                """
            )
            try:
                cur.execute(
                    "ALTER TABLE scenario_process_rules ADD COLUMN business_group TEXT NOT NULL DEFAULT ''"
                )
            except sqlite3.OperationalError:
                pass
            try:
                cur.execute(
                    "ALTER TABLE scenario_external_proxy_programs ADD COLUMN business_group TEXT NOT NULL DEFAULT ''"
                )
            except sqlite3.OperationalError:
                pass
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS route_contracts (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    strategy_type TEXT NOT NULL DEFAULT 'strict',
                    failure_action TEXT NOT NULL DEFAULT 'interrupt',
                    routing_action TEXT NOT NULL DEFAULT 'proxy',
                    editable INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    owner_scenario_id TEXT NOT NULL DEFAULT '',
                    is_system INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_route_contract_views (
                    scenario_id TEXT NOT NULL,
                    contract_id TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    llm_routing_intent TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scenario_id, contract_id)
                )
                """
            )
            if not self._has_column("route_contracts", "description"):
                cur.execute(
                    "ALTER TABLE route_contracts ADD COLUMN description TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("route_contracts", "owner_scenario_id"):
                cur.execute(
                    "ALTER TABLE route_contracts ADD COLUMN owner_scenario_id TEXT NOT NULL DEFAULT ''"
                )
            if not self._has_column("route_contracts", "routing_action"):
                cur.execute(
                    "ALTER TABLE route_contracts ADD COLUMN routing_action TEXT NOT NULL DEFAULT 'proxy'"
                )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS route_contract_pool_bindings (
                    contract_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    pool_name TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (contract_id, role, sort_order)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS service_catalog_entries (
                    category_name TEXT PRIMARY KEY,
                    catalog_group TEXT NOT NULL DEFAULT '',
                    contract_id TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'migrated',
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_backup_outbox (
                    generation INTEGER PRIMARY KEY,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'acked')),
                    sync_run_id TEXT NOT NULL DEFAULT '',
                    commit_sha TEXT NOT NULL DEFAULT '',
                    remote_digest TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_policy_backup_outbox_status
                ON policy_backup_outbox(status, generation)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_task_heartbeats (
                    task_name TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'starting',
                    required INTEGER NOT NULL DEFAULT 1,
                    started_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    last_success_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    failure_episode INTEGER NOT NULL DEFAULT 0,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            if not self._has_column("runtime_task_heartbeats", "failure_episode"):
                cur.execute(
                    "ALTER TABLE runtime_task_heartbeats ADD COLUMN failure_episode INTEGER NOT NULL DEFAULT 0"
                )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_alert_receipts (
                    alert_key TEXT PRIMARY KEY,
                    alert_id TEXT NOT NULL UNIQUE,
                    task_name TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'fatal',
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'sent', 'failed', 'unknown')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    sent_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            alert_table = cur.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='runtime_alert_receipts'"
            ).fetchone()
            if alert_table and "unknown" not in str(alert_table["sql"] or "").lower():
                # SQLite cannot alter a CHECK constraint in place.  Rebuild
                # this small app-owned table while preserving existing
                # receipts from an older deployment.
                cur.execute("DROP INDEX IF EXISTS idx_runtime_alert_receipts_status")
                cur.execute("ALTER TABLE runtime_alert_receipts RENAME TO runtime_alert_receipts_legacy")
                cur.execute(
                    """
                    CREATE TABLE runtime_alert_receipts (
                        alert_key TEXT PRIMARY KEY,
                        alert_id TEXT NOT NULL UNIQUE,
                        task_name TEXT NOT NULL,
                        severity TEXT NOT NULL DEFAULT 'fatal',
                        message TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'sent', 'failed', 'unknown')),
                        attempts INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        sent_at TEXT NOT NULL DEFAULT '',
                        last_error TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    INSERT INTO runtime_alert_receipts (
                        alert_key, alert_id, task_name, severity, message,
                        payload_json, status, attempts, created_at, sent_at,
                        last_error, updated_at
                    )
                    SELECT alert_key, alert_id, task_name, severity, message,
                           payload_json, status, attempts, created_at, sent_at,
                           last_error, updated_at
                    FROM runtime_alert_receipts_legacy
                    """
                )
                cur.execute("DROP TABLE runtime_alert_receipts_legacy")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runtime_alert_receipts_status
                ON runtime_alert_receipts(status, updated_at)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS cn_judge_cache (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                )
                """
            )

            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_gorelay_bindings_account ON gorelay_domain_bindings(account_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_gorelay_histories_account_created ON gorelay_domain_import_histories(account_id, created_at DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_gorelay_snapshots_account_created ON gorelay_account_snapshots(account_id, created_at DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_custom_rules_category_name ON custom_rules(category_name)"
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pinned_categories (
                    category_name TEXT PRIMARY KEY,
                    pin_group TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS pin_groups (
                    group_name TEXT PRIMARY KEY,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    mode TEXT NOT NULL DEFAULT 'standard',
                    description TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            if not self._has_column("pin_groups", "mode"):
                cur.execute(
                    "ALTER TABLE pin_groups ADD COLUMN mode TEXT NOT NULL DEFAULT 'standard'"
                )
            if not self._has_column("pin_groups", "description"):
                cur.execute(
                    "ALTER TABLE pin_groups ADD COLUMN description TEXT NOT NULL DEFAULT ''"
                )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS review_cache (
                    id TEXT PRIMARY KEY,
                    cache_key TEXT NOT NULL UNIQUE,
                    primary_profile_id TEXT NOT NULL,
                    target_profile_id TEXT NOT NULL,
                    annotations_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    primary_updated_at TEXT NOT NULL,
                    target_updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_cache_key ON review_cache(cache_key)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_cache_profiles ON review_cache(primary_profile_id, target_profile_id)"
            )

            self._conn.commit()

    def _migrate_gorelay_sources_to_accounts(self) -> None:
        with self._lock:
            count = self._conn.execute("SELECT COUNT(1) AS c FROM gorelay_accounts").fetchone()
            if int(count["c"] or 0) > 0:
                return
            rows = self._conn.execute("SELECT * FROM gorelay_sources ORDER BY updated_at DESC").fetchall()
            now = _utc_now()
            for row in rows:
                self._conn.execute(
                    """
                    INSERT INTO gorelay_accounts (
                        id,name,login_url,rules_url,gorelay_username,gorelay_password,
                        proxy_username_default,proxy_password_default,selectors_json,
                        mcp_url,auth_header,login_tool,nodes_tool,login_args_json,nodes_args_json,
                        enabled,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        login_url=excluded.login_url,
                        rules_url=excluded.rules_url,
                        gorelay_username=excluded.gorelay_username,
                        gorelay_password=excluded.gorelay_password,
                        proxy_username_default=excluded.proxy_username_default,
                        proxy_password_default=excluded.proxy_password_default,
                        selectors_json=excluded.selectors_json,
                        mcp_url=excluded.mcp_url,
                        auth_header=excluded.auth_header,
                        login_tool=excluded.login_tool,
                        nodes_tool=excluded.nodes_tool,
                        login_args_json=excluded.login_args_json,
                        nodes_args_json=excluded.nodes_args_json,
                        enabled=excluded.enabled,
                        updated_at=excluded.updated_at
                    """,
                    (
                        str(row["id"]),
                        str(row["name"]),
                        str(row["login_url"]),
                        str(row["login_url"]),
                        str(row["gorelay_username"] or ""),
                        str(row["gorelay_password"] or ""),
                        str(row["proxy_username"] or ""),
                        str(row["proxy_password"] or ""),
                        str(row["selectors_json"] or "{}"),
                        "",
                        "",
                        "auth_login",
                        "list_nodes",
                        '{"username":"{username}","password":"{password}"}',
                        "{}",
                        int(row["enabled"] or 0),
                        now,
                    ),
                )
            self._conn.commit()

    def _migrate_encrypt_plaintext(self) -> None:
        """One-time migration: encrypt any existing plaintext password fields.

        Detection strategy: Fernet tokens always start with ``gAAAAA``. If a
        non-empty value does *not* start with that prefix, it is treated as
        plaintext and encrypted in-place. The migration is idempotent.
        """
        if self._cipher is None:
            return

        def _needs_encrypt(val: str | None) -> bool:
            if not val:
                return False
            # Verify existing encrypted credentials before startup can use
            # them. A lost key must not turn ciphertext into a password.
            self._cipher.decrypt(val)
            return not self._cipher._looks_encrypted(val)

        with self._lock:
            # -- gorelay_accounts --
            rows = self._conn.execute(
                "SELECT id, gorelay_password, proxy_password_default, auth_header FROM gorelay_accounts"
            ).fetchall()
            for r in rows:
                updates: dict[str, str] = {}
                for col in ("gorelay_password", "proxy_password_default", "auth_header"):
                    raw = str(r[col] or "")
                    if _needs_encrypt(raw):
                        updates[col] = self._cipher.encrypt(raw)
                if updates:
                    set_clause = ", ".join(f"{k}=?" for k in updates)
                    self._conn.execute(
                        f"UPDATE gorelay_accounts SET {set_clause} WHERE id=?",
                        (*updates.values(), str(r["id"])),
                    )

            # -- gorelay_sources (legacy) --
            rows = self._conn.execute(
                "SELECT id, gorelay_password, proxy_password FROM gorelay_sources"
            ).fetchall()
            for r in rows:
                updates = {}
                for col in ("gorelay_password", "proxy_password"):
                    raw = str(r[col] or "")
                    if _needs_encrypt(raw):
                        updates[col] = self._cipher.encrypt(raw)
                if updates:
                    set_clause = ", ".join(f"{k}=?" for k in updates)
                    self._conn.execute(
                        f"UPDATE gorelay_sources SET {set_clause} WHERE id=?",
                        (*updates.values(), str(r["id"])),
                    )

            # -- gorelay_device_profiles --
            rows = self._conn.execute(
                "SELECT account_id, device_key, proxy_password_override FROM gorelay_device_profiles"
            ).fetchall()
            for r in rows:
                raw = str(r["proxy_password_override"] or "")
                if _needs_encrypt(raw):
                    self._conn.execute(
                        "UPDATE gorelay_device_profiles SET proxy_password_override=? WHERE account_id=? AND device_key=?",
                        (self._cipher.encrypt(raw), str(r["account_id"]), str(r["device_key"])),
                    )

            self._conn.commit()

    def _normalize_contract_strategy(self, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in CONTRACT_STRATEGIES else CONTRACT_STRATEGY_STRICT

    def _normalize_contract_failure_action(self, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in CONTRACT_FAILURE_ACTIONS else CONTRACT_FAILURE_INTERRUPT

    def _normalize_contract_routing_action(self, value: object) -> str:
        return normalize_route_action(value)

    def _row_to_route_contract_view(self, row: sqlite3.Row) -> RouteContractView:
        return RouteContractView(
            scenario_id=str(row["scenario_id"] or ""),
            contract_id=normalize_contract_id(row["contract_id"]),
            display_name=str(row["display_name"] or "").strip(),
            description=str(row["description"] or "").strip(),
            llm_routing_intent=str(row["llm_routing_intent"] or "").strip(),
            enabled=bool(int(row["enabled"] or 0)),
            sort_order=int(row["sort_order"] or 0),
            is_default=bool(int(row["is_default"] or 0)),
            updated_at=str(row["updated_at"] or ""),
        )

    def _row_to_custom_rule(self, row: sqlite3.Row) -> CustomRule:
        return CustomRule(
            id=str(row["id"] or ""),
            rule_type=str(row["rule_type"] or ""),
            value=str(row["value"] or ""),
            target_contract_id=resolve_legacy_route_target(row["target_contract_id"]),
            target_group=str(row["target_group"] or ""),
            category_name=str(row["category_name"] or ""),
            created_at=str(row["created_at"] or ""),
        )

    def _row_to_route_contract(self, row: sqlite3.Row) -> RouteContract:
        contract_id = str(row["id"] or "")
        bindings = self._conn.execute(
            """
            SELECT role, pool_name, sort_order
            FROM route_contract_pool_bindings
            WHERE contract_id=?
            ORDER BY role, sort_order
            """,
            (contract_id,),
        ).fetchall()
        primary_pools = [str(item["pool_name"] or "") for item in bindings if str(item["role"]) == "primary"]
        fallback_pools = [
            str(item["pool_name"] or "") for item in bindings if str(item["role"]) == "fallback"
        ]
        return RouteContract(
            id=contract_id,
            display_name=str(row["display_name"] or contract_display_name(contract_id)),
            description=str(row["description"] or contract_description(contract_id)),
            strategy_type=self._normalize_contract_strategy(row["strategy_type"]),
            primary_pools=[pool for pool in primary_pools if pool in POOL_IDS],
            fallback_pools=[pool for pool in fallback_pools if pool in POOL_IDS],
            failure_action=self._normalize_contract_failure_action(row["failure_action"]),
            routing_action=self._normalize_contract_routing_action(row["routing_action"]),
            editable=bool(int(row["editable"] or 0)),
            enabled=bool(int(row["enabled"] or 0)),
            sort_order=int(row["sort_order"] or 0),
            owner_scenario_id=str(row["owner_scenario_id"] or "").strip(),
            is_system=bool(int(row["is_system"] or 0)),
            updated_at=str(row["updated_at"] or ""),
        )

    def _row_to_service_catalog_entry(self, row: sqlite3.Row) -> ServiceCatalogEntry:
        contract_id = normalize_contract_id(row["contract_id"])
        return ServiceCatalogEntry(
            category_name=str(row["category_name"] or ""),
            catalog_group=str(row["catalog_group"] or ""),
            contract_id=contract_id,
            sort_order=int(row["sort_order"] or 0),
            source=str(row["source"] or "migrated"),
            updated_at=str(row["updated_at"] or ""),
        )

    def _row_to_general_profile(self, row: sqlite3.Row) -> GeneralProfile:
        payload = _json_loads(str(row["settings_json"] or "{}"))
        settings = payload if isinstance(payload, dict) else {}
        editor_payload = _json_loads(str(row["editor_state_json"] or "{}"))
        return GeneralProfile(
            id=str(row["id"] or ""),
            name=str(row["name"] or ""),
            settings=normalize_lazycat_profile_settings(settings),
            editor_state=normalize_profile_editor_state(
                editor_payload if isinstance(editor_payload, dict) else {},
                legacy_default=True,
            ),
            is_system_default=bool(int(row["is_system_default"] or 0)),
            updated_at=str(row["updated_at"] or ""),
        )

    def _row_to_scenario_profile(self, row: sqlite3.Row) -> ScenarioProfile:
        payload = _json_loads(str(row["settings_json"] or "{}"))
        settings = payload if isinstance(payload, dict) else {}
        editor_payload = _json_loads(str(row["editor_state_json"] or "{}"))
        legacy_default = str(row["id"] or "") != _DEFAULT_SCENARIO_ID
        return ScenarioProfile(
            id=str(row["id"] or ""),
            slug=str(row["slug"] or ""),
            name=str(row["name"] or ""),
            description=str(row["description"] or ""),
            enabled=bool(int(row["enabled"] or 0)),
            sort_order=int(row["sort_order"] or 0),
            settings=normalize_lazycat_profile_settings(settings),
            editor_state=normalize_profile_editor_state(
                editor_payload if isinstance(editor_payload, dict) else {},
                legacy_default=legacy_default,
            ),
            updated_at=str(row["updated_at"] or ""),
        )

    def _migrate_profile_editor_state(self) -> None:
        default_settings = normalize_lazycat_profile_settings({})
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, editor_state_json FROM general_profiles"
            ).fetchall()
            for row in rows:
                payload = _json_loads(str(row["editor_state_json"] or "{}"))
                state = payload if isinstance(payload, dict) else {}
                if int(state.get("version") or 0) == 0:
                    self._conn.execute(
                        "UPDATE general_profiles SET editor_state_json=? WHERE id=?",
                        (_json_dumps(default_profile_editor_state(legacy=True)), str(row["id"] or "")),
                    )

            rows = self._conn.execute(
                "SELECT id, editor_state_json FROM scenario_profiles"
            ).fetchall()
            for row in rows:
                scenario_id = str(row["id"] or "")
                payload = _json_loads(str(row["editor_state_json"] or "{}"))
                state = payload if isinstance(payload, dict) else {}
                if int(state.get("version") or 0) != 0:
                    continue
                if scenario_id == _DEFAULT_SCENARIO_ID:
                    self._conn.execute(
                        """
                        UPDATE scenario_profiles
                        SET settings_json=?, editor_state_json=?
                        WHERE id=?
                        """,
                        (
                            _json_dumps(default_settings),
                            _json_dumps(default_profile_editor_state(legacy=False)),
                            scenario_id,
                        ),
                    )
                else:
                    self._conn.execute(
                        "UPDATE scenario_profiles SET editor_state_json=? WHERE id=?",
                        (_json_dumps(default_profile_editor_state(legacy=True)), scenario_id),
                    )
            self._conn.commit()

    def _pin_group_mode_locked(self, group_name: str) -> str:
        if not group_name:
            return BUSINESS_GROUP_MODE_STANDARD
        row = self._conn.execute(
            "SELECT mode FROM pin_groups WHERE group_name=?",
            (group_name,),
        ).fetchone()
        return _normalize_business_group_mode(row["mode"] if row else BUSINESS_GROUP_MODE_STANDARD)

    def _sync_service_catalog_entry_locked(
        self,
        category_name: str,
        *,
        preserve_manual_contract: bool,
        prefer_category_contract: bool = False,
    ) -> None:
        safe_name = str(category_name or "").strip()
        if not safe_name:
            return
        category_row = self._conn.execute(
            "SELECT name, assigned_group FROM rule_categories WHERE name=?",
            (safe_name,),
        ).fetchone()
        if not category_row:
            self._conn.execute(
                "DELETE FROM service_catalog_entries WHERE category_name=?",
                (safe_name,),
            )
            return
        pin_row = self._conn.execute(
            """
            SELECT pin_group, sort_order
            FROM pinned_categories
            WHERE category_name=?
            """,
            (safe_name,),
        ).fetchone()
        existing_row = self._conn.execute(
            "SELECT * FROM service_catalog_entries WHERE category_name=?",
            (safe_name,),
        ).fetchone()
        catalog_group = str(pin_row["pin_group"] or "") if pin_row else ""
        sort_order = int(pin_row["sort_order"] or 0) if pin_row else 0
        existing_source = str(existing_row["source"] or "migrated") if existing_row else "migrated"
        existing_contract_id = normalize_contract_id(existing_row["contract_id"]) if existing_row else ""
        legacy_contract_id = normalize_contract_id(str(category_row["assigned_group"] or ""))
        contract_id = legacy_contract_id if prefer_category_contract else existing_contract_id or legacy_contract_id
        source = existing_source if existing_row else "migrated"
        now = _utc_now()
        self._conn.execute(
            """
            INSERT INTO service_catalog_entries (
                category_name, catalog_group, contract_id, sort_order, source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(category_name) DO UPDATE SET
                catalog_group=excluded.catalog_group,
                contract_id=excluded.contract_id,
                sort_order=excluded.sort_order,
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            (
                safe_name,
                catalog_group,
                contract_id,
                sort_order,
                source,
                now,
            ),
        )

    def _seed_route_contracts(self) -> None:
        now = _utc_now()
        with self._lock:
            marker_row = self._conn.execute(
                "SELECT value_json FROM runtime_settings WHERE key=?",
                (_ROUTE_CONTRACTS_SEEDED_SETTING,),
            ).fetchone()
            if marker_row:
                return

            existing_count = int(
                self._conn.execute("SELECT COUNT(*) AS count FROM route_contracts").fetchone()["count"]
            )
            if existing_count:
                # Upgrade existing rows in place. Their identity, labels,
                # pools and bindings are user data and must survive intact.
                rows = self._conn.execute("SELECT id FROM route_contracts").fetchall()
                for row in rows:
                    contract_id = str(row["id"] or "").strip()
                    action = (
                        ROUTE_ACTION_DIRECT
                        if contract_id == CONTRACT_DIRECT
                        else ROUTE_ACTION_REJECT
                        if contract_id == CONTRACT_AD_BLOCK
                        else ROUTE_ACTION_PROXY
                    )
                    self._conn.execute(
                        "UPDATE route_contracts SET routing_action=?, editable=1, is_system=0 WHERE id=?",
                        (action, contract_id),
                    )
            elif not self._route_contracts_table_preexisting:
                # Empty database only: templates are a one-time initial seed.
                # Missing rows after this point are intentional user state.
                for spec in _default_route_contracts():
                    self._conn.execute(
                        """
                        INSERT INTO route_contracts (
                            id, display_name, description, strategy_type, failure_action, routing_action,
                            editable, enabled, sort_order, owner_scenario_id, is_system, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            spec.id,
                            spec.display_name,
                            spec.description,
                            spec.strategy_type,
                            spec.failure_action,
                            spec.routing_action,
                            1,
                            1 if spec.enabled else 0,
                            spec.sort_order,
                            "",
                            0,
                            now,
                        ),
                    )
                    for sort_order, pool_name in enumerate(spec.primary_pools):
                        self._conn.execute(
                            """
                            INSERT INTO route_contract_pool_bindings (
                                contract_id, role, pool_name, sort_order
                            ) VALUES (?, 'primary', ?, ?)
                            """,
                            (spec.id, pool_name, sort_order),
                        )
                    for sort_order, pool_name in enumerate(spec.fallback_pools):
                        self._conn.execute(
                            """
                            INSERT INTO route_contract_pool_bindings (
                                contract_id, role, pool_name, sort_order
                            ) VALUES (?, 'fallback', ?, ?)
                            """,
                            (spec.id, pool_name, sort_order),
                        )
            self._conn.execute(
                """
                INSERT INTO runtime_settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (_ROUTE_CONTRACTS_SEEDED_SETTING, _json_dumps(True), now),
            )
            self._conn.commit()

    def _seed_scenario_route_contract_views(self) -> None:
        now = _utc_now()
        with self._lock:
            changed = self._ensure_default_scenario_route_contract_views_locked(now)
            changed = self._compact_inherited_scenario_route_contract_views_locked(now) or changed
            if changed:
                self._conn.commit()

    def _ensure_default_scenario_route_contract_views_locked(self, now: str) -> bool:
        marker_row = self._conn.execute(
            "SELECT value_json FROM runtime_settings WHERE key=?",
            (_SCENARIO_ROUTE_CONTRACT_VIEWS_SEEDED_SETTING,),
        ).fetchone()
        if marker_row:
            return False
        changed = False
        existing_ids = {
            str(row["contract_id"] or "").strip()
            for row in self._conn.execute(
                "SELECT contract_id FROM scenario_route_contract_views WHERE scenario_id=?",
                (_DEFAULT_SCENARIO_ID,),
            ).fetchall()
            if str(row["contract_id"] or "").strip()
        }
        rows = self._conn.execute(
            """
            SELECT id, display_name, description, enabled, sort_order
            FROM route_contracts
            WHERE owner_scenario_id=''
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
        for row in rows:
            contract_id = str(row["id"] or "").strip()
            if not contract_id or contract_id in existing_ids:
                continue
            self._conn.execute(
                """
                INSERT INTO scenario_route_contract_views (
                    scenario_id, contract_id, display_name, description, llm_routing_intent,
                    enabled, sort_order, is_default, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _DEFAULT_SCENARIO_ID,
                    contract_id,
                    str(row["display_name"] or ""),
                    str(row["description"] or ""),
                    str(row["description"] or ""),
                    1 if bool(row["enabled"]) else 0,
                    int(row["sort_order"] or 0),
                    1 if contract_id == CONTRACT_CHAIN_HOME else 0,
                    now,
                ),
            )
            changed = True
        default_row = self._conn.execute(
            """
            SELECT contract_id FROM scenario_route_contract_views
            WHERE scenario_id=? AND is_default=1
            ORDER BY contract_id
            LIMIT 1
            """,
            (_DEFAULT_SCENARIO_ID,),
        ).fetchone()
        if not default_row:
            self._conn.execute(
                "UPDATE scenario_route_contract_views SET is_default=CASE WHEN contract_id=? THEN 1 ELSE 0 END WHERE scenario_id=? AND contract_id=?",
                (CONTRACT_CHAIN_HOME, _DEFAULT_SCENARIO_ID, CONTRACT_CHAIN_HOME),
            )
            if self._conn.execute("SELECT changes()").fetchone()[0]:
                changed = True
        self._conn.execute(
            """
            INSERT INTO runtime_settings (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
            """,
            (_SCENARIO_ROUTE_CONTRACT_VIEWS_SEEDED_SETTING, _json_dumps(True), now),
        )
        changed = True
        return changed

    def _compact_inherited_scenario_route_contract_views_locked(self, now: str) -> bool:
        default_map = self._list_scenario_route_contract_view_rows_locked(_DEFAULT_SCENARIO_ID)
        changed = False
        scenario_ids = [
            str(row["id"] or "").strip()
            for row in self._conn.execute(
                "SELECT id FROM scenario_profiles WHERE id<>? ORDER BY id",
                (_DEFAULT_SCENARIO_ID,),
            ).fetchall()
            if str(row["id"] or "").strip()
        ]
        for scenario_id in scenario_ids:
            explicit_map = self._list_scenario_route_contract_view_rows_locked(scenario_id)
            redundant_ids = [
                contract_id
                for contract_id, view in explicit_map.items()
                if self._route_contract_view_semantically_equal(view, default_map.get(contract_id))
            ]
            if not redundant_ids:
                continue
            placeholders = ",".join("?" for _ in redundant_ids)
            self._conn.execute(
                f"DELETE FROM scenario_route_contract_views WHERE scenario_id=? AND contract_id IN ({placeholders})",
                (scenario_id, *redundant_ids),
            )
            changed = True
        return changed

    def _migrate_general_profile_defaults(self) -> None:
        now = _utc_now()
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM general_profiles WHERE is_system_default=1 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if existing:
                return
            legacy = self._conn.execute(
                "SELECT settings_json, updated_at FROM lazycat_profile_settings WHERE id=1"
            ).fetchone()
            legacy_settings = (
                backfill_legacy_mihomo_mainline_settings(
                    _json_loads(str(legacy["settings_json"] or "{}"))
                )
                if legacy
                else {}
            )
            settings = (
                normalize_lazycat_profile_settings(legacy_settings)
                if legacy
                else normalize_lazycat_profile_settings({})
            )
            updated_at = str(legacy["updated_at"] or now) if legacy else now
            self._conn.execute(
                """
                INSERT INTO general_profiles (id, name, settings_json, editor_state_json, is_system_default, updated_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    settings_json=excluded.settings_json,
                    editor_state_json=excluded.editor_state_json,
                    is_system_default=excluded.is_system_default,
                    updated_at=excluded.updated_at
                """,
                (
                    _DEFAULT_GENERAL_PROFILE_ID,
                    "LazyCat Default",
                    _json_dumps(settings),
                    _json_dumps(default_profile_editor_state(legacy=True)),
                    updated_at,
                ),
            )
            self._conn.commit()

    def _pin_existing_mihomo_mainline_defaults(self) -> None:
        with self._lock:
            changed = False
            for table in ("general_profiles", "scenario_profiles"):
                rows = self._conn.execute(
                    f"SELECT id, settings_json FROM {table}"
                ).fetchall()
                for row in rows:
                    raw = _json_loads(str(row["settings_json"] or "{}"))
                    payload = raw if isinstance(raw, dict) else {}
                    backfilled = backfill_legacy_mihomo_mainline_settings(payload)
                    if backfilled == payload:
                        continue
                    self._conn.execute(
                        f"UPDATE {table} SET settings_json=? WHERE id=?",
                        (_json_dumps(backfilled), str(row["id"] or "")),
                    )
                    changed = True

            legacy = self._conn.execute(
                "SELECT settings_json FROM lazycat_profile_settings WHERE id=1"
            ).fetchone()
            if legacy:
                raw = _json_loads(str(legacy["settings_json"] or "{}"))
                payload = raw if isinstance(raw, dict) else {}
                backfilled = backfill_legacy_mihomo_mainline_settings(payload)
                if backfilled != payload:
                    self._conn.execute(
                        "UPDATE lazycat_profile_settings SET settings_json=? WHERE id=1",
                        (_json_dumps(backfilled),),
                    )
                    changed = True

            if changed:
                self._conn.commit()

    def _migrate_default_scenario(self) -> None:
        now = _utc_now()
        with self._lock:
            existing = self._conn.execute(
                "SELECT 1 FROM scenario_profiles WHERE id=? OR slug=?",
                (_DEFAULT_SCENARIO_ID, _DEFAULT_SCENARIO_SLUG),
            ).fetchone()
            if existing:
                return

            profile_row = self._conn.execute(
                "SELECT * FROM general_profiles WHERE is_system_default=1 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            profile = self._row_to_general_profile(profile_row) if profile_row else None
            settings = profile.settings if profile else normalize_lazycat_profile_settings({})
            updated_at = profile.updated_at if profile and profile.updated_at else now
            self._conn.execute(
                """
                INSERT INTO scenario_profiles (
                    id, slug, name, description, enabled, sort_order, settings_json, editor_state_json, updated_at
                ) VALUES (?, ?, ?, '', 1, 0, ?, ?, ?)
                """,
                (
                    _DEFAULT_SCENARIO_ID,
                    _DEFAULT_SCENARIO_SLUG,
                    "默认场景",
                    _json_dumps(settings),
                    _json_dumps(default_profile_editor_state(legacy=False)),
                    updated_at,
                ),
            )

            for row in self._conn.execute("SELECT * FROM rule_categories ORDER BY name").fetchall():
                catalog = self._conn.execute(
                    "SELECT * FROM service_catalog_entries WHERE category_name=?",
                    (str(row["name"] or ""),),
                ).fetchone()
                self._conn.execute(
                    """
                    INSERT INTO scenario_category_states (
                        scenario_id, category_name, assigned_group, contract_id, catalog_group, sort_order,
                        rule_count, rule_source, category_type, updated_at, locked,
                        system_directness, system_default_group, system_default_locked,
                        override_group, override_active, directness_override, lock_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _DEFAULT_SCENARIO_ID,
                        str(row["name"] or ""),
                        str(row["assigned_group"] or ""),
                        normalize_contract_id(catalog["contract_id"]) if catalog else "",
                        str(catalog["catalog_group"] or "") if catalog else "",
                        int(catalog["sort_order"] or 0) if catalog else 0,
                        int(row["rule_count"] or 0),
                        str(row["rule_source"] or ""),
                        str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO),
                        str(row["updated_at"] or updated_at),
                        int(row["locked"] or 0),
                        str(row["system_directness"] or RULE_DIRECTNESS_PROXY),
                        str(row["system_default_group"] or ""),
                        int(row["system_default_locked"] or 0),
                        str(row["override_group"] or ""),
                        int(row["override_active"] or 0),
                        str(row["directness_override"] or ""),
                        str(row["lock_source"] or ""),
                    ),
                )

            for row in self._conn.execute("SELECT * FROM pin_groups ORDER BY sort_order, group_name").fetchall():
                self._conn.execute(
                    """
                    INSERT INTO scenario_pin_groups (
                        scenario_id, group_name, sort_order, mode, description, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _DEFAULT_SCENARIO_ID,
                        str(row["group_name"] or ""),
                        int(row["sort_order"] or 0),
                        str(row["mode"] or BUSINESS_GROUP_MODE_STANDARD),
                        str(row["description"] or ""),
                        str(row["updated_at"] or updated_at),
                    ),
                )

            for row in self._conn.execute("SELECT * FROM custom_rules ORDER BY created_at, id").fetchall():
                target_contract_id = resolve_legacy_route_target(row["target_contract_id"])
                if not target_contract_id:
                    target_contract_id = resolve_legacy_route_target(row["target_group"])
                self._conn.execute(
                    """
                    INSERT INTO scenario_custom_rules (
                        scenario_id, id, rule_type, value, target_contract_id, target_group, category_name, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _DEFAULT_SCENARIO_ID,
                        str(row["id"] or ""),
                        str(row["rule_type"] or ""),
                        str(row["value"] or ""),
                        target_contract_id,
                        str(row["target_group"] or ""),
                        str(row["category_name"] or ""),
                        str(row["created_at"] or updated_at),
                    ),
                )

            process_rules_row = self._conn.execute(
                "SELECT value_json FROM runtime_settings WHERE key=?",
                ("surge.process_rules",),
            ).fetchone()
            process_rules = (
                _json_loads(str(process_rules_row["value_json"] or "null"))
                if process_rules_row
                else None
            )
            if isinstance(process_rules, list):
                for item in process_rules:
                    if not isinstance(item, dict):
                        continue
                    self._conn.execute(
                        """
                        INSERT INTO scenario_process_rules (
                            scenario_id, id, contract_id, business_group, match_type, value, sort_order, enabled, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            _DEFAULT_SCENARIO_ID,
                            str(item.get("id", "") or ""),
                            normalize_contract_id(item.get("contract_id")) or normalize_contract_id(item.get("business_group")),
                            str(item.get("business_group") or item.get("contract_display_name") or "").strip(),
                            str(item.get("match_type", "") or "PROCESS-NAME").strip().upper(),
                            str(item.get("value", "") or "").strip(),
                            int(item.get("sort_order", 0) or 0),
                            1 if bool(item.get("enabled", True)) else 0,
                            updated_at,
                        ),
                    )

            external_programs_row = self._conn.execute(
                "SELECT value_json FROM runtime_settings WHERE key=?",
                ("surge.external_proxy_programs",),
            ).fetchone()
            external_programs = (
                _json_loads(str(external_programs_row["value_json"] or "null"))
                if external_programs_row
                else None
            )
            if isinstance(external_programs, list):
                for item in external_programs:
                    if not isinstance(item, dict):
                        continue
                    args = item.get("args")
                    self._conn.execute(
                        """
                        INSERT INTO scenario_external_proxy_programs (
                            scenario_id, id, contract_id, business_group, program_path, args_json, local_port,
                            name, sort_order, enabled, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            _DEFAULT_SCENARIO_ID,
                            str(item.get("id", "") or ""),
                            normalize_contract_id(item.get("contract_id")) or normalize_contract_id(item.get("business_group")),
                            str(item.get("business_group") or item.get("contract_display_name") or "").strip(),
                            str(item.get("program_path", "") or "").strip(),
                            _json_dumps(args if isinstance(args, list) else []),
                            int(item.get("local_port", 0) or 0),
                            str(item.get("name", "") or "").strip(),
                            int(item.get("sort_order", 0) or 0),
                            1 if bool(item.get("enabled", True)) else 0,
                            updated_at,
                        ),
                    )

            self._conn.commit()

    def _backfill_service_catalog_entries(self, *, preserve_manual_contract: bool = False) -> None:
        with self._lock:
            rows = self._conn.execute("SELECT name FROM rule_categories ORDER BY name").fetchall()
            seen = {str(row["name"] or "") for row in rows}
            for category_name in seen:
                self._sync_service_catalog_entry_locked(
                    category_name,
                    preserve_manual_contract=preserve_manual_contract,
                )
            if seen:
                placeholders = ", ".join("?" for _ in seen)
                self._conn.execute(
                    f"DELETE FROM service_catalog_entries WHERE category_name NOT IN ({placeholders})",
                    tuple(sorted(seen)),
                )
            else:
                self._conn.execute("DELETE FROM service_catalog_entries")
            for category_name in sorted(seen):
                self._sync_default_scenario_category_state_locked(category_name)
            self._conn.commit()

    def _route_contract_display_name_conflict_locked(
        self,
        display_name: str,
        *,
        exclude_id: str = "",
        owner_scenario_id: str = "",
    ) -> bool:
        safe_display_name = str(display_name or "").strip()
        if not safe_display_name:
            return False
        safe_owner = str(owner_scenario_id or "").strip()
        if safe_owner:
            row = self._conn.execute(
                """
                SELECT id FROM route_contracts
                WHERE display_name=? AND id<>? AND (owner_scenario_id='' OR owner_scenario_id=?)
                LIMIT 1
                """,
                (safe_display_name, str(exclude_id or "").strip(), safe_owner),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT id FROM route_contracts WHERE display_name=? AND id<>? LIMIT 1",
                (safe_display_name, str(exclude_id or "").strip()),
            ).fetchone()
        return row is not None

    @staticmethod
    def _validate_route_contract_identity(raw_id: object, normalized_id: str) -> None:
        raw_text = str(raw_id or "").strip()
        if raw_text in {
            ROUTE_NATIVE_DIRECT_TARGET,
            ROUTE_NATIVE_REJECT_TARGET,
            *RESERVED_ROUTE_ACTION_IDS,
        } or normalized_id in RESERVED_ROUTE_ACTION_IDS:
            raise ValueError("reserved route action id")

    @staticmethod
    def _validate_route_contract_display_name(
        contract_id: str,
        display_name: object,
        routing_action: object,
    ) -> None:
        if normalize_route_action(routing_action) != ROUTE_ACTION_PROXY:
            return
        safe_name = str(display_name or "").strip()
        if safe_name not in ROUTE_RENDERER_RESERVED_GROUP_NAMES:
            return
        raise ValueError("display_name is reserved by the subscription renderer")

    def _validated_contract_policy(
        self,
        contract_id: str,
        *,
        strategy_type: object,
        failure_action: object,
        routing_action: object,
        primary_pools: list[str],
        fallback_pools: list[str],
        existing: RouteContract | None = None,
    ) -> tuple[str, str, str, list[str], list[str]]:
        normalized_strategy = self._normalize_contract_strategy(strategy_type)
        normalized_failure = self._normalize_contract_failure_action(failure_action)
        normalized_action = self._normalize_contract_routing_action(routing_action)
        raw_primary = [str(pool or "").strip() for pool in primary_pools if str(pool or "").strip()]
        raw_fallback = [str(pool or "").strip() for pool in fallback_pools if str(pool or "").strip()]
        unknown_pools = [pool for pool in [*raw_primary, *raw_fallback] if pool not in POOL_IDS]
        if unknown_pools:
            raise ValueError(f"unknown pool: {unknown_pools[0]}")
        clean_primary = raw_primary
        clean_fallback = raw_fallback
        if normalized_action in {ROUTE_ACTION_DIRECT, ROUTE_ACTION_REJECT}:
            if clean_primary or clean_fallback:
                raise ValueError("direct/reject contracts cannot have pools")
            clean_primary = []
            clean_fallback = []
        if normalized_action == ROUTE_ACTION_PROXY and not clean_primary:
            raise ValueError("primary_pools is required")

        if len(clean_primary) != len(set(clean_primary)):
            raise ValueError("primary_pools must not contain duplicates")
        if len(clean_fallback) != len(set(clean_fallback)):
            raise ValueError("fallback_pools must not contain duplicates")
        if normalized_action == ROUTE_ACTION_PROXY:
            quality_families = {
                "high" if pool in {POOL_HQ_PREMIUM, POOL_HQ_STANDARD, POOL_CHAIN_HOME}
                else pool
                for pool in [*clean_primary, *clean_fallback]
            }
            if POOL_DIRECT in quality_families or len(quality_families) > 1:
                raise ValueError("proxy contract pools must stay within one quality family")
        if normalized_failure == "degrade" and not clean_fallback and normalized_action == ROUTE_ACTION_PROXY:
            raise ValueError("degrade failure_action requires fallback_pools")
        if normalized_failure == "degrade" and normalized_action == ROUTE_ACTION_PROXY:
            primary_family = {
                "high" if pool in {POOL_HQ_PREMIUM, POOL_HQ_STANDARD, POOL_CHAIN_HOME}
                else pool
                for pool in clean_primary
            }
            fallback_family = {
                "high" if pool in {POOL_HQ_PREMIUM, POOL_HQ_STANDARD, POOL_CHAIN_HOME}
                else pool
                for pool in clean_fallback
            }
            if primary_family and fallback_family != primary_family:
                raise ValueError("degrade fallback_pools must stay within the primary quality family")
        return normalized_strategy, normalized_failure, normalized_action, clean_primary, clean_fallback

    def list_route_contracts(self, scenario_id: str | None = None) -> list[RouteContract]:
        safe_scenario_id = str(scenario_id or "").strip()
        with self._lock:
            if safe_scenario_id and safe_scenario_id != _DEFAULT_SCENARIO_ID:
                rows = self._conn.execute(
                    """
                    SELECT * FROM route_contracts
                    WHERE owner_scenario_id='' OR owner_scenario_id=?
                    ORDER BY sort_order, id
                    """,
                    (safe_scenario_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM route_contracts WHERE owner_scenario_id='' ORDER BY sort_order, id"
                ).fetchall()
            return [self._row_to_route_contract(row) for row in rows]

    def get_route_contract(self, contract_id: str) -> RouteContract | None:
        safe_id = normalize_contract_id(contract_id)
        if not safe_id:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM route_contracts WHERE id=?",
                (safe_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_route_contract(row)

    def create_route_contract(self, contract: RouteContract) -> RouteContract:
        raw_id = str(contract.id or "").strip()
        normalized_id = normalize_contract_id(raw_id)
        if not normalized_id:
            raise ValueError("invalid contract id")
        self._validate_route_contract_identity(raw_id, normalized_id)
        if self.get_route_contract(normalized_id):
            raise ValueError("contract already exists")
        safe_owner = str(contract.owner_scenario_id or "").strip()
        if safe_owner == _DEFAULT_SCENARIO_ID:
            safe_owner = ""
        if safe_owner and not self.get_scenario(safe_owner):
            raise ValueError("owner scenario not found")
        next_display_name = str(contract.display_name or "").strip()
        if not next_display_name:
            raise ValueError("display_name is required")
        strategy_type, failure_action, routing_action, primary_pools, fallback_pools = self._validated_contract_policy(
            normalized_id,
            strategy_type=contract.strategy_type,
            failure_action=contract.failure_action,
            routing_action=contract.routing_action,
            primary_pools=list(contract.primary_pools),
            fallback_pools=list(contract.fallback_pools),
            existing=None,
        )
        self._validate_route_contract_display_name(
            normalized_id,
            next_display_name,
            routing_action,
        )
        now = _utc_now()
        with self._lock:
            if self._route_contract_display_name_conflict_locked(
                next_display_name,
                exclude_id=normalized_id,
                owner_scenario_id=safe_owner,
            ):
                raise ValueError("display_name already used by another contract")
            self._conn.execute(
                """
                        INSERT INTO route_contracts (
                    id, display_name, description, strategy_type, failure_action, routing_action, editable,
                    enabled, sort_order, owner_scenario_id, is_system, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_id,
                    next_display_name,
                    str(contract.description or "").strip(),
                    strategy_type,
                    failure_action,
                    routing_action,
                    1,
                    1 if bool(contract.enabled) else 0,
                    int(contract.sort_order or 0),
                    safe_owner,
                    0,
                    now,
                ),
            )
            for sort_order, pool_name in enumerate(primary_pools):
                self._conn.execute(
                    """
                    INSERT INTO route_contract_pool_bindings (contract_id, role, pool_name, sort_order)
                    VALUES (?, 'primary', ?, ?)
                    """,
                    (normalized_id, pool_name, sort_order),
                )
            for sort_order, pool_name in enumerate(fallback_pools):
                self._conn.execute(
                    """
                    INSERT INTO route_contract_pool_bindings (contract_id, role, pool_name, sort_order)
                    VALUES (?, 'fallback', ?, ?)
                    """,
                    (normalized_id, pool_name, sort_order),
                )
            self._conn.commit()
        saved = self.get_route_contract(normalized_id)
        if not saved:
            raise ValueError("failed to create contract")
        self._notify_policy_backup("route-contract-create")
        return saved

    def save_route_contract(self, contract: RouteContract) -> RouteContract:
        raw_id = str(contract.id or "").strip()
        normalized_id = normalize_contract_id(raw_id)
        if not normalized_id:
            raise ValueError("invalid contract id")
        self._validate_route_contract_identity(raw_id, normalized_id)
        existing = self.get_route_contract(normalized_id)
        if not existing:
            raise ValueError("contract not found")
        strategy_type, failure_action, routing_action, primary_pools, fallback_pools = self._validated_contract_policy(
            normalized_id,
            strategy_type=contract.strategy_type,
            failure_action=contract.failure_action,
            routing_action=contract.routing_action,
            primary_pools=list(contract.primary_pools),
            fallback_pools=list(contract.fallback_pools),
            existing=existing,
        )
        next_display_name = str(contract.display_name or existing.display_name or contract_display_name(normalized_id)).strip()
        next_description = str(contract.description if contract.description is not None else existing.description).strip()
        self._validate_route_contract_display_name(
            normalized_id,
            next_display_name,
            routing_action,
        )
        now = _utc_now()
        with self._lock:
            if self._route_contract_display_name_conflict_locked(
                next_display_name or contract_display_name(normalized_id),
                exclude_id=normalized_id,
                owner_scenario_id=str(existing.owner_scenario_id or "").strip(),
            ):
                raise ValueError("display_name already used by another contract")
            self._conn.execute(
                """
                UPDATE route_contracts
                SET display_name=?, description=?, strategy_type=?, failure_action=?, routing_action=?, editable=?, enabled=?, sort_order=?, owner_scenario_id=?, is_system=?, updated_at=?
                WHERE id=?
                """,
                (
                    next_display_name or contract_display_name(normalized_id),
                    next_description,
                    strategy_type,
                    failure_action,
                    routing_action,
                    1,
                    1 if contract.enabled else 0,
                    int(contract.sort_order if contract.sort_order is not None else existing.sort_order),
                    str(existing.owner_scenario_id or "").strip(),
                    0,
                    now,
                    normalized_id,
                ),
            )
            self._conn.execute(
                "DELETE FROM route_contract_pool_bindings WHERE contract_id=?",
                (normalized_id,),
            )
            for sort_order, pool_name in enumerate(primary_pools):
                self._conn.execute(
                    """
                    INSERT INTO route_contract_pool_bindings (contract_id, role, pool_name, sort_order)
                    VALUES (?, 'primary', ?, ?)
                    """,
                    (normalized_id, pool_name, sort_order),
                )
            for sort_order, pool_name in enumerate(fallback_pools):
                self._conn.execute(
                    """
                    INSERT INTO route_contract_pool_bindings (contract_id, role, pool_name, sort_order)
                    VALUES (?, 'fallback', ?, ?)
                    """,
                    (normalized_id, pool_name, sort_order),
                )
            self._conn.commit()
        saved = self.get_route_contract(normalized_id)
        if not saved:
            raise ValueError("failed to save contract")
        self._notify_policy_backup("route-contract-save")
        return saved

    def delete_route_contract(self, contract_id: str) -> bool:
        safe_id = normalize_contract_id(contract_id)
        if not safe_id:
            return False
        with self._lock:
            self._conn.execute("DELETE FROM route_contract_pool_bindings WHERE contract_id=?", (safe_id,))
            self._conn.execute("DELETE FROM scenario_route_contract_views WHERE contract_id=?", (safe_id,))
            cur = self._conn.execute("DELETE FROM route_contracts WHERE id=?", (safe_id,))
            self._conn.commit()
        deleted = int(cur.rowcount or 0) > 0
        if deleted:
            self._notify_policy_backup("route-contract-delete")
        return deleted

    def list_scenario_route_contract_views(self, scenario_id: str) -> list[RouteContractView]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM scenario_route_contract_views
                WHERE scenario_id=?
                ORDER BY sort_order, contract_id
                """,
                (safe_id,),
            ).fetchall()
        return [self._row_to_route_contract_view(row) for row in rows]

    def get_scenario_route_contract_view(self, scenario_id: str, contract_id: str) -> RouteContractView | None:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        safe_contract_id = normalize_contract_id(contract_id)
        if not safe_contract_id:
            return None
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM scenario_route_contract_views
                WHERE scenario_id=? AND contract_id=?
                """,
                (safe_id, safe_contract_id),
            ).fetchone()
        return self._row_to_route_contract_view(row) if row else None

    def _list_scenario_route_contract_view_rows_locked(self, scenario_id: str) -> dict[str, RouteContractView]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        rows = self._conn.execute(
            """
            SELECT * FROM scenario_route_contract_views
            WHERE scenario_id=?
            ORDER BY sort_order, contract_id
            """,
            (safe_id,),
        ).fetchall()
        return {
            str(item.contract_id or "").strip(): item
            for item in (self._row_to_route_contract_view(row) for row in rows)
            if str(item.contract_id or "").strip()
        }

    def _get_route_contract_locked(self, contract_id: str) -> RouteContract | None:
        safe_contract_id = normalize_contract_id(contract_id)
        if not safe_contract_id:
            return None
        row = self._conn.execute(
            "SELECT * FROM route_contracts WHERE id=?",
            (safe_contract_id,),
        ).fetchone()
        return self._row_to_route_contract(row) if row else None

    def _route_contract_view_semantically_equal(
        self,
        left: RouteContractView | None,
        right: RouteContractView | None,
    ) -> bool:
        if left is None or right is None:
            return left is right
        return (
            str(left.display_name or "").strip() == str(right.display_name or "").strip()
            and str(left.description or "").strip() == str(right.description or "").strip()
            and str(left.llm_routing_intent or "").strip() == str(right.llm_routing_intent or "").strip()
            and bool(left.enabled) == bool(right.enabled)
            and int(left.sort_order or 0) == int(right.sort_order or 0)
            and bool(left.is_default) == bool(right.is_default)
        )

    def _effective_scenario_route_contract_view_map_locked(self, scenario_id: str) -> dict[str, RouteContractView]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        default_map = self._list_scenario_route_contract_view_rows_locked(_DEFAULT_SCENARIO_ID)
        if safe_id == _DEFAULT_SCENARIO_ID:
            return default_map
        explicit_map = self._list_scenario_route_contract_view_rows_locked(safe_id)
        merged = dict(default_map)
        merged.update(explicit_map)
        return merged

    def _prepare_scenario_route_contract_view_map_locked(
        self,
        scenario_id: str,
        view: RouteContractView,
    ) -> tuple[dict[str, RouteContractView], RouteContractView]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        safe_contract_id = normalize_contract_id(view.contract_id)
        if not safe_contract_id:
            raise ValueError("invalid contract_id")
        contract = self._get_route_contract_locked(safe_contract_id)
        if contract is None:
            raise ValueError("contract not found")
        display_name = str(view.display_name or "").strip() or str(contract.display_name or "")
        self._validate_route_contract_display_name(
            safe_contract_id,
            display_name,
            contract.routing_action,
        )
        description = str(view.description or "").strip()
        llm_routing_intent = str(view.llm_routing_intent or "").strip()
        enabled = bool(view.enabled)
        is_default = bool(view.is_default)
        if normalize_route_action(contract.routing_action) == ROUTE_ACTION_REJECT and is_default:
            raise ValueError("reject contract cannot be the default contract")
        if is_default and not enabled:
            raise ValueError("default contract must be enabled")

        effective_map = self._effective_scenario_route_contract_view_map_locked(safe_id)
        prepared_view = RouteContractView(
            scenario_id=safe_id,
            contract_id=safe_contract_id,
            display_name=display_name,
            description=description,
            llm_routing_intent=llm_routing_intent,
            enabled=enabled,
            sort_order=int(view.sort_order or 0),
            is_default=is_default,
            updated_at=str(view.updated_at or ""),
        )
        effective_map[safe_contract_id] = prepared_view
        if is_default:
            for contract_id, item in list(effective_map.items()):
                effective_map[contract_id] = RouteContractView(
                    scenario_id=safe_id,
                    contract_id=contract_id,
                    display_name=str(item.display_name or ""),
                    description=str(item.description or ""),
                    llm_routing_intent=str(item.llm_routing_intent or ""),
                    enabled=bool(item.enabled),
                    sort_order=int(item.sort_order or 0),
                    is_default=contract_id == safe_contract_id,
                    updated_at=str(item.updated_at or ""),
                )
        duplicate = next(
            (
                item.contract_id
                for item in effective_map.values()
                if item.contract_id != safe_contract_id
                and str(item.display_name or "").strip() == display_name
            ),
            "",
        )
        if duplicate:
            raise ValueError("display_name already used by another contract in this scenario")
        return effective_map, prepared_view

    def _persist_scenario_route_contract_view_map_locked(
        self,
        scenario_id: str,
        effective_map: dict[str, RouteContractView],
        *,
        now: str,
    ) -> None:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        if safe_id == _DEFAULT_SCENARIO_ID:
            desired_rows = list(effective_map.values())
        else:
            inherited_map = self._list_scenario_route_contract_view_rows_locked(_DEFAULT_SCENARIO_ID)
            desired_rows = [
                item
                for contract_id, item in effective_map.items()
                if not self._route_contract_view_semantically_equal(item, inherited_map.get(contract_id))
            ]
        desired_rows.sort(key=lambda item: (int(item.sort_order or 0), str(item.contract_id or "").strip()))
        self._conn.execute(
            "DELETE FROM scenario_route_contract_views WHERE scenario_id=?",
            (safe_id,),
        )
        for item in desired_rows:
            self._conn.execute(
                """
                INSERT INTO scenario_route_contract_views (
                    scenario_id, contract_id, display_name, description, llm_routing_intent,
                    enabled, sort_order, is_default, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    safe_id,
                    str(item.contract_id or "").strip(),
                    str(item.display_name or "").strip(),
                    str(item.description or "").strip(),
                    str(item.llm_routing_intent or "").strip(),
                    1 if bool(item.enabled) else 0,
                    int(item.sort_order or 0),
                    1 if bool(item.is_default) else 0,
                    now,
                ),
            )

    def validate_scenario_route_contract_view(self, scenario_id: str, view: RouteContractView) -> RouteContractView:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        with self._lock:
            _, prepared_view = self._prepare_scenario_route_contract_view_map_locked(safe_id, view)
        return prepared_view

    def save_scenario_route_contract_view(self, scenario_id: str, view: RouteContractView) -> RouteContractView:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        now = _utc_now()
        with self._lock:
            effective_map, prepared_view = self._prepare_scenario_route_contract_view_map_locked(safe_id, view)
            self._persist_scenario_route_contract_view_map_locked(
                safe_id,
                effective_map,
                now=now,
            )
            self._conn.commit()
        saved = self.get_scenario_route_contract_view(safe_id, prepared_view.contract_id)
        if safe_id != _DEFAULT_SCENARIO_ID and saved is None:
            # In sparse override mode a scenario can inherit the default view exactly.
            saved = self.get_scenario_route_contract_view(_DEFAULT_SCENARIO_ID, prepared_view.contract_id)
        if not saved:
            raise ValueError("failed to save scenario contract view")
        self._notify_policy_backup("scenario-contract-view-save")
        return saved

    def delete_scenario_route_contract_view(self, scenario_id: str, contract_id: str) -> bool:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        safe_contract_id = normalize_contract_id(contract_id)
        if not safe_contract_id:
            return False
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM scenario_route_contract_views WHERE scenario_id=? AND contract_id=?",
                (safe_id, safe_contract_id),
            )
            self._conn.commit()
        if int(cur.rowcount or 0) > 0:
            self._notify_policy_backup("scenario-contract-view-delete")
            return True
        return False

    def list_service_catalog_entries(self) -> list[ServiceCatalogEntry]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM service_catalog_entries
                ORDER BY catalog_group, sort_order, category_name
                """
            ).fetchall()
            return [self._row_to_service_catalog_entry(row) for row in rows]

    def get_service_catalog_entry(self, category_name: str) -> ServiceCatalogEntry | None:
        safe_name = str(category_name or "").strip()
        if not safe_name:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM service_catalog_entries WHERE category_name=?",
                (safe_name,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_service_catalog_entry(row)

    def save_service_catalog_entry(self, entry: ServiceCatalogEntry) -> ServiceCatalogEntry:
        safe_name = str(entry.category_name or "").strip()
        if not safe_name:
            raise ValueError("category_name is required")
        if not self.get_rule_category(safe_name):
            raise ValueError("category not found")
        contract_id = normalize_contract_id(entry.contract_id)
        if not contract_id:
            raise ValueError("invalid contract_id")
        now = _utc_now()
        with self._lock:
            existing = self._conn.execute(
                "SELECT source FROM service_catalog_entries WHERE category_name=?",
                (safe_name,),
            ).fetchone()
            source = str(entry.source or "") or (str(existing["source"] or "") if existing else "")
            if not source:
                source = "manual"
            catalog_group = str(entry.catalog_group or "").strip()
            self._conn.execute(
                """
                INSERT INTO service_catalog_entries (
                    category_name, catalog_group, contract_id, sort_order, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(category_name) DO UPDATE SET
                    catalog_group=excluded.catalog_group,
                    contract_id=excluded.contract_id,
                    sort_order=excluded.sort_order,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (
                    safe_name,
                    catalog_group,
                    contract_id,
                    int(entry.sort_order or 0),
                    source,
                    now,
                ),
            )
            if catalog_group:
                self._conn.execute(
                    """
                    INSERT INTO pin_groups (group_name, sort_order, mode, description, updated_at)
                    VALUES (?, COALESCE((SELECT sort_order FROM pin_groups WHERE group_name=?), 0), ?, COALESCE((SELECT description FROM pin_groups WHERE group_name=?), ''), ?)
                    ON CONFLICT(group_name) DO UPDATE SET
                        updated_at=excluded.updated_at
                    """,
                    (
                        catalog_group,
                        catalog_group,
                        self._pin_group_mode_locked(catalog_group),
                        catalog_group,
                        now,
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO pinned_categories (category_name, pin_group, sort_order, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(category_name) DO UPDATE SET
                        pin_group=excluded.pin_group,
                        sort_order=excluded.sort_order,
                        updated_at=excluded.updated_at
                    """,
                    (safe_name, catalog_group, int(entry.sort_order or 0), now),
                )
            else:
                self._conn.execute(
                    "DELETE FROM pinned_categories WHERE category_name=?",
                    (safe_name,),
                )
            self._conn.commit()
        saved = self.get_service_catalog_entry(safe_name)
        if not saved:
            raise ValueError("failed to save service catalog entry")
        self.save_scenario_service_catalog_entry(_DEFAULT_SCENARIO_ID, saved)
        self._notify_policy_backup("catalog-save")
        return saved

    def list_general_profiles(self) -> list[GeneralProfile]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM general_profiles ORDER BY is_system_default DESC, updated_at DESC, id"
            ).fetchall()
            return [self._row_to_general_profile(row) for row in rows]

    def get_general_profile(self, profile_id: str) -> GeneralProfile | None:
        safe_id = str(profile_id or "").strip()
        if not safe_id:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM general_profiles WHERE id=?",
                (safe_id,),
            ).fetchone()
            if not row:
                return None
            return self._row_to_general_profile(row)

    def get_default_general_profile(self) -> GeneralProfile | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM general_profiles WHERE is_system_default=1 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if row:
                return self._row_to_general_profile(row)
        return None

    def save_general_profile(self, profile: GeneralProfile) -> GeneralProfile:
        safe_id = str(profile.id or "").strip() or _DEFAULT_GENERAL_PROFILE_ID
        now = _utc_now()
        settings = normalize_lazycat_profile_settings(profile.settings or {})
        editor_state = normalize_profile_editor_state(profile.editor_state, legacy_default=True)
        is_system_default = bool(profile.is_system_default)
        display_name = str(profile.name or "LazyCat Default")
        with self._lock:
            if is_system_default:
                self._conn.execute("UPDATE general_profiles SET is_system_default=0")
            self._conn.execute(
                """
                INSERT INTO general_profiles (id, name, settings_json, editor_state_json, is_system_default, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    settings_json=excluded.settings_json,
                    editor_state_json=excluded.editor_state_json,
                    is_system_default=excluded.is_system_default,
                    updated_at=excluded.updated_at
                """,
                (
                    safe_id,
                    display_name,
                    _json_dumps(settings),
                    _json_dumps(editor_state),
                    1 if is_system_default else 0,
                    now,
                ),
            )
            if is_system_default or safe_id == _DEFAULT_GENERAL_PROFILE_ID:
                self._conn.execute(
                    """
                    INSERT INTO lazycat_profile_settings (id, settings_json, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        settings_json=excluded.settings_json,
                        updated_at=excluded.updated_at
                    """,
                    (_json_dumps(settings), now),
                )
            self._conn.commit()
        if is_system_default or safe_id == _DEFAULT_GENERAL_PROFILE_ID:
            self.save_scenario(
                ScenarioProfile(
                    id=_DEFAULT_SCENARIO_ID,
                    slug=_DEFAULT_SCENARIO_SLUG,
                    name="默认场景",
                    description="Migrated from the previous global LazyCat profile",
                    enabled=True,
                    sort_order=0,
                    settings=settings,
                    editor_state=default_profile_editor_state(legacy=False),
                    updated_at=now,
                )
            )
        saved = self.get_general_profile(safe_id)
        if not saved:
            raise ValueError("failed to save general profile")
        return saved

    def delete_general_profile(self, profile_id: str) -> bool:
        safe_id = str(profile_id or "").strip()
        if not safe_id:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT is_system_default FROM general_profiles WHERE id=?",
                (safe_id,),
            ).fetchone()
            if not row:
                return False
            if int(row["is_system_default"] or 0):
                raise ValueError("cannot delete the system default profile")
            self._conn.execute("DELETE FROM general_profiles WHERE id=?", (safe_id,))
            self._conn.commit()
        return True

    def list_scenarios(self) -> list[ScenarioProfile]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM scenario_profiles ORDER BY sort_order, updated_at DESC, id"
            ).fetchall()
            return [self._row_to_scenario_profile(row) for row in rows]

    def get_scenario(self, scenario_id: str) -> ScenarioProfile | None:
        safe_id = str(scenario_id or "").strip()
        if not safe_id:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM scenario_profiles WHERE id=?",
                (safe_id,),
            ).fetchone()
            return self._row_to_scenario_profile(row) if row else None

    def get_scenario_by_slug(self, slug: str) -> ScenarioProfile | None:
        safe_slug = str(slug or "").strip()
        if not safe_slug:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM scenario_profiles WHERE slug=?",
                (safe_slug,),
            ).fetchone()
            return self._row_to_scenario_profile(row) if row else None

    def save_scenario(self, scenario: ScenarioProfile) -> ScenarioProfile:
        safe_id = str(scenario.id or "").strip() or _DEFAULT_SCENARIO_ID
        safe_slug = str(scenario.slug or "").strip() or _DEFAULT_SCENARIO_SLUG
        now = _utc_now()
        settings = normalize_lazycat_profile_settings(scenario.settings or {})
        editor_state = normalize_profile_editor_state(
            scenario.editor_state,
            legacy_default=safe_id != _DEFAULT_SCENARIO_ID,
        )
        existing = self.get_scenario(safe_id)
        identity_changed = (
            existing is None
            or existing.slug != safe_slug
            or existing.name != str(scenario.name or "默认场景")
            or existing.description != str(scenario.description or "")
            or bool(existing.enabled) != bool(scenario.enabled)
            or int(existing.sort_order or 0) != int(scenario.sort_order or 0)
        )
        try:
            with self._lock:
                self._conn.execute(
                    """
                    INSERT INTO scenario_profiles (
                        id, slug, name, description, enabled, sort_order, settings_json, editor_state_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        slug=excluded.slug,
                        name=excluded.name,
                        description=excluded.description,
                        enabled=excluded.enabled,
                        sort_order=excluded.sort_order,
                        settings_json=excluded.settings_json,
                        editor_state_json=excluded.editor_state_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        safe_id,
                        safe_slug,
                        str(scenario.name or "默认场景"),
                        str(scenario.description or ""),
                        1 if scenario.enabled else 0,
                        int(scenario.sort_order or 0),
                        _json_dumps(settings),
                        _json_dumps(editor_state),
                        now,
                    ),
                )
                self._conn.commit()
        except sqlite3.IntegrityError as exc:
            if "scenario_profiles.slug" in str(exc):
                raise ValueError("scenario slug already exists") from exc
            raise
        saved = self.get_scenario(safe_id)
        if not saved:
            raise ValueError("failed to save scenario")
        if identity_changed:
            self._notify_policy_backup("scenario-save")
        return saved

    def delete_scenario(self, scenario_id: str) -> bool:
        safe_id = str(scenario_id or "").strip()
        if not safe_id:
            return False
        if safe_id == _DEFAULT_SCENARIO_ID:
            raise ValueError("cannot delete the default scenario")
        with self._lock:
            enabled_count = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM scenario_profiles WHERE enabled=1"
                ).fetchone()[0]
            )
            row = self._conn.execute(
                "SELECT enabled FROM scenario_profiles WHERE id=?",
                (safe_id,),
            ).fetchone()
            if not row:
                return False
            if enabled_count <= 1 and bool(int(row["enabled"] or 0)):
                raise ValueError("cannot delete the last enabled scenario")
            for table in (
                "scenario_category_states",
                "scenario_route_contract_views",
                "scenario_pin_groups",
                "scenario_custom_rules",
                "scenario_process_rules",
                "scenario_external_proxy_programs",
            ):
                self._conn.execute(f"DELETE FROM {table} WHERE scenario_id=?", (safe_id,))
            self._conn.execute("DELETE FROM scenario_profiles WHERE id=?", (safe_id,))
            self._conn.commit()
        self._notify_policy_backup("scenario-delete")
        return True

    def clone_scenario_state(self, source_scenario_id: str, target_scenario_id: str) -> None:
        source_id = str(source_scenario_id or "").strip()
        target_id = str(target_scenario_id or "").strip()
        if not source_id or not target_id:
            raise ValueError("scenario id is required")
        with self._lock:
            for table, columns in (
                (
                    "scenario_category_states",
                    "category_name, assigned_group, contract_id, catalog_group, sort_order, rule_count, "
                    "rule_source, category_type, updated_at, locked, system_directness, "
                    "system_default_group, system_default_locked, override_group, override_active, "
                    "directness_override, lock_source",
                ),
                (
                    "scenario_route_contract_views",
                    "contract_id, display_name, description, llm_routing_intent, enabled, sort_order, is_default, updated_at",
                ),
                (
                    "scenario_pin_groups",
                    "group_name, sort_order, mode, description, updated_at",
                ),
                (
                    "scenario_custom_rules",
                    "id, rule_type, value, target_contract_id, target_group, category_name, created_at",
                ),
                (
                    "scenario_process_rules",
                    "id, contract_id, business_group, match_type, value, sort_order, enabled, updated_at",
                ),
                (
                    "scenario_external_proxy_programs",
                    "id, contract_id, business_group, program_path, args_json, local_port, name, sort_order, enabled, updated_at",
                ),
            ):
                self._conn.execute(f"DELETE FROM {table} WHERE scenario_id=?", (target_id,))
                self._conn.execute(
                    f"INSERT INTO {table} (scenario_id, {columns}) "
                    f"SELECT ?, {columns} FROM {table} WHERE scenario_id=?",
                    (target_id, source_id),
                )
            self._conn.commit()
        self._notify_policy_backup("scenario-clone-state")

    def list_scenario_categories(self, scenario_id: str) -> list[RuleCategory]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    rc.name AS name,
                    COALESCE(sc.assigned_group, rc.assigned_group) AS assigned_group,
                    COALESCE(sc.rule_count, rc.rule_count) AS rule_count,
                    COALESCE(sc.rule_source, rc.rule_source) AS rule_source,
                    COALESCE(sc.category_type, rc.category_type) AS category_type,
                    COALESCE(sc.updated_at, rc.updated_at) AS updated_at,
                    COALESCE(sc.locked, rc.locked) AS locked,
                    COALESCE(sc.system_directness, rc.system_directness) AS system_directness,
                    COALESCE(sc.system_default_group, rc.system_default_group) AS system_default_group,
                    COALESCE(sc.system_default_locked, rc.system_default_locked) AS system_default_locked,
                    COALESCE(sc.override_group, rc.override_group) AS override_group,
                    COALESCE(sc.override_active, rc.override_active) AS override_active,
                    COALESCE(sc.directness_override, rc.directness_override) AS directness_override,
                    COALESCE(sc.lock_source, rc.lock_source) AS lock_source
                FROM rule_categories rc
                LEFT JOIN scenario_category_states sc
                    ON sc.scenario_id=? AND sc.category_name=rc.name
                ORDER BY rc.name
                """,
                (safe_id,),
            ).fetchall()
        return [self._row_to_rule_category(row) for row in rows]

    def list_scenario_service_catalog_entries(self, scenario_id: str) -> list[ServiceCatalogEntry]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    rc.name AS category_name,
                    CASE
                        WHEN sc.catalog_group IS NULL OR sc.catalog_group = ?
                            THEN COALESCE(sce.catalog_group, pc.pin_group, '')
                        ELSE sc.catalog_group
                    END AS catalog_group,
                    COALESCE(NULLIF(sc.contract_id, ''), sce.contract_id, '') AS contract_id,
                    CASE
                        WHEN sc.catalog_group IS NULL OR sc.catalog_group = ?
                            THEN COALESCE(sce.sort_order, pc.sort_order, 0)
                        ELSE COALESCE(sc.sort_order, 0)
                    END AS sort_order,
                    'scenario' AS source,
                    COALESCE(sc.updated_at, sce.updated_at, rc.updated_at) AS updated_at
                FROM rule_categories rc
                LEFT JOIN scenario_category_states sc
                    ON sc.scenario_id=? AND sc.category_name=rc.name
                LEFT JOIN service_catalog_entries sce
                    ON sce.category_name=rc.name
                LEFT JOIN pinned_categories pc
                    ON pc.category_name=rc.name
                WHERE (
                    CASE
                        WHEN sc.catalog_group IS NULL OR sc.catalog_group = ?
                            THEN COALESCE(sce.catalog_group, pc.pin_group, '')
                        ELSE sc.catalog_group
                    END
                ) <> ''
                    OR COALESCE(NULLIF(sc.contract_id, ''), sce.contract_id, '') <> ''
                ORDER BY catalog_group, sort_order, category_name
                """,
                (
                    _SCENARIO_CATALOG_GROUP_INHERIT,
                    _SCENARIO_CATALOG_GROUP_INHERIT,
                    safe_id,
                    _SCENARIO_CATALOG_GROUP_INHERIT,
                ),
            ).fetchall()
        return [self._row_to_service_catalog_entry(row) for row in rows]

    def list_scenario_custom_rules(
        self,
        scenario_id: str,
        *,
        category_name: str | None = None,
        global_only: bool = False,
    ) -> list[CustomRule]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        scenario_clauses = ["scenario_id=?"]
        scenario_params: list[object] = [safe_id]
        global_clauses: list[str] = []
        global_params: list[object] = []
        if category_name is not None:
            safe_category = str(category_name)
            scenario_clauses.append("category_name=?")
            scenario_params.append(safe_category)
            global_clauses.append("category_name=?")
            global_params.append(safe_category)
        if global_only:
            scenario_clauses.append("category_name=''")
            global_clauses.append("category_name=''")
        with self._lock:
            scenario_rows = self._conn.execute(
                f"SELECT * FROM scenario_custom_rules WHERE {' AND '.join(scenario_clauses)} ORDER BY created_at DESC, id DESC",
                tuple(scenario_params),
            ).fetchall()
            global_rows = self._conn.execute(
                f"SELECT * FROM custom_rules WHERE {' AND '.join(global_clauses) if global_clauses else '1=1'} ORDER BY created_at DESC, id DESC",
                tuple(global_params),
            ).fetchall()
        items: dict[str, CustomRule] = {}
        for row in global_rows:
            item = self._row_to_custom_rule(row)
            items[item.id] = item
        for row in scenario_rows:
            item = self._row_to_custom_rule(row)
            items[item.id] = item
        return sorted(items.values(), key=lambda entry: (entry.created_at, entry.id), reverse=True)

    def list_explicit_scenario_custom_rules(
        self,
        scenario_id: str,
        *,
        category_name: str | None = None,
    ) -> list[CustomRule]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        clauses = ["scenario_id=?"]
        params: list[object] = [safe_id]
        if category_name is not None:
            clauses.append("category_name=?")
            params.append(str(category_name))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM scenario_custom_rules WHERE {' AND '.join(clauses)} "
                "ORDER BY created_at DESC, id DESC",
                tuple(params),
            ).fetchall()
        return [
            self._row_to_custom_rule(row)
            for row in rows
        ]

    def list_scenario_pin_groups(self, scenario_id: str) -> list[dict[str, Any]]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT group_name, sort_order, mode, description, updated_at
                FROM scenario_pin_groups
                WHERE scenario_id=?
                ORDER BY sort_order, group_name
                """,
                (safe_id,),
            ).fetchall()
        return [
            {
                "group_name": str(row["group_name"] or ""),
                "sort_order": int(row["sort_order"] or 0),
                "mode": _normalize_business_group_mode(row["mode"]),
                "description": str(row["description"] or ""),
                "updated_at": str(row["updated_at"] or ""),
            }
            for row in rows
        ]

    def list_scenario_pinned_categories(self, scenario_id: str) -> list[dict[str, Any]]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT category_name, catalog_group AS pin_group, sort_order, updated_at
                FROM scenario_category_states
                WHERE scenario_id=? AND catalog_group NOT IN ('', ?)
                ORDER BY sort_order, category_name
                """,
                (safe_id, _SCENARIO_CATALOG_GROUP_INHERIT),
            ).fetchall()
        return [
            {
                "category_name": str(row["category_name"] or ""),
                "pin_group": str(row["pin_group"] or ""),
                "sort_order": int(row["sort_order"] or 0),
                "updated_at": str(row["updated_at"] or ""),
            }
            for row in rows
        ]

    def _scenario_category_baseline_locked(self, category_name: str) -> tuple[RuleCategory, ServiceCatalogEntry | None]:
        row = self._conn.execute(
            "SELECT * FROM rule_categories WHERE name=?",
            (category_name,),
        ).fetchone()
        if not row:
            raise ValueError("category not found")
        category = self._row_to_rule_category(row)
        catalog_row = self._conn.execute(
            "SELECT * FROM service_catalog_entries WHERE category_name=?",
            (category_name,),
        ).fetchone()
        catalog_entry = self._row_to_service_catalog_entry(catalog_row) if catalog_row else None
        pin_row = self._conn.execute(
            "SELECT pin_group, sort_order FROM pinned_categories WHERE category_name=?",
            (category_name,),
        ).fetchone()
        if pin_row and not catalog_entry:
            catalog_entry = ServiceCatalogEntry(
                category_name=category_name,
                catalog_group=str(pin_row["pin_group"] or ""),
                contract_id=normalize_contract_id(category.assigned_group),
                sort_order=int(pin_row["sort_order"] or 0),
                source="scenario-baseline",
            )
        return category, catalog_entry

    def _ensure_scenario_category_state_locked(self, scenario_id: str, category_name: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM scenario_category_states WHERE scenario_id=? AND category_name=?",
            (scenario_id, category_name),
        ).fetchone()
        if row:
            return
        category, catalog_entry = self._scenario_category_baseline_locked(category_name)
        now = _utc_now()
        if scenario_id == _DEFAULT_SCENARIO_ID:
            contract_id = (
                normalize_contract_id(catalog_entry.contract_id)
                if catalog_entry
                else normalize_contract_id(category.assigned_group)
            )
            catalog_group = str(catalog_entry.catalog_group or "") if catalog_entry else ""
            sort_order = int(catalog_entry.sort_order or 0) if catalog_entry else 0
        else:
            contract_id = ""
            catalog_group = _SCENARIO_CATALOG_GROUP_INHERIT
            sort_order = 0
        self._conn.execute(
            """
            INSERT INTO scenario_category_states (
                scenario_id, category_name, assigned_group, contract_id, catalog_group, sort_order,
                rule_count, rule_source, category_type, updated_at, locked, system_directness,
                system_default_group, system_default_locked, override_group, override_active,
                directness_override, lock_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scenario_id, category_name) DO NOTHING
            """,
            (
                scenario_id,
                category.name,
                str(category.assigned_group or ""),
                contract_id,
                catalog_group,
                sort_order,
                int(category.rule_count or 0),
                str(category.rule_source or ""),
                str(category.category_type or RULE_CATEGORY_TYPE_AUTO),
                now,
                1 if category.locked else 0,
                str(category.system_directness or RULE_DIRECTNESS_PROXY),
                str(category.system_default_group or ""),
                1 if category.system_default_locked else 0,
                str(category.override_group or ""),
                1 if category.override_active else 0,
                str(category.directness_override or ""),
                str(category.lock_source or ""),
            ),
        )

    def get_scenario_service_catalog_override(
        self,
        scenario_id: str,
        category_name: str,
    ) -> ServiceCatalogEntry | None:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        safe_name = str(category_name or "").strip()
        if not safe_name:
            return None
        with self._lock:
            row = self._conn.execute(
                """
                SELECT category_name, contract_id, catalog_group, sort_order, updated_at
                FROM scenario_category_states
                WHERE scenario_id=? AND category_name=?
                """,
                (safe_id, safe_name),
            ).fetchone()
        if not row:
            return None
        return ServiceCatalogEntry(
            category_name=str(row["category_name"] or ""),
            catalog_group=str(row["catalog_group"] or ""),
            contract_id=str(row["contract_id"] or ""),
            sort_order=int(row["sort_order"] or 0),
            source="scenario-override",
            updated_at=str(row["updated_at"] or ""),
        )

    def _sync_default_scenario_category_state_locked(self, category_name: str) -> bool:
        safe_name = str(category_name or "").strip()
        if not safe_name:
            return False
        self._ensure_scenario_category_state_locked(_DEFAULT_SCENARIO_ID, safe_name)
        category, catalog_entry = self._scenario_category_baseline_locked(safe_name)
        now = _utc_now()
        cur = self._conn.execute(
            """
            UPDATE scenario_category_states
            SET assigned_group=?,
                contract_id=?,
                catalog_group=?,
                sort_order=?,
                rule_count=?,
                rule_source=?,
                category_type=?,
                updated_at=?,
                locked=?,
                system_directness=?,
                system_default_group=?,
                system_default_locked=?,
                override_group=?,
                override_active=?,
                directness_override=?,
                lock_source=?
            WHERE scenario_id=? AND category_name=?
            """,
            (
                str(category.assigned_group or ""),
                normalize_contract_id(catalog_entry.contract_id) if catalog_entry else "",
                str(catalog_entry.catalog_group or "") if catalog_entry else "",
                int(catalog_entry.sort_order or 0) if catalog_entry else 0,
                int(category.rule_count or 0),
                str(category.rule_source or ""),
                str(category.category_type or RULE_CATEGORY_TYPE_AUTO),
                now,
                1 if category.locked else 0,
                str(category.system_directness or RULE_DIRECTNESS_PROXY),
                str(category.system_default_group or ""),
                1 if category.system_default_locked else 0,
                str(category.override_group or ""),
                1 if category.override_active else 0,
                str(category.directness_override or ""),
                str(category.lock_source or ""),
                _DEFAULT_SCENARIO_ID,
                safe_name,
            ),
        )
        return int(cur.rowcount or 0) > 0

    def save_scenario_service_catalog_entry(
        self,
        scenario_id: str,
        entry: ServiceCatalogEntry,
    ) -> ServiceCatalogEntry:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        safe_name = str(entry.category_name or "").strip()
        if not safe_name:
            raise ValueError("category_name is required")
        contract_id = normalize_contract_id(entry.contract_id)
        if not contract_id:
            raise ValueError("invalid contract_id")
        catalog_group = str(entry.catalog_group or "").strip()
        if entry.catalog_group == _SCENARIO_CATALOG_GROUP_INHERIT:
            catalog_group = _SCENARIO_CATALOG_GROUP_INHERIT
        now = _utc_now()
        with self._lock:
            self._ensure_scenario_category_state_locked(safe_id, safe_name)
            self._conn.execute(
                """
                UPDATE scenario_category_states
                SET contract_id=?, catalog_group=?, sort_order=?, updated_at=?
                WHERE scenario_id=? AND category_name=?
                """,
                (
                    contract_id,
                    catalog_group,
                    int(entry.sort_order or 0),
                    now,
                    safe_id,
                    safe_name,
                ),
            )
            if catalog_group not in {"", _SCENARIO_CATALOG_GROUP_INHERIT}:
                self._conn.execute(
                    """
                    INSERT INTO scenario_pin_groups (scenario_id, group_name, sort_order, mode, description, updated_at)
                    VALUES (?, ?, COALESCE((SELECT sort_order FROM scenario_pin_groups WHERE scenario_id=? AND group_name=?), 0), ?, COALESCE((SELECT description FROM scenario_pin_groups WHERE scenario_id=? AND group_name=?), ''), ?)
                    ON CONFLICT(scenario_id, group_name) DO UPDATE SET
                        updated_at=excluded.updated_at
                    """,
                    (
                        safe_id,
                        catalog_group,
                        safe_id,
                        catalog_group,
                        self._pin_group_mode_locked(catalog_group),
                        safe_id,
                        catalog_group,
                        now,
                    ),
                )
            self._conn.commit()
        saved = next(
            (item for item in self.list_scenario_service_catalog_entries(safe_id) if item.category_name == safe_name),
            None,
        )
        if not saved:
            raise ValueError("failed to save scenario catalog entry")
        self._notify_policy_backup("scenario-catalog-save")
        return saved

    def update_scenario_category_assignment(
        self,
        scenario_id: str,
        category_name: str,
        assigned_group: str,
    ) -> bool:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        safe_name = str(category_name or "").strip()
        if not safe_name:
            return False
        valid_groups = {"", RULE_DIRECTNESS_DIRECT, *QUALITY_GROUPS}
        normalized_group = str(assigned_group or "").strip()
        if normalized_group not in valid_groups:
            normalized_group = ""
        normalized_contract_id = normalize_contract_id(normalized_group)
        now = _utc_now()
        with self._lock:
            self._ensure_scenario_category_state_locked(safe_id, safe_name)
            row = self._conn.execute(
                """
                SELECT category_type, system_default_group, system_directness, locked
                FROM scenario_category_states
                WHERE scenario_id=? AND category_name=?
                """,
                (safe_id, safe_name),
            ).fetchone()
            if not row:
                return False
            category_type = str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO)
            if category_type == RULE_CATEGORY_TYPE_MANUAL:
                cur = self._conn.execute(
                    """
                    UPDATE scenario_category_states
                    SET assigned_group=?,
                        contract_id=?,
                        system_default_group=?,
                        system_default_locked=CASE WHEN locked=1 THEN 1 ELSE 0 END,
                        override_group='',
                        override_active=0,
                        directness_override='',
                        updated_at=?
                    WHERE scenario_id=? AND category_name=?
                    """,
                    (
                        normalized_group,
                        normalized_contract_id,
                        normalized_group,
                        now,
                        safe_id,
                        safe_name,
                    ),
                )
                self._conn.commit()
                updated = int(cur.rowcount or 0) > 0
                if updated:
                    self._notify_policy_backup("scenario-category-assignment")
                return updated

            system_default_group = str(row["system_default_group"] or "")
            if not system_default_group:
                system_default_group = (
                    RULE_DIRECTNESS_DIRECT
                    if str(row["system_directness"] or RULE_DIRECTNESS_PROXY) == RULE_DIRECTNESS_DIRECT
                    else ""
                )
            directness_override = ""
            if normalized_group == RULE_DIRECTNESS_DIRECT:
                directness_override = RULE_DIRECTNESS_DIRECT
            elif system_default_group == RULE_DIRECTNESS_DIRECT:
                directness_override = RULE_DIRECTNESS_PROXY
            cur = self._conn.execute(
                """
                UPDATE scenario_category_states
                SET assigned_group=?,
                    contract_id=?,
                    override_group=?,
                    override_active=1,
                    directness_override=?,
                    updated_at=?
                WHERE scenario_id=? AND category_name=?
                """,
                (
                    normalized_group,
                    normalized_contract_id,
                    normalized_group,
                    directness_override,
                    now,
                    safe_id,
                    safe_name,
                ),
            )
            self._conn.commit()
            updated = int(cur.rowcount or 0) > 0
        if updated:
            self._notify_policy_backup("scenario-category-assignment")
        return updated

    def bulk_update_scenario_service_catalog_groups(
        self,
        scenario_id: str,
        assignments: dict[str, str],
    ) -> int:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        now = _utc_now()
        updated = 0
        with self._lock:
            for category_name, catalog_group in assignments.items():
                safe_name = str(category_name or "").strip()
                if not safe_name:
                    continue
                self._ensure_scenario_category_state_locked(safe_id, safe_name)
                normalized_group = str(catalog_group or "").strip()
                cur = self._conn.execute(
                    """
                    UPDATE scenario_category_states
                    SET catalog_group=?, updated_at=?
                    WHERE scenario_id=? AND category_name=?
                    """,
                    (normalized_group, now, safe_id, safe_name),
                )
                updated += int(cur.rowcount or 0)
                if normalized_group:
                    self._conn.execute(
                        """
                        INSERT INTO scenario_pin_groups (scenario_id, group_name, sort_order, mode, description, updated_at)
                        VALUES (?, ?, COALESCE((SELECT sort_order FROM scenario_pin_groups WHERE scenario_id=? AND group_name=?), 0), ?, COALESCE((SELECT description FROM scenario_pin_groups WHERE scenario_id=? AND group_name=?), ''), ?)
                        ON CONFLICT(scenario_id, group_name) DO UPDATE SET
                            updated_at=excluded.updated_at
                        """,
                        (
                            safe_id,
                            normalized_group,
                            safe_id,
                            normalized_group,
                            self._pin_group_mode_locked(normalized_group),
                            safe_id,
                            normalized_group,
                            now,
                        ),
                    )
            self._conn.commit()
        if updated:
            self._notify_policy_backup("scenario-catalog-bulk-save")
        return updated

    def bulk_update_service_catalog_groups(
        self,
        assignments: dict[str, str],
    ) -> int:
        now = _utc_now()
        processed: list[str] = []
        groups_to_ensure: set[str] = set()
        with self._lock:
            for category_name, catalog_group in assignments.items():
                safe_name = str(category_name or "").strip()
                if not safe_name:
                    continue
                normalized_group = str(catalog_group or "").strip()
                pin_row = self._conn.execute(
                    """
                    SELECT pin_group, sort_order
                    FROM pinned_categories
                    WHERE category_name=?
                    """,
                    (safe_name,),
                ).fetchone()
                sort_order = int(pin_row["sort_order"] or 0) if pin_row else 0
                if normalized_group:
                    self._conn.execute(
                        """
                        INSERT INTO pin_groups (group_name, sort_order, mode, description, updated_at)
                        VALUES (?, COALESCE((SELECT sort_order FROM pin_groups WHERE group_name=?), 0), ?, COALESCE((SELECT description FROM pin_groups WHERE group_name=?), ''), ?)
                        ON CONFLICT(group_name) DO UPDATE SET
                            updated_at=excluded.updated_at
                        """,
                        (
                            normalized_group,
                            normalized_group,
                            self._pin_group_mode_locked(normalized_group),
                            normalized_group,
                            now,
                        ),
                    )
                    groups_to_ensure.add(normalized_group)
                    self._conn.execute(
                        """
                        INSERT INTO pinned_categories (category_name, pin_group, sort_order, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(category_name) DO UPDATE SET
                            pin_group=excluded.pin_group,
                            sort_order=excluded.sort_order,
                            updated_at=excluded.updated_at
                        """,
                        (safe_name, normalized_group, sort_order, now),
                    )
                else:
                    self._conn.execute(
                        "DELETE FROM pinned_categories WHERE category_name=?",
                        (safe_name,),
                    )
                self._sync_service_catalog_entry_locked(
                    safe_name,
                    preserve_manual_contract=False,
                )
                processed.append(safe_name)
            self._conn.commit()
        for category_name in processed:
            self._sync_default_scenario_category_state_locked(category_name)
        for group_name in sorted(groups_to_ensure):
            self.create_scenario_pin_group(
                _DEFAULT_SCENARIO_ID,
                group_name,
                mode=self._pin_group_mode_locked(group_name),
            )
        if processed:
            self._notify_policy_backup("catalog-bulk-save")
        return len(processed)

    def update_scenario_category_locked(
        self,
        scenario_id: str,
        category_name: str,
        locked: bool,
        *,
        lock_source: str = "",
    ) -> bool:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        safe_name = str(category_name or "").strip()
        if not safe_name:
            return False
        now = _utc_now()
        normalized_source = str(lock_source or "").strip()
        with self._lock:
            self._ensure_scenario_category_state_locked(safe_id, safe_name)
            cur = self._conn.execute(
                """
                UPDATE scenario_category_states
                SET locked=?, lock_source=?, updated_at=?
                WHERE scenario_id=? AND category_name=?
                """,
                (1 if locked else 0, normalized_source if locked else "", now, safe_id, safe_name),
            )
            self._conn.commit()
            updated = int(cur.rowcount or 0) > 0
        if updated:
            self._notify_policy_backup("scenario-category-lock")
        return updated

    def pin_scenario_category(
        self,
        scenario_id: str,
        name: str,
        pin_group: str,
        sort_order: int = 0,
    ) -> None:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        safe_name = str(name or "").strip()
        if not safe_name:
            raise ValueError("category_name is required")
        now = _utc_now()
        with self._lock:
            self._ensure_scenario_category_state_locked(safe_id, safe_name)
            self._conn.execute(
                """
                UPDATE scenario_category_states
                SET catalog_group=?, sort_order=?, updated_at=?
                WHERE scenario_id=? AND category_name=?
                """,
                (str(pin_group or "").strip(), int(sort_order or 0), now, safe_id, safe_name),
            )
            if pin_group:
                self._conn.execute(
                    """
                    INSERT INTO scenario_pin_groups (scenario_id, group_name, sort_order, mode, description, updated_at)
                    VALUES (?, ?, 0, ?, '', ?)
                    ON CONFLICT(scenario_id, group_name) DO NOTHING
                    """,
                    (safe_id, str(pin_group), BUSINESS_GROUP_MODE_STANDARD, now),
                )
            self._conn.commit()
        self._notify_policy_backup("scenario-category-pin")

    def unpin_scenario_category(self, scenario_id: str, name: str) -> bool:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        safe_name = str(name or "").strip()
        if not safe_name:
            return False
        now = _utc_now()
        with self._lock:
            self._ensure_scenario_category_state_locked(safe_id, safe_name)
            cur = self._conn.execute(
                """
                UPDATE scenario_category_states
                SET catalog_group='', sort_order=0, updated_at=?
                WHERE scenario_id=? AND category_name=? AND catalog_group <> ''
                """,
                (now, safe_id, safe_name),
            )
            self._conn.commit()
            updated = int(cur.rowcount or 0) > 0
        if updated:
            self._notify_policy_backup("scenario-category-unpin")
        return updated

    def save_scenario_pinned_categories_bulk(self, scenario_id: str, items: list[dict[str, Any]]) -> None:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        now = _utc_now()
        with self._lock:
            for item in items:
                category_name = str(item.get("category_name") or "").strip()
                if not category_name:
                    continue
                self._ensure_scenario_category_state_locked(safe_id, category_name)
                self._conn.execute(
                    """
                    UPDATE scenario_category_states
                    SET sort_order=?, catalog_group=?, updated_at=?
                    WHERE scenario_id=? AND category_name=?
                    """,
                    (
                        int(item.get("sort_order", 0)),
                        str(item.get("pin_group", "")),
                        now,
                        safe_id,
                        category_name,
                    ),
                )
            self._conn.commit()
        self._notify_policy_backup("scenario-pins-bulk-save")

    def create_scenario_pin_group(
        self,
        scenario_id: str,
        group_name: str,
        mode: str = BUSINESS_GROUP_MODE_STANDARD,
        description: str = "",
    ) -> bool:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        now = _utc_now()
        normalized_mode = _normalize_business_group_mode(mode)
        normalized_description = str(description or "").strip()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO scenario_pin_groups (scenario_id, group_name, sort_order, mode, description, updated_at)
                VALUES (?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM scenario_pin_groups WHERE scenario_id=?), ?, ?, ?)
                ON CONFLICT(scenario_id, group_name) DO NOTHING
                """,
                (safe_id, group_name, safe_id, normalized_mode, normalized_description, now),
            )
            self._conn.commit()
            created = int(cur.rowcount or 0) > 0
        if created:
            self._notify_policy_backup("scenario-pin-group-create")
        return created

    def rename_scenario_pin_group(
        self,
        scenario_id: str,
        old_name: str,
        new_name: str,
        mode: str | None = None,
        description: str | None = None,
    ) -> bool:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        now = _utc_now()
        with self._lock:
            row = self._conn.execute(
                "SELECT sort_order, mode, description FROM scenario_pin_groups WHERE scenario_id=? AND group_name=?",
                (safe_id, old_name),
            ).fetchone()
            if not row:
                return False
            sort_order = int(row["sort_order"] or 0)
            current_mode = _normalize_business_group_mode(row["mode"])
            current_description = str(row["description"] or "")
            next_mode = current_mode if mode is None else _normalize_business_group_mode(mode)
            next_description = current_description if description is None else str(description or "").strip()
            self._conn.execute(
                """
                INSERT INTO scenario_pin_groups (scenario_id, group_name, sort_order, mode, description, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scenario_id, group_name) DO UPDATE SET
                    sort_order=excluded.sort_order,
                    mode=excluded.mode,
                    description=excluded.description,
                    updated_at=excluded.updated_at
                """,
                (safe_id, new_name, sort_order, next_mode, next_description, now),
            )
            self._conn.execute(
                """
                UPDATE scenario_category_states
                SET catalog_group=?, updated_at=?
                WHERE scenario_id=? AND catalog_group=?
                """,
                (new_name, now, safe_id, old_name),
            )
            if old_name != new_name:
                self._conn.execute(
                    "DELETE FROM scenario_pin_groups WHERE scenario_id=? AND group_name=?",
                    (safe_id, old_name),
                )
            self._conn.commit()
        self._notify_policy_backup("scenario-pin-group-rename")
        return True

    def delete_scenario_pin_group(self, scenario_id: str, group_name: str) -> bool:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        now = _utc_now()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM scenario_pin_groups WHERE scenario_id=? AND group_name=?",
                (safe_id, group_name),
            )
            if int(cur.rowcount or 0) == 0:
                return False
            self._conn.execute(
                """
                UPDATE scenario_category_states
                SET catalog_group='', sort_order=0, updated_at=?
                WHERE scenario_id=? AND catalog_group=?
                """,
                (now, safe_id, group_name),
            )
            self._conn.commit()
        self._notify_policy_backup("scenario-pin-group-delete")
        return True

    def save_scenario_pin_group_order(self, scenario_id: str, items: list[dict[str, Any]]) -> None:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        now = _utc_now()
        with self._lock:
            for item in items:
                self._conn.execute(
                    """
                    UPDATE scenario_pin_groups
                    SET sort_order=?, updated_at=?
                    WHERE scenario_id=? AND group_name=?
                    """,
                    (int(item.get("sort_order", 0)), now, safe_id, str(item["group_name"])),
                )
            self._conn.commit()
        self._notify_policy_backup("scenario-pin-group-order")

    def save_scenario_custom_rule(self, scenario_id: str, rule: CustomRule) -> None:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        target_contract_id = rule.resolved_target_contract_id()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO scenario_custom_rules (scenario_id, id, rule_type, value, target_contract_id, target_group, category_name, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scenario_id, id) DO UPDATE SET
                    rule_type=excluded.rule_type,
                    value=excluded.value,
                    target_contract_id=excluded.target_contract_id,
                    target_group=excluded.target_group,
                    category_name=excluded.category_name
                """,
                (
                    safe_id,
                    rule.id,
                    rule.rule_type,
                    rule.value,
                    target_contract_id,
                    rule.display_target_group(),
                    rule.category_name,
                    rule.created_at,
                ),
            )
            self._conn.commit()
        self._notify_policy_backup("scenario-custom-rule-save")

    def delete_scenario_custom_rule(self, scenario_id: str, rule_id: str) -> None:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        with self._lock:
            self._conn.execute(
                "DELETE FROM scenario_custom_rules WHERE scenario_id=? AND id=?",
                (safe_id, rule_id),
            )
            self._conn.commit()
        self._notify_policy_backup("scenario-custom-rule-delete")

    def set_scenario_process_rules(self, scenario_id: str, items: list[dict[str, Any]]) -> None:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        now = _utc_now()
        catalog_contracts: dict[str, set[str]] = {}
        for entry in self.list_scenario_service_catalog_entries(safe_id):
            group_name = str(entry.catalog_group or "").strip()
            contract_id = normalize_contract_id(entry.contract_id)
            if group_name and contract_id:
                catalog_contracts.setdefault(group_name, set()).add(contract_id)
        with self._lock:
            self._conn.execute("DELETE FROM scenario_process_rules WHERE scenario_id=?", (safe_id,))
            for index, item in enumerate(items):
                business_group = str(item.get("business_group") or item.get("contract_display_name") or "").strip()
                contract_id = normalize_contract_id(item.get("contract_id"))
                if not contract_id and business_group:
                    resolved = catalog_contracts.get(business_group, set())
                    if len(resolved) == 1:
                        contract_id = next(iter(resolved))
                self._conn.execute(
                    """
                    INSERT INTO scenario_process_rules (
                        scenario_id, id, contract_id, business_group, match_type, value, sort_order, enabled, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        safe_id,
                        str(item.get("id") or uuid4().hex),
                        contract_id,
                        business_group,
                        str(item.get("match_type") or "PROCESS-NAME"),
                        str(item.get("value") or ""),
                        int(item.get("sort_order", index)),
                        1 if bool(item.get("enabled", True)) else 0,
                        now,
                    ),
                )
            self._conn.commit()

    def set_scenario_external_proxy_programs(self, scenario_id: str, items: list[dict[str, Any]]) -> None:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        now = _utc_now()
        catalog_contracts: dict[str, set[str]] = {}
        for entry in self.list_scenario_service_catalog_entries(safe_id):
            group_name = str(entry.catalog_group or "").strip()
            contract_id = normalize_contract_id(entry.contract_id)
            if group_name and contract_id:
                catalog_contracts.setdefault(group_name, set()).add(contract_id)
        with self._lock:
            self._conn.execute(
                "DELETE FROM scenario_external_proxy_programs WHERE scenario_id=?",
                (safe_id,),
            )
            for index, item in enumerate(items):
                business_group = str(item.get("business_group") or item.get("contract_display_name") or "").strip()
                contract_id = normalize_contract_id(item.get("contract_id"))
                if not contract_id and business_group:
                    resolved = catalog_contracts.get(business_group, set())
                    if len(resolved) == 1:
                        contract_id = next(iter(resolved))
                self._conn.execute(
                    """
                    INSERT INTO scenario_external_proxy_programs (
                        scenario_id, id, contract_id, business_group, program_path, args_json, local_port, name, sort_order, enabled, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        safe_id,
                        str(item.get("id") or uuid4().hex),
                        contract_id,
                        business_group,
                        str(item.get("program_path") or ""),
                        _json_dumps(item.get("args") or []),
                        int(item.get("local_port", 0) or 0),
                        str(item.get("name") or ""),
                        int(item.get("sort_order", index)),
                        1 if bool(item.get("enabled", True)) else 0,
                        now,
                    ),
                )
            self._conn.commit()

    def list_scenario_process_rules(self, scenario_id: str) -> list[dict[str, Any]]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, contract_id, business_group, match_type, value, sort_order, enabled
                FROM scenario_process_rules
                WHERE scenario_id=?
                ORDER BY sort_order, id
                """,
                (safe_id,),
            ).fetchall()
        return [
            {
                "id": str(row["id"] or ""),
                "contract_id": normalize_contract_id(row["contract_id"]),
                "business_group": str(row["business_group"] or ""),
                "match_type": str(row["match_type"] or "PROCESS-NAME"),
                "value": str(row["value"] or ""),
                "sort_order": int(row["sort_order"] or 0),
                "enabled": bool(int(row["enabled"] or 0)),
            }
            for row in rows
        ]

    def list_scenario_external_proxy_programs(self, scenario_id: str) -> list[dict[str, Any]]:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, contract_id, business_group, program_path, args_json, local_port, name, sort_order, enabled
                FROM scenario_external_proxy_programs
                WHERE scenario_id=?
                ORDER BY sort_order, id
                """,
                (safe_id,),
            ).fetchall()
        return [
            {
                "id": str(row["id"] or ""),
                "contract_id": normalize_contract_id(row["contract_id"]),
                "business_group": str(row["business_group"] or ""),
                "program_path": str(row["program_path"] or ""),
                "args": _json_loads(str(row["args_json"] or "[]")) or [],
                "local_port": int(row["local_port"] or 0),
                "name": str(row["name"] or ""),
                "sort_order": int(row["sort_order"] or 0),
                "enabled": bool(int(row["enabled"] or 0)),
            }
            for row in rows
        ]

    def load_review_cache(self, cache_key: str) -> str | None:
        safe_key = str(cache_key or "").strip()
        if not safe_key:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT annotations_json FROM review_cache WHERE cache_key=?",
                (safe_key,),
            ).fetchone()
            if row:
                return str(row["annotations_json"])
        return None

    def save_review_cache(
        self,
        cache_key: str,
        primary_profile_id: str,
        target_profile_id: str,
        annotations_json: str,
        primary_updated_at: str,
        target_updated_at: str,
    ) -> None:
        import uuid as _uuid

        row_id = str(_uuid.uuid4())
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO review_cache
                    (id, cache_key, primary_profile_id, target_profile_id,
                     annotations_json, created_at, primary_updated_at, target_updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    annotations_json=excluded.annotations_json,
                    created_at=excluded.created_at,
                    primary_updated_at=excluded.primary_updated_at,
                    target_updated_at=excluded.target_updated_at
                """,
                (
                    row_id,
                    str(cache_key),
                    str(primary_profile_id),
                    str(target_profile_id),
                    str(annotations_json),
                    now,
                    str(primary_updated_at),
                    str(target_updated_at),
                ),
            )
            self._conn.commit()

    def invalidate_review_cache(self, profile_id: str | None = None) -> None:
        with self._lock:
            if profile_id:
                safe_id = str(profile_id).strip()
                self._conn.execute(
                    "DELETE FROM review_cache WHERE primary_profile_id=? OR target_profile_id=?",
                    (safe_id, safe_id),
                )
            else:
                self._conn.execute("DELETE FROM review_cache")
            self._conn.commit()

    def list_pool_statuses(self) -> list[PoolStatus]:
        nodes: list[NodeRecord] = []
        gorelay_seen: set[str] = set()
        for account in self.list_gorelay_accounts():
            if not account.enabled:
                continue
            snapshot = self.load_gorelay_active_account_snapshot(account.id)
            if not snapshot:
                continue
            for device_nodes in snapshot.device_nodes.values():
                for node in device_nodes:
                    dedupe_key = node.dedupe_key()
                    if dedupe_key in gorelay_seen:
                        continue
                    gorelay_seen.add(dedupe_key)
                    nodes.append(node)
        for source in self.list_standard_sources():
            if not source.enabled:
                continue
            nodes.extend(self.load_standard_node_cache(source.id) or [])
        grouped: dict[str, list[NodeRecord]] = {
            POOL_DIRECT: [],
            POOL_HQ_PREMIUM: [],
            POOL_HQ_STANDARD: [],
            POOL_MEDIUM: [],
            POOL_BULK: [],
            POOL_CHAIN_HOME: [],
        }
        for node in nodes:
            contract_like = normalize_contract_id(node.quality_group)
            if contract_like == CONTRACT_HQ_PREMIUM:
                grouped[POOL_HQ_PREMIUM].append(node)
            elif contract_like == CONTRACT_HQ_STANDARD:
                grouped[POOL_HQ_STANDARD].append(node)
            elif contract_like == CONTRACT_MEDIUM:
                grouped[POOL_MEDIUM].append(node)
            elif contract_like == CONTRACT_BULK:
                grouped[POOL_BULK].append(node)
            elif contract_like == CONTRACT_CHAIN_HOME:
                grouped[POOL_CHAIN_HOME].append(node)
        output: list[PoolStatus] = []
        for sort_order, pool_id in enumerate(POOL_IDS):
            entries = grouped.get(pool_id, [])
            sources: dict[str, int] = {}
            for node in entries:
                source_key = str(node.source_id or "") or "unknown"
                sources[source_key] = sources.get(source_key, 0) + 1
            output.append(
                PoolStatus(
                    id=pool_id,
                    display_name=contract_display_name(pool_id),
                    node_count=len(entries),
                    renderable_node_count=len(entries),
                    last_refresh_at="",
                    sources=sources,
                    pseudo=pool_id == POOL_DIRECT,
                )
            )
        return output

    # legacy sources (compat)
    def list_gorelay_sources(self) -> list[GoRelaySource]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM gorelay_sources ORDER BY updated_at DESC"
            ).fetchall()
        output_by_id: dict[str, GoRelaySource] = {}
        for r in rows:
            output_by_id[str(r["id"])] = GoRelaySource(
                id=str(r["id"]),
                name=str(r["name"]),
                login_url=str(r["login_url"]),
                gorelay_username=str(r["gorelay_username"]),
                gorelay_password=self._dec(str(r["gorelay_password"])),
                proxy_username=str(r["proxy_username"] or ""),
                proxy_password=self._dec(str(r["proxy_password"] or "")),
                selectors_json=str(r["selectors_json"] or "{}"),
                enabled=bool(int(r["enabled"])),
                updated_at=str(r["updated_at"]),
            )
        # Always merge in `gorelay_accounts` so UI/API remains consistent even when only one of
        # the legacy/new tables has data (common during migrations / partial resets).
        for item in self.list_gorelay_accounts():
            if item.id in output_by_id:
                continue
            output_by_id[item.id] = GoRelaySource(
                id=item.id,
                name=item.name,
                login_url=item.login_url,
                gorelay_username=item.gorelay_username,
                gorelay_password=item.gorelay_password,
                proxy_username=item.proxy_username_default,
                proxy_password=item.proxy_password_default,
                selectors_json=item.selectors_json,
                enabled=item.enabled,
                updated_at=item.updated_at,
            )
        items = list(output_by_id.values())
        items.sort(key=lambda x: str(x.updated_at), reverse=True)
        return items

    def save_gorelay_source(self, source: GoRelaySource) -> None:
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO gorelay_sources (
                    id,name,login_url,gorelay_username,gorelay_password,
                    proxy_username,proxy_password,selectors_json,enabled,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    login_url=excluded.login_url,
                    gorelay_username=excluded.gorelay_username,
                    gorelay_password=excluded.gorelay_password,
                    proxy_username=excluded.proxy_username,
                    proxy_password=excluded.proxy_password,
                    selectors_json=excluded.selectors_json,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    source.id,
                    source.name,
                    source.login_url,
                    source.gorelay_username,
                    self._enc(source.gorelay_password),
                    source.proxy_username,
                    self._enc(source.proxy_password),
                    source.selectors_json or "{}",
                    1 if source.enabled else 0,
                    now,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO gorelay_accounts (
                    id,name,login_url,rules_url,gorelay_username,gorelay_password,
                    proxy_username_default,proxy_password_default,selectors_json,enabled,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    login_url=excluded.login_url,
                    gorelay_username=excluded.gorelay_username,
                    gorelay_password=excluded.gorelay_password,
                    proxy_username_default=excluded.proxy_username_default,
                    proxy_password_default=excluded.proxy_password_default,
                    selectors_json=excluded.selectors_json,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    source.id,
                    source.name,
                    source.login_url,
                    source.login_url,
                    source.gorelay_username,
                    self._enc(source.gorelay_password),
                    source.proxy_username,
                    self._enc(source.proxy_password),
                    source.selectors_json or "{}",
                    1 if source.enabled else 0,
                    now,
                ),
            )
            self._conn.commit()

    def delete_gorelay_source(self, source_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM gorelay_sources WHERE id=?", (source_id,))
            self._conn.execute("DELETE FROM gorelay_node_cache WHERE source_id=?", (source_id,))
            # The management UI lists GoRelay sources from either legacy `gorelay_sources`
            # or the newer `gorelay_accounts` fallback. Deleting must clear both; otherwise
            # accounts created via `/api/gorelay/*` would appear "undeletable" in `/api/sources/*`.
            self._conn.execute("DELETE FROM gorelay_accounts WHERE id=?", (source_id,))
            self._conn.execute("DELETE FROM gorelay_device_profiles WHERE account_id=?", (source_id,))
            self._conn.execute("DELETE FROM gorelay_device_subscriptions WHERE account_id=?", (source_id,))
            self._conn.execute("DELETE FROM gorelay_domain_bindings WHERE account_id=?", (source_id,))
            self._conn.execute(
                "DELETE FROM gorelay_domain_import_histories WHERE account_id=?", (source_id,)
            )
            self._conn.execute(
                "DELETE FROM gorelay_account_snapshots WHERE account_id=?", (source_id,)
            )
            self._conn.execute("DELETE FROM gorelay_active_snapshots WHERE account_id=?", (source_id,))
            self._conn.execute(
                "DELETE FROM gorelay_entry_multiplier_overrides WHERE account_id=?", (source_id,)
            )
            self._conn.commit()

    # gorelay accounts
    def list_gorelay_accounts(self) -> list[GoRelayAccount]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM gorelay_accounts ORDER BY updated_at DESC"
            ).fetchall()
        return [
            GoRelayAccount(
                id=str(r["id"]),
                name=str(r["name"]),
                login_url=str(r["login_url"]),
                rules_url=str(r["rules_url"] or ""),
                gorelay_username=str(r["gorelay_username"] or ""),
                gorelay_password=self._dec(str(r["gorelay_password"] or "")),
                proxy_username_default=str(r["proxy_username_default"] or ""),
                proxy_password_default=self._dec(str(r["proxy_password_default"] or "")),
                selectors_json=str(r["selectors_json"] or "{}"),
                mcp_url=str(r["mcp_url"] or ""),
                auth_header=self._dec(str(r["auth_header"] or "")),
                login_tool=str(r["login_tool"] or "auth_login"),
                nodes_tool=str(r["nodes_tool"] or "list_nodes"),
                login_args_json=str(
                    r["login_args_json"] or '{"username":"{username}","password":"{password}"}'
                ),
                nodes_args_json=str(r["nodes_args_json"] or "{}"),
                enabled=bool(int(r["enabled"])),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def get_gorelay_account(self, account_id: str) -> GoRelayAccount | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM gorelay_accounts WHERE id=? LIMIT 1",
                (account_id,),
            ).fetchone()
        if not row:
            return None
        return GoRelayAccount(
            id=str(row["id"]),
            name=str(row["name"]),
            login_url=str(row["login_url"]),
            rules_url=str(row["rules_url"] or ""),
            gorelay_username=str(row["gorelay_username"] or ""),
            gorelay_password=self._dec(str(row["gorelay_password"] or "")),
            proxy_username_default=str(row["proxy_username_default"] or ""),
            proxy_password_default=self._dec(str(row["proxy_password_default"] or "")),
            selectors_json=str(row["selectors_json"] or "{}"),
            mcp_url=str(row["mcp_url"] or ""),
            auth_header=self._dec(str(row["auth_header"] or "")),
            login_tool=str(row["login_tool"] or "auth_login"),
            nodes_tool=str(row["nodes_tool"] or "list_nodes"),
            login_args_json=str(
                row["login_args_json"] or '{"username":"{username}","password":"{password}"}'
            ),
            nodes_args_json=str(row["nodes_args_json"] or "{}"),
            enabled=bool(int(row["enabled"])),
            updated_at=str(row["updated_at"]),
        )

    def save_gorelay_account(self, account: GoRelayAccount) -> None:
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO gorelay_accounts (
                    id,name,login_url,rules_url,gorelay_username,gorelay_password,
                    proxy_username_default,proxy_password_default,selectors_json,
                    mcp_url,auth_header,login_tool,nodes_tool,login_args_json,nodes_args_json,
                    enabled,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    login_url=excluded.login_url,
                    rules_url=excluded.rules_url,
                    gorelay_username=excluded.gorelay_username,
                    gorelay_password=excluded.gorelay_password,
                    proxy_username_default=excluded.proxy_username_default,
                    proxy_password_default=excluded.proxy_password_default,
                    selectors_json=excluded.selectors_json,
                    mcp_url=excluded.mcp_url,
                    auth_header=excluded.auth_header,
                    login_tool=excluded.login_tool,
                    nodes_tool=excluded.nodes_tool,
                    login_args_json=excluded.login_args_json,
                    nodes_args_json=excluded.nodes_args_json,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    account.id,
                    account.name,
                    account.login_url,
                    account.rules_url or account.login_url,
                    account.gorelay_username,
                    self._enc(account.gorelay_password),
                    account.proxy_username_default,
                    self._enc(account.proxy_password_default),
                    account.selectors_json or "{}",
                    account.mcp_url,
                    self._enc(account.auth_header),
                    account.login_tool or "auth_login",
                    account.nodes_tool or "list_nodes",
                    account.login_args_json or '{"username":"{username}","password":"{password}"}',
                    account.nodes_args_json or "{}",
                    1 if account.enabled else 0,
                    now,
                ),
            )
            self._conn.commit()

    def delete_gorelay_account(self, account_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM gorelay_sources WHERE id=?", (account_id,))
            self._conn.execute("DELETE FROM gorelay_node_cache WHERE source_id=?", (account_id,))
            self._conn.execute("DELETE FROM gorelay_accounts WHERE id=?", (account_id,))
            self._conn.execute("DELETE FROM gorelay_device_profiles WHERE account_id=?", (account_id,))
            self._conn.execute("DELETE FROM gorelay_device_subscriptions WHERE account_id=?", (account_id,))
            self._conn.execute("DELETE FROM gorelay_domain_bindings WHERE account_id=?", (account_id,))
            self._conn.execute(
                "DELETE FROM gorelay_domain_import_histories WHERE account_id=?", (account_id,)
            )
            self._conn.execute(
                "DELETE FROM gorelay_account_snapshots WHERE account_id=?", (account_id,)
            )
            self._conn.execute("DELETE FROM gorelay_active_snapshots WHERE account_id=?", (account_id,))
            self._conn.execute(
                "DELETE FROM gorelay_entry_multiplier_overrides WHERE account_id=?", (account_id,)
            )
            self._conn.commit()

    def list_gorelay_device_profiles(self, account_id: str | None = None) -> list[GoRelayDeviceProfile]:
        with self._lock:
            if account_id:
                rows = self._conn.execute(
                    "SELECT * FROM gorelay_device_profiles WHERE account_id=? ORDER BY device_key",
                    (account_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM gorelay_device_profiles ORDER BY account_id, device_key"
                ).fetchall()
        return [
            GoRelayDeviceProfile(
                account_id=str(r["account_id"]),
                device_key=str(r["device_key"]),
                device_name=str(r["device_name"]),
                proxy_username_override=str(r["proxy_username_override"] or ""),
                proxy_password_override=self._dec(str(r["proxy_password_override"] or "")),
                strategy_preset=str(r["strategy_preset"] or "balanced"),
                enabled=bool(int(r["enabled"])),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def upsert_gorelay_device_profile(self, profile: GoRelayDeviceProfile) -> None:
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO gorelay_device_profiles (
                    account_id,device_key,device_name,proxy_username_override,
                    proxy_password_override,strategy_preset,enabled,updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id,device_key) DO UPDATE SET
                    device_name=excluded.device_name,
                    proxy_username_override=excluded.proxy_username_override,
                    proxy_password_override=excluded.proxy_password_override,
                    strategy_preset=excluded.strategy_preset,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    profile.account_id,
                    profile.device_key,
                    profile.device_name,
                    profile.proxy_username_override,
                    self._enc(profile.proxy_password_override),
                    profile.strategy_preset,
                    1 if profile.enabled else 0,
                    now,
                ),
            )
            self._conn.commit()

    def list_gorelay_device_subscriptions(
        self,
        account_id: str | None = None,
        include_disabled: bool = True,
    ) -> list[GoRelayDeviceSubscription]:
        sql = "SELECT * FROM gorelay_device_subscriptions"
        args: list[Any] = []
        clauses: list[str] = []
        if account_id:
            clauses.append("account_id=?")
            args.append(account_id)
        if not include_disabled:
            clauses.append("enabled=1")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY account_id, device_name"
        with self._lock:
            rows = self._conn.execute(sql, tuple(args)).fetchall()
        return [
            GoRelayDeviceSubscription(
                id=str(r["id"]),
                account_id=str(r["account_id"]),
                device_key=str(r["device_key"]),
                device_name=str(r["device_name"]),
                token=str(r["token"]),
                public_id=str(r["public_id"] or ""),
                enabled=bool(int(r["enabled"])),
                last_seen_at=str(r["last_seen_at"]) if r["last_seen_at"] else None,
                last_seen_ip=str(r["last_seen_ip"]) if r["last_seen_ip"] else None,
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def upsert_gorelay_device_subscription(self, item: GoRelayDeviceSubscription) -> None:
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO gorelay_device_subscriptions (
                    id,account_id,device_key,device_name,token,public_id,enabled,last_seen_at,last_seen_ip,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id,device_key) DO UPDATE SET
                    id=excluded.id,
                    device_name=excluded.device_name,
                    token=excluded.token,
                    public_id=excluded.public_id,
                    enabled=excluded.enabled,
                    last_seen_at=COALESCE(excluded.last_seen_at, gorelay_device_subscriptions.last_seen_at),
                    last_seen_ip=COALESCE(excluded.last_seen_ip, gorelay_device_subscriptions.last_seen_ip),
                    updated_at=excluded.updated_at
                """,
                (
                    item.id,
                    item.account_id,
                    item.device_key,
                    item.device_name,
                    item.token,
                    item.public_id or generate_public_subscription_id(),
                    1 if item.enabled else 0,
                    item.last_seen_at,
                    item.last_seen_ip,
                    now,
                ),
            )
            self._conn.commit()

    def get_gorelay_device_subscription_by_token(self, token: str) -> GoRelayDeviceSubscription | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM gorelay_device_subscriptions WHERE token=? LIMIT 1",
                (token,),
            ).fetchone()
        if not row:
            return None
        return GoRelayDeviceSubscription(
            id=str(row["id"]),
            account_id=str(row["account_id"]),
            device_key=str(row["device_key"]),
            device_name=str(row["device_name"]),
            token=str(row["token"]),
            public_id=str(row["public_id"] or ""),
            enabled=bool(int(row["enabled"])),
            last_seen_at=str(row["last_seen_at"]) if row["last_seen_at"] else None,
            last_seen_ip=str(row["last_seen_ip"]) if row["last_seen_ip"] else None,
            updated_at=str(row["updated_at"]),
        )

    def get_gorelay_device_subscription_by_public_id(self, public_id: str) -> GoRelayDeviceSubscription | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM gorelay_device_subscriptions WHERE public_id=? LIMIT 1",
                (public_id,),
            ).fetchone()
        if not row:
            return None
        return GoRelayDeviceSubscription(
            id=str(row["id"]),
            account_id=str(row["account_id"]),
            device_key=str(row["device_key"]),
            device_name=str(row["device_name"]),
            token=str(row["token"]),
            public_id=str(row["public_id"] or ""),
            enabled=bool(int(row["enabled"])),
            last_seen_at=str(row["last_seen_at"]) if row["last_seen_at"] else None,
            last_seen_ip=str(row["last_seen_ip"]) if row["last_seen_ip"] else None,
            updated_at=str(row["updated_at"]),
        )

    def disable_gorelay_device_subscription(self, subscription_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE gorelay_device_subscriptions SET enabled=0, updated_at=? WHERE id=?",
                (_utc_now(), subscription_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def touch_gorelay_device_subscription(self, token: str, seen_at: str, seen_ip: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE gorelay_device_subscriptions SET last_seen_at=?, last_seen_ip=?, updated_at=? WHERE token=?",
                (seen_at, seen_ip, _utc_now(), token),
            )
            self._conn.commit()

    def touch_gorelay_device_subscription_by_public_id(self, public_id: str, seen_at: str, seen_ip: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE gorelay_device_subscriptions SET last_seen_at=?, last_seen_ip=?, updated_at=? WHERE public_id=?",
                (seen_at, seen_ip, _utc_now(), public_id),
            )
            self._conn.commit()

    def list_gorelay_domain_bindings(self, account_id: str | None = None) -> list[GoRelayDomainBinding]:
        with self._lock:
            if account_id:
                rows = self._conn.execute(
                    "SELECT * FROM gorelay_domain_bindings WHERE account_id=? ORDER BY updated_at DESC",
                    (account_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM gorelay_domain_bindings ORDER BY updated_at DESC"
                ).fetchall()
        return [
            GoRelayDomainBinding(
                id=str(r["id"]),
                account_id=str(r["account_id"]),
                entry_name=str(r["entry_name"]),
                isp=str(r["isp"]),
                ip_version=str(r["ip_version"]),
                host_value=str(r["host_value"]),
                source=str(r["source"]),
                status=str(r["status"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def save_gorelay_domain_bindings(self, bindings: list[GoRelayDomainBinding]) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM gorelay_domain_bindings")
            for item in bindings:
                self._conn.execute(
                    """
                    INSERT INTO gorelay_domain_bindings (
                        id,account_id,entry_name,isp,ip_version,host_value,source,status,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        item.id,
                        item.account_id,
                        item.entry_name,
                        item.isp,
                        item.ip_version,
                        item.host_value,
                        item.source,
                        item.status,
                        item.updated_at,
                    ),
                )
            self._conn.commit()

    def list_gorelay_domain_import_histories(
        self,
        account_id: str | None = None,
        limit: int = 50,
    ) -> list[GoRelayDomainImportHistory]:
        capped = max(1, min(int(limit), 200))
        with self._lock:
            if account_id:
                rows = self._conn.execute(
                    "SELECT * FROM gorelay_domain_import_histories WHERE account_id=? ORDER BY created_at DESC LIMIT ?",
                    (account_id, capped),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM gorelay_domain_import_histories ORDER BY created_at DESC LIMIT ?",
                    (capped,),
                ).fetchall()
        return [
            GoRelayDomainImportHistory(
                id=str(r["id"]),
                account_id=str(r["account_id"]),
                raw_text=str(r["raw_text"] or ""),
                parsed_count=int(r["parsed_count"] or 0),
                changed_count=int(r["changed_count"] or 0),
                multiplier_hint_count=int(r["multiplier_hint_count"] or 0),
                applied_bindings=list(_json_loads(str(r["applied_bindings_json"])) or []),
                created_at=str(r["created_at"] or ""),
            )
            for r in rows
        ]

    def save_gorelay_domain_import_histories(self, items: list[GoRelayDomainImportHistory]) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM gorelay_domain_import_histories")
            for item in items:
                self._conn.execute(
                    """
                    INSERT INTO gorelay_domain_import_histories (
                        id,account_id,raw_text,parsed_count,changed_count,multiplier_hint_count,
                        applied_bindings_json,created_at
                    ) VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        item.id,
                        item.account_id,
                        item.raw_text,
                        int(item.parsed_count),
                        int(item.changed_count),
                        int(item.multiplier_hint_count),
                        _json_dumps(item.applied_bindings or []),
                        item.created_at,
                    ),
                )
            self._conn.commit()

    def delete_gorelay_domain_import_history(self, account_id: str, history_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM gorelay_domain_import_histories WHERE account_id=? AND id=?",
                (account_id, history_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def list_gorelay_entry_multiplier_overrides(
        self, account_id: str
    ) -> list[GoRelayEntryMultiplierOverride]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM gorelay_entry_multiplier_overrides WHERE account_id=? ORDER BY entry_key",
                (account_id,),
            ).fetchall()
        return [
            GoRelayEntryMultiplierOverride(
                account_id=str(r["account_id"]),
                entry_key=str(r["entry_key"]),
                multiplier=str(r["multiplier"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def replace_gorelay_entry_multiplier_overrides(
        self,
        account_id: str,
        overrides: dict[str, str],
    ) -> dict[str, int]:
        existing = {
            item.entry_key: item.multiplier
            for item in self.list_gorelay_entry_multiplier_overrides(account_id)
        }
        applied_count = 0
        unchanged_count = 0
        for key, value in overrides.items():
            if existing.get(key) == value:
                unchanged_count += 1
            else:
                applied_count += 1
        removed_count = len([key for key in existing if key not in overrides])

        with self._lock:
            self._conn.execute(
                "DELETE FROM gorelay_entry_multiplier_overrides WHERE account_id=?", (account_id,)
            )
            now = _utc_now()
            for entry_key, multiplier in overrides.items():
                self._conn.execute(
                    """
                    INSERT INTO gorelay_entry_multiplier_overrides (account_id,entry_key,multiplier,updated_at)
                    VALUES (?,?,?,?)
                    """,
                    (account_id, entry_key, multiplier, now),
                )
            self._conn.commit()

        return {
            "applied_count": applied_count,
            "removed_count": removed_count,
            "unchanged_count": unchanged_count,
        }

    def merge_gorelay_entry_multiplier_overrides(
        self,
        account_id: str,
        overrides: dict[str, str],
    ) -> int:
        if not overrides:
            return 0
        existing = {
            item.entry_key: item.multiplier
            for item in self.list_gorelay_entry_multiplier_overrides(account_id)
        }
        merged = dict(existing)
        changed = 0
        for key, value in overrides.items():
            if merged.get(key) != value:
                merged[key] = value
                changed += 1
        if changed <= 0:
            return 0
        self.replace_gorelay_entry_multiplier_overrides(account_id, merged)
        return changed

    def save_gorelay_account_snapshot(self, payload: GoRelayAccountSnapshotPayload) -> None:
        meta = payload.account
        raw = json.dumps(payload.to_dict(), ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO gorelay_account_snapshots (
                    account_id,snapshot_id,created_at,node_count,device_count,status,error,payload_json
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id,snapshot_id) DO UPDATE SET
                    created_at=excluded.created_at,
                    node_count=excluded.node_count,
                    device_count=excluded.device_count,
                    status=excluded.status,
                    error=excluded.error,
                    payload_json=excluded.payload_json
                """,
                (
                    meta.account_id,
                    meta.snapshot_id,
                    meta.created_at,
                    meta.node_count,
                    meta.device_count,
                    meta.status,
                    meta.error,
                    raw,
                ),
            )
            self._conn.commit()

    def load_gorelay_account_snapshot(
        self,
        account_id: str,
        snapshot_id: str,
    ) -> GoRelayAccountSnapshotPayload | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM gorelay_account_snapshots WHERE account_id=? AND snapshot_id=? LIMIT 1",
                (account_id, snapshot_id),
            ).fetchone()
        if not row:
            return None
        return GoRelayAccountSnapshotPayload.from_dict(json.loads(str(row["payload_json"])))

    def load_gorelay_latest_account_snapshot(self, account_id: str) -> GoRelayAccountSnapshotPayload | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT snapshot_id FROM gorelay_account_snapshots WHERE account_id=? ORDER BY created_at DESC LIMIT 1",
                (account_id,),
            ).fetchone()
        if not row:
            return None
        return self.load_gorelay_account_snapshot(account_id, str(row["snapshot_id"]))

    def load_gorelay_active_snapshot_id(self, account_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT snapshot_id FROM gorelay_active_snapshots WHERE account_id=? LIMIT 1",
                (account_id,),
            ).fetchone()
        if not row:
            return None
        text = str(row["snapshot_id"] or "").strip()
        return text or None

    def save_gorelay_active_snapshot_id(self, account_id: str, snapshot_id: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO gorelay_active_snapshots (account_id,snapshot_id)
                VALUES (?,?)
                ON CONFLICT(account_id) DO UPDATE SET snapshot_id=excluded.snapshot_id
                """,
                (account_id, snapshot_id),
            )
            self._conn.commit()

    def load_gorelay_active_account_snapshot(self, account_id: str) -> GoRelayAccountSnapshotPayload | None:
        active = self.load_gorelay_active_snapshot_id(account_id)
        if not active:
            return None
        return self.load_gorelay_account_snapshot(account_id, active)

    def list_gorelay_account_snapshots(self, account_id: str) -> list[GoRelayAccountSnapshot]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT account_id,snapshot_id,created_at,node_count,device_count,status,error
                FROM gorelay_account_snapshots
                WHERE account_id=?
                ORDER BY created_at DESC
                """,
                (account_id,),
            ).fetchall()
        return [
            GoRelayAccountSnapshot(
                account_id=str(r["account_id"]),
                snapshot_id=str(r["snapshot_id"]),
                created_at=str(r["created_at"]),
                node_count=int(r["node_count"]),
                device_count=int(r["device_count"]),
                status=str(r["status"]),
                error=str(r["error"]) if r["error"] not in (None, "") else None,
            )
            for r in rows
        ]

    def prune_gorelay_account_snapshots(self, account_id: str, keep: int) -> None:
        keep = max(int(keep), 1)
        active_id = self.load_gorelay_active_snapshot_id(account_id)
        snapshots = self.list_gorelay_account_snapshots(account_id)
        stale = snapshots[keep:]
        with self._lock:
            for item in stale:
                if active_id and item.snapshot_id == active_id:
                    continue
                self._conn.execute(
                    "DELETE FROM gorelay_account_snapshots WHERE account_id=? AND snapshot_id=?",
                    (account_id, item.snapshot_id),
                )
            self._conn.commit()

    # standard source
    @staticmethod
    def _standard_source_pull_reasons(raw: object) -> list[dict[str, str]]:
        try:
            value = json.loads(str(raw or "[]"))
        except ValueError:
            return []
        if not isinstance(value, list):
            return []
        return [
            {key: str(item.get(key) or "") for key in ("method", "code", "url", "message")}
            for item in value
            if isinstance(item, dict)
        ]

    @staticmethod
    def _row_to_standard_source(row: sqlite3.Row) -> StandardSource:
        return StandardSource(
            id=str(row["id"]),
            name=str(row["name"]),
            clash_url=str(row["clash_url"] or ""),
            shadowrocket_url=str(row["shadowrocket_url"] or ""),
            surge_url=str(row["surge_url"] or ""),
            login_url=str(row["login_url"] or ""),
            quality_group=str(row["quality_group"]),
            target_contract_id=normalize_contract_id(row["target_contract_id"]),
            source_mode=normalize_standard_source_mode(row["source_mode"]),
            ingest_kind=normalize_standard_source_ingest_kind(row["ingest_kind"]),
            manual_nodes_text=str(row["manual_nodes_text"] or ""),
            enabled=bool(int(row["enabled"])),
            last_pull_attempt_at=(str(row["last_pull_attempt_at"]) if row["last_pull_attempt_at"] else None),
            last_success_at=(str(row["last_success_at"]) if row["last_success_at"] else None),
            last_pull_ok=(
                bool(int(row["last_pull_ok"]))
                if row["last_pull_ok"] is not None
                else None
            ),
            last_pull_method=str(row["last_pull_method"] or ""),
            last_pull_node_count=int(row["last_pull_node_count"] or 0),
            last_pull_error=str(row["last_pull_error"] or ""),
            last_pull_reasons=SqliteRepo._standard_source_pull_reasons(row["last_pull_reasons"]),
            pull_network_mode=(
                str(row["pull_network_mode"] or DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE)
                if str(row["pull_network_mode"] or DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE)
                in STANDARD_SOURCE_PULL_NETWORK_MODES
                else DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE
            ),
            auto_pull_consecutive_failures=int(row["auto_pull_consecutive_failures"] or 0),
            auto_pull_expired=bool(int(row["auto_pull_expired"] or 0)),
            auto_pull_expired_at=(
                str(row["auto_pull_expired_at"]) if row["auto_pull_expired_at"] else None
            ),
            last_success_config_fingerprint=str(row["last_success_config_fingerprint"] or ""),
            updated_at=str(row["updated_at"]),
        )

    def list_standard_sources(self) -> list[StandardSource]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM standard_sources ORDER BY updated_at DESC"
            ).fetchall()
        return [self._row_to_standard_source(r) for r in rows]

    def get_standard_source(self, source_id: str) -> StandardSource | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM standard_sources WHERE id=? LIMIT 1",
                (source_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_standard_source(row)

    def save_standard_source(self, source: StandardSource) -> None:
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO standard_sources (
                    id,name,clash_url,shadowrocket_url,surge_url,login_url,quality_group,target_contract_id,source_mode,
                    ingest_kind,manual_nodes_text,enabled,pull_network_mode,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    clash_url=excluded.clash_url,
                    shadowrocket_url=excluded.shadowrocket_url,
                    surge_url=excluded.surge_url,
                    login_url=excluded.login_url,
                    quality_group=excluded.quality_group,
                    target_contract_id=excluded.target_contract_id,
                    source_mode=excluded.source_mode,
                    ingest_kind=excluded.ingest_kind,
                    manual_nodes_text=excluded.manual_nodes_text,
                    enabled=excluded.enabled,
                    pull_network_mode=excluded.pull_network_mode,
                    updated_at=excluded.updated_at
                """,
                (
                    source.id,
                    source.name,
                    source.clash_url,
                    source.shadowrocket_url,
                    source.surge_url,
                    source.login_url,
                    source.display_quality_group(),
                    source.resolved_target_contract_id(),
                    (
                        source.resolved_source_mode()
                        if source.resolved_source_mode() in STANDARD_SOURCE_MODES
                        else STANDARD_SOURCE_MODE_ROUTE_CONTRACT
                    ),
                    (
                        source.resolved_ingest_kind()
                        if source.resolved_ingest_kind() in STANDARD_SOURCE_INGEST_KINDS
                        else STANDARD_SOURCE_INGEST_REMOTE_SUBSCRIPTION
                    ),
                    str(source.manual_nodes_text or "").strip(),
                    1 if source.enabled else 0,
                    source.pull_network_mode
                    if source.pull_network_mode in STANDARD_SOURCE_PULL_NETWORK_MODES
                    else DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE,
                    now,
                ),
            )
            self._conn.commit()

    def save_standard_source_pull_status(
        self,
        source_id: str,
        *,
        attempt_at: str,
        ok: bool,
        method: str,
        node_count: int,
        error: str,
        success_config_fingerprint: str = "",
        trigger: str = "auto",
        reasons: list[dict[str, str]] | None = None,
    ) -> None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    last_success_at,
                    last_pull_node_count,
                    auto_pull_consecutive_failures,
                    auto_pull_expired,
                    auto_pull_expired_at,
                    last_success_config_fingerprint
                FROM standard_sources
                WHERE id=?
                LIMIT 1
                """,
                (source_id,),
            ).fetchone()
            if not row:
                return
            trigger_key = str(trigger or "").strip().lower() or "auto"
            if trigger_key not in {"auto", "manual", "save"}:
                trigger_key = "auto"

            success_at = attempt_at if ok else (str(row["last_success_at"]) if row["last_success_at"] else None)
            consecutive_failures = max(int(row["auto_pull_consecutive_failures"] or 0), 0)
            expired = bool(int(row["auto_pull_expired"] or 0))
            expired_at = str(row["auto_pull_expired_at"]) if row["auto_pull_expired_at"] else None
            last_success_config_fingerprint = str(row["last_success_config_fingerprint"] or "")

            if ok:
                consecutive_failures = 0
                expired = False
                expired_at = None
                final_node_count = max(int(node_count), 0)
                last_success_config_fingerprint = str(success_config_fingerprint or "").strip()
            elif trigger_key == "auto":
                consecutive_failures += 1
                if consecutive_failures >= STANDARD_SOURCE_AUTO_PULL_FAILURE_EXPIRED_THRESHOLD:
                    if not expired:
                        expired_at = attempt_at
                    expired = True
                final_node_count = max(int(row["last_pull_node_count"] or 0), 0)
            else:
                final_node_count = max(int(row["last_pull_node_count"] or 0), 0)

            self._conn.execute(
                """
                UPDATE standard_sources
                SET
                    last_pull_attempt_at=?,
                    last_success_at=?,
                    last_pull_ok=?,
                    last_pull_method=?,
                    last_pull_node_count=?,
                    last_pull_error=?,
                    last_pull_reasons=?,
                    auto_pull_consecutive_failures=?,
                    auto_pull_expired=?,
                    auto_pull_expired_at=?,
                    last_success_config_fingerprint=?
                WHERE id=?
                """,
                (
                    attempt_at,
                    success_at,
                    1 if ok else 0,
                    method,
                    final_node_count,
                    "" if ok else str(error or ""),
                    "[]" if ok else json.dumps(list(reasons or []), ensure_ascii=False),
                    consecutive_failures,
                    1 if expired else 0,
                    expired_at,
                    last_success_config_fingerprint,
                    source_id,
                ),
            )
            self._conn.commit()

    def _standard_source_qr_dir(self, source_id: str) -> Path:
        return self.data_dir / "standard-source-qr" / str(source_id)

    def list_standard_source_qr_assets(self, source_id: str) -> dict[str, StandardSourceQrAsset]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT source_id, field, file_relpath, mime_type, detected_url, updated_at
                FROM standard_source_qr_assets
                WHERE source_id=?
                ORDER BY field
                """,
                (source_id,),
            ).fetchall()
        output: dict[str, StandardSourceQrAsset] = {}
        for row in rows:
            field = str(row["field"] or "").strip()
            if field not in STANDARD_SOURCE_QR_FIELDS:
                continue
            output[field] = StandardSourceQrAsset(
                source_id=str(row["source_id"]),
                field=field,
                file_relpath=str(row["file_relpath"] or ""),
                mime_type=str(row["mime_type"] or ""),
                detected_url=str(row["detected_url"] or ""),
                updated_at=str(row["updated_at"] or ""),
            )
        return output

    def get_standard_source_qr_asset(
        self, source_id: str, field: str
    ) -> StandardSourceQrAsset | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT source_id, field, file_relpath, mime_type, detected_url, updated_at
                FROM standard_source_qr_assets
                WHERE source_id=? AND field=?
                LIMIT 1
                """,
                (source_id, field),
            ).fetchone()
        if not row:
            return None
        return StandardSourceQrAsset(
            source_id=str(row["source_id"]),
            field=str(row["field"]),
            file_relpath=str(row["file_relpath"] or ""),
            mime_type=str(row["mime_type"] or ""),
            detected_url=str(row["detected_url"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )

    def save_standard_source_qr_asset(self, asset: StandardSourceQrAsset) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO standard_source_qr_assets (
                    source_id, field, file_relpath, mime_type, detected_url, updated_at
                ) VALUES (?,?,?,?,?,?)
                ON CONFLICT(source_id, field) DO UPDATE SET
                    file_relpath=excluded.file_relpath,
                    mime_type=excluded.mime_type,
                    detected_url=excluded.detected_url,
                    updated_at=excluded.updated_at
                """,
                (
                    asset.source_id,
                    asset.field,
                    asset.file_relpath,
                    asset.mime_type,
                    asset.detected_url,
                    asset.updated_at or _utc_now(),
                ),
            )
            self._conn.commit()

    def delete_standard_source_qr_asset(self, source_id: str, field: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM standard_source_qr_assets WHERE source_id=? AND field=?",
                (source_id, field),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def delete_standard_source(self, source_id: str) -> None:
        qr_dir = self._standard_source_qr_dir(source_id)
        with self._lock:
            self._conn.execute("DELETE FROM standard_sources WHERE id=?", (source_id,))
            self._conn.execute("DELETE FROM standard_node_cache WHERE source_id=?", (source_id,))
            self._conn.execute("DELETE FROM standard_source_qr_assets WHERE source_id=?", (source_id,))
            self._conn.execute(
                "DELETE FROM runtime_settings WHERE key=?",
                (standard_source_diagnostics_key(source_id),),
            )
            self._conn.commit()
        if qr_dir.exists():
            shutil.rmtree(qr_dir, ignore_errors=True)

    # rule catalog
    @staticmethod
    def _row_to_rule_category(row: sqlite3.Row) -> RuleCategory:
        system_directness = (
            str(row["system_directness"] or RULE_DIRECTNESS_PROXY)
            if "system_directness" in row.keys()
            else RULE_DIRECTNESS_PROXY
        )
        system_default_group = (
            str(row["system_default_group"] or "")
            if "system_default_group" in row.keys()
            else (RULE_DIRECTNESS_DIRECT if system_directness == RULE_DIRECTNESS_DIRECT else "")
        )
        system_default_locked = (
            bool(row["system_default_locked"])
            if "system_default_locked" in row.keys()
            else (system_default_group == RULE_DIRECTNESS_DIRECT)
        )
        return RuleCategory(
            name=str(row["name"]),
            assigned_group=str(row["assigned_group"] or ""),
            rule_count=int(row["rule_count"] or 0),
            rule_source=str(row["rule_source"] or ""),
            category_type=(
                str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO)
                if "category_type" in row.keys()
                and str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO) in RULE_CATEGORY_TYPES
                else RULE_CATEGORY_TYPE_AUTO
            ),
            updated_at=str(row["updated_at"]),
            locked=bool(row["locked"]) if "locked" in row.keys() else False,
            system_directness=system_directness,
            system_default_group=system_default_group,
            system_default_locked=system_default_locked,
            override_group=str(row["override_group"] or "") if "override_group" in row.keys() else "",
            override_active=bool(row["override_active"]) if "override_active" in row.keys() else False,
            directness_override=(
                str(row["directness_override"] or "")
                if "directness_override" in row.keys()
                else ""
            ),
            lock_source=str(row["lock_source"] or "") if "lock_source" in row.keys() else "",
        )

    def list_rule_categories(self, query: str = "") -> list[RuleCategory]:
        with self._lock:
            if query:
                rows = self._conn.execute(
                    "SELECT * FROM rule_categories WHERE name LIKE ? ORDER BY name",
                    (f"%{query}%",),
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM rule_categories ORDER BY name").fetchall()
        return [self._row_to_rule_category(r) for r in rows]

    def get_rule_category(self, name: str) -> RuleCategory | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM rule_categories WHERE name=?",
                (name,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_rule_category(row)

    def save_rule_categories(self, categories: list[RuleCategory]) -> None:
        now = _utc_now()
        valid_groups = {"", RULE_DIRECTNESS_DIRECT, *QUALITY_GROUPS}
        with self._lock:
            for cat in categories:
                system_directness = (
                    cat.system_directness
                    if cat.system_directness in RULE_DIRECTNESS_CHOICES
                    else RULE_DIRECTNESS_PROXY
                )
                category_type = (
                    cat.category_type
                    if cat.category_type in RULE_CATEGORY_TYPES
                    else RULE_CATEGORY_TYPE_AUTO
                )
                assigned_group = str(cat.assigned_group or "")
                if assigned_group not in valid_groups:
                    assigned_group = ""
                system_default_group = str(cat.system_default_group or "")
                if system_default_group not in valid_groups:
                    system_default_group = (
                        RULE_DIRECTNESS_DIRECT
                        if system_directness == RULE_DIRECTNESS_DIRECT
                        else ""
                    )
                system_default_locked = bool(cat.system_default_locked)
                if system_default_group == RULE_DIRECTNESS_DIRECT:
                    system_default_locked = True
                override_group = str(cat.override_group or "")
                if override_group not in valid_groups:
                    override_group = ""
                override_active = bool(cat.override_active)
                if override_active and not assigned_group:
                    assigned_group = override_group
                if category_type == RULE_CATEGORY_TYPE_AUTO and not override_active:
                    if assigned_group != system_default_group:
                        override_active = True
                        override_group = assigned_group
                    else:
                        assigned_group = system_default_group
                if category_type == RULE_CATEGORY_TYPE_MANUAL:
                    if not system_default_group:
                        system_default_group = assigned_group
                    system_default_locked = bool(cat.locked)
                    override_group = ""
                    override_active = False

                lock_source = cat.lock_source if cat.lock_source in {"", *RULE_LOCK_SOURCES} else ""
                locked = bool(cat.locked)
                if lock_source == RULE_LOCK_SOURCE_MANUAL:
                    locked = True
                if category_type == RULE_CATEGORY_TYPE_MANUAL:
                    lock_source = RULE_LOCK_SOURCE_MANUAL if locked else ""
                elif not override_active and system_default_locked and lock_source != RULE_LOCK_SOURCE_MANUAL:
                    lock_source = RULE_LOCK_SOURCE_SYSTEM
                    locked = True
                elif override_active and lock_source == RULE_LOCK_SOURCE_SYSTEM:
                    lock_source = ""
                    locked = False

                directness_override = (
                    cat.directness_override
                    if cat.directness_override in {"", *RULE_DIRECTNESS_CHOICES}
                    else ""
                )
                if category_type == RULE_CATEGORY_TYPE_AUTO:
                    if override_active:
                        if assigned_group == RULE_DIRECTNESS_DIRECT:
                            directness_override = RULE_DIRECTNESS_DIRECT
                        elif system_default_group == RULE_DIRECTNESS_DIRECT:
                            directness_override = RULE_DIRECTNESS_PROXY
                        elif directness_override == RULE_DIRECTNESS_DIRECT:
                            directness_override = RULE_DIRECTNESS_PROXY
                    else:
                        directness_override = ""

                self._conn.execute(
                    """
                    INSERT INTO rule_categories (
                        name,assigned_group,rule_count,rule_source,category_type,updated_at,locked,
                        system_directness,system_default_group,system_default_locked,
                        override_group,override_active,directness_override,lock_source
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(name) DO UPDATE SET
                        assigned_group=CASE
                            WHEN COALESCE(rule_categories.category_type,'auto')='manual'
                                THEN rule_categories.assigned_group
                            ELSE excluded.assigned_group
                        END,
                        rule_count=CASE
                            WHEN COALESCE(rule_categories.category_type,'auto')='manual'
                                THEN rule_categories.rule_count
                            ELSE excluded.rule_count
                        END,
                        rule_source=CASE
                            WHEN COALESCE(rule_categories.category_type,'auto')='manual'
                                THEN rule_categories.rule_source
                            ELSE excluded.rule_source
                        END,
                        category_type=CASE
                            WHEN COALESCE(rule_categories.category_type,'auto')='manual'
                                THEN 'manual'
                            ELSE excluded.category_type
                        END,
                        updated_at=excluded.updated_at,
                        system_directness=excluded.system_directness,
                        system_default_group=CASE
                            WHEN COALESCE(rule_categories.category_type,'auto')='manual'
                                THEN rule_categories.system_default_group
                            ELSE excluded.system_default_group
                        END,
                        system_default_locked=CASE
                            WHEN COALESCE(rule_categories.category_type,'auto')='manual'
                                THEN rule_categories.system_default_locked
                            ELSE excluded.system_default_locked
                        END,
                        override_group=CASE
                            WHEN COALESCE(rule_categories.category_type,'auto')='manual'
                                THEN COALESCE(rule_categories.override_group,'')
                            ELSE excluded.override_group
                        END,
                        override_active=CASE
                            WHEN COALESCE(rule_categories.category_type,'auto')='manual'
                                THEN COALESCE(rule_categories.override_active,0)
                            ELSE excluded.override_active
                        END,
                        directness_override=CASE
                            WHEN COALESCE(rule_categories.category_type,'auto')='manual'
                                THEN COALESCE(rule_categories.directness_override,'')
                            ELSE excluded.directness_override
                        END,
                        lock_source=CASE
                            WHEN COALESCE(rule_categories.category_type,'auto')='manual'
                                THEN COALESCE(rule_categories.lock_source,'')
                            WHEN COALESCE(rule_categories.lock_source,'')='manual' THEN 'manual'
                            ELSE excluded.lock_source
                        END,
                        locked=CASE
                            WHEN COALESCE(rule_categories.category_type,'auto')='manual'
                                THEN rule_categories.locked
                            WHEN COALESCE(rule_categories.lock_source,'')='manual' THEN 1
                            ELSE excluded.locked
                        END
                    """,
                    (
                        cat.name,
                        assigned_group,
                        int(cat.rule_count),
                        cat.rule_source,
                        category_type,
                        now,
                        1 if locked else 0,
                        system_directness,
                        system_default_group,
                        1 if system_default_locked else 0,
                        override_group,
                        1 if override_active else 0,
                        directness_override,
                        lock_source,
                    ),
                )
            self._conn.commit()
        self._backfill_service_catalog_entries(preserve_manual_contract=True)

    def create_manual_rule_category(
        self,
        name: str,
        assigned_group: str,
        *,
        locked: bool = False,
    ) -> RuleCategory | None:
        safe_name = str(name or "").strip()
        if not safe_name:
            return None
        normalized_group = str(assigned_group or "").strip()
        valid_groups = {"", RULE_DIRECTNESS_DIRECT, *QUALITY_GROUPS}
        if normalized_group not in valid_groups:
            normalized_group = ""
        now = _utc_now()
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM rule_categories WHERE name=?",
                (safe_name,),
            ).fetchone()
            if exists:
                return None
            self._conn.execute(
                """
                INSERT INTO rule_categories (
                    name,assigned_group,rule_count,rule_source,category_type,updated_at,locked,
                    system_directness,system_default_group,system_default_locked,
                    override_group,override_active,directness_override,lock_source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    safe_name,
                    normalized_group,
                    0,
                    "manual",
                    RULE_CATEGORY_TYPE_MANUAL,
                    now,
                    1 if locked else 0,
                    RULE_DIRECTNESS_DIRECT if normalized_group == RULE_DIRECTNESS_DIRECT else RULE_DIRECTNESS_PROXY,
                    normalized_group,
                    1 if locked else 0,
                    "",
                    0,
                    "",
                    RULE_LOCK_SOURCE_MANUAL if locked else "",
                ),
            )
            self._conn.commit()
        self._backfill_service_catalog_entries()
        created = self.get_rule_category(safe_name)
        if created:
            self._notify_policy_backup("manual-category-create")
        return created

    def rename_manual_rule_category(self, old_name: str, new_name: str) -> bool:
        old = str(old_name or "").strip()
        new = str(new_name or "").strip()
        if not old or not new or old == new:
            return False
        now = _utc_now()
        with self._lock:
            row = self._conn.execute(
                "SELECT category_type FROM rule_categories WHERE name=?",
                (old,),
            ).fetchone()
            if not row or str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO) != RULE_CATEGORY_TYPE_MANUAL:
                return False
            target = self._conn.execute(
                "SELECT 1 FROM rule_categories WHERE name=?",
                (new,),
            ).fetchone()
            if target:
                return False

            self._conn.execute(
                "UPDATE rule_categories SET name=?, updated_at=? WHERE name=? AND category_type=?",
                (new, now, old, RULE_CATEGORY_TYPE_MANUAL),
            )
            self._conn.execute(
                "UPDATE custom_rules SET category_name=? WHERE category_name=?",
                (new, old),
            )
            self._conn.execute(
                "UPDATE pinned_categories SET category_name=?, updated_at=? WHERE category_name=?",
                (new, now, old),
            )
            self._conn.execute(
                "UPDATE service_catalog_entries SET category_name=?, updated_at=? WHERE category_name=?",
                (new, now, old),
            )
            self._conn.execute(
                "UPDATE rule_category_directness_reviews SET category_name=? WHERE category_name=?",
                (new, old),
            )
            self._conn.execute(
                "UPDATE rule_category_cache SET name=? WHERE name=?",
                (new, old),
            )
            self._conn.execute(
                "UPDATE scenario_category_states SET category_name=?, updated_at=? WHERE scenario_id=? AND category_name=?",
                (new, now, _DEFAULT_SCENARIO_ID, old),
            )
            self._conn.execute(
                "UPDATE scenario_custom_rules SET category_name=? WHERE scenario_id=? AND category_name=?",
                (new, _DEFAULT_SCENARIO_ID, old),
            )
            self._conn.commit()
            self._notify_policy_backup("manual-category-rename")
            return True

    def delete_manual_rule_category(self, name: str) -> bool:
        safe_name = str(name or "").strip()
        if not safe_name:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT category_type FROM rule_categories WHERE name=?",
                (safe_name,),
            ).fetchone()
            if not row or str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO) != RULE_CATEGORY_TYPE_MANUAL:
                return False

            self._conn.execute(
                "DELETE FROM custom_rules WHERE category_name=?",
                (safe_name,),
            )
            self._conn.execute(
                "DELETE FROM pinned_categories WHERE category_name=?",
                (safe_name,),
            )
            self._conn.execute(
                "DELETE FROM rule_category_directness_reviews WHERE category_name=?",
                (safe_name,),
            )
            self._conn.execute(
                "DELETE FROM service_catalog_entries WHERE category_name=?",
                (safe_name,),
            )
            self._conn.execute(
                "DELETE FROM scenario_category_states WHERE scenario_id=? AND category_name=?",
                (_DEFAULT_SCENARIO_ID, safe_name),
            )
            self._conn.execute(
                "DELETE FROM scenario_custom_rules WHERE scenario_id=? AND category_name=?",
                (_DEFAULT_SCENARIO_ID, safe_name),
            )
            self._conn.execute(
                "DELETE FROM rule_category_cache WHERE name=?",
                (safe_name,),
            )
            cur = self._conn.execute(
                "DELETE FROM rule_categories WHERE name=? AND category_type=?",
                (safe_name, RULE_CATEGORY_TYPE_MANUAL),
            )
            self._conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            self._notify_policy_backup("manual-category-delete")
        return deleted

    def update_rule_category_group(self, name: str, group: str) -> bool:
        valid_groups = {"", RULE_DIRECTNESS_DIRECT, *QUALITY_GROUPS}
        normalized_group = str(group or "").strip()
        if normalized_group not in valid_groups:
            normalized_group = ""
        now = _utc_now()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE rule_categories SET assigned_group=?, updated_at=? WHERE name=?",
                (normalized_group, now, name),
            )
            self._conn.commit()
            updated = cur.rowcount > 0
        if updated:
            with self._lock:
                self._sync_service_catalog_entry_locked(
                    name,
                    preserve_manual_contract=False,
                    prefer_category_contract=True,
                )
                self._sync_default_scenario_category_state_locked(name)
                self._conn.commit()
        return updated

    def set_rule_category_override_group(self, name: str, group: str) -> bool:
        valid_groups = {"", RULE_DIRECTNESS_DIRECT, *QUALITY_GROUPS}
        normalized_group = str(group or "").strip()
        if normalized_group not in valid_groups:
            normalized_group = ""
        now = _utc_now()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT category_type,system_default_group,system_directness,locked
                FROM rule_categories
                WHERE name=?
                """,
                (name,),
            ).fetchone()
            if not row:
                return False

            category_type = str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO)
            if category_type == RULE_CATEGORY_TYPE_MANUAL:
                cur = self._conn.execute(
                    """
                    UPDATE rule_categories
                    SET assigned_group=?,
                        system_default_group=?,
                        system_default_locked=CASE WHEN locked=1 THEN 1 ELSE 0 END,
                        updated_at=?
                    WHERE name=?
                    """,
                    (normalized_group, normalized_group, now, name),
                )
                self._conn.commit()
                updated = cur.rowcount > 0
                if updated:
                    self._sync_service_catalog_entry_locked(
                        name,
                        preserve_manual_contract=False,
                        prefer_category_contract=True,
                    )
                    self._conn.commit()
                    self._notify_policy_backup("category-override")
                return updated

            system_default_group = str(row["system_default_group"] or "")
            if not system_default_group:
                system_default_group = (
                    RULE_DIRECTNESS_DIRECT
                    if str(row["system_directness"] or RULE_DIRECTNESS_PROXY) == RULE_DIRECTNESS_DIRECT
                    else ""
                )
            directness_override = ""
            if normalized_group == RULE_DIRECTNESS_DIRECT:
                directness_override = RULE_DIRECTNESS_DIRECT
            elif system_default_group == RULE_DIRECTNESS_DIRECT:
                directness_override = RULE_DIRECTNESS_PROXY

            cur = self._conn.execute(
                """
                UPDATE rule_categories
                SET assigned_group=?,
                    override_group=?,
                    override_active=1,
                    directness_override=?,
                    updated_at=?
                WHERE name=?
                """,
                (normalized_group, normalized_group, directness_override, now, name),
            )
            self._conn.commit()
            updated = cur.rowcount > 0
        if updated:
            with self._lock:
                self._sync_service_catalog_entry_locked(
                    name,
                    preserve_manual_contract=False,
                    prefer_category_contract=True,
                )
                self._sync_default_scenario_category_state_locked(name)
                self._conn.commit()
            self._notify_policy_backup("category-override")
        return updated

    def restore_rule_category_system_default(self, name: str) -> bool:
        now = _utc_now()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT category_type,system_default_group,system_default_locked,system_directness
                FROM rule_categories
                WHERE name=?
                """,
                (name,),
            ).fetchone()
            if not row:
                return False
            if str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO) != RULE_CATEGORY_TYPE_AUTO:
                return False

            system_default_group = str(row["system_default_group"] or "")
            if not system_default_group:
                system_default_group = (
                    RULE_DIRECTNESS_DIRECT
                    if str(row["system_directness"] or RULE_DIRECTNESS_PROXY) == RULE_DIRECTNESS_DIRECT
                    else ""
                )
            system_default_locked = bool(row["system_default_locked"])
            if system_default_group == RULE_DIRECTNESS_DIRECT:
                system_default_locked = True

            cur = self._conn.execute(
                """
                UPDATE rule_categories
                SET assigned_group=?,
                    locked=?,
                    lock_source=?,
                    override_group='',
                    override_active=0,
                    directness_override='',
                    updated_at=?
                WHERE name=? AND category_type=?
                """,
                (
                    system_default_group,
                    1 if system_default_locked else 0,
                    RULE_LOCK_SOURCE_SYSTEM if system_default_locked else "",
                    now,
                    name,
                    RULE_CATEGORY_TYPE_AUTO,
                ),
            )
            self._conn.commit()
            updated = cur.rowcount > 0
        if updated:
            with self._lock:
                self._sync_service_catalog_entry_locked(
                    name,
                    preserve_manual_contract=False,
                    prefer_category_contract=True,
                )
                self._sync_default_scenario_category_state_locked(name)
                self._conn.commit()
            self._notify_policy_backup("category-restore-system-default")
        return updated

    def update_rule_category_directness_override(self, name: str, override: str) -> bool:
        normalized = override if override in {"", *RULE_DIRECTNESS_CHOICES} else ""
        now = _utc_now()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT category_type,assigned_group,system_default_group,system_directness
                FROM rule_categories WHERE name=?
                """,
                (name,),
            ).fetchone()
            if not row:
                return False
            category_type = str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO)
            if category_type != RULE_CATEGORY_TYPE_AUTO:
                cur = self._conn.execute(
                    "UPDATE rule_categories SET directness_override=?, updated_at=? WHERE name=?",
                    (normalized, now, name),
                )
                self._conn.commit()
                updated = cur.rowcount > 0
                if updated:
                    self._sync_service_catalog_entry_locked(
                        name,
                        preserve_manual_contract=False,
                        prefer_category_contract=True,
                    )
                    self._conn.commit()
                return updated

            assigned_group = str(row["assigned_group"] or "")
            system_default_group = str(row["system_default_group"] or "")
            if not system_default_group:
                system_default_group = (
                    RULE_DIRECTNESS_DIRECT
                    if str(row["system_directness"] or RULE_DIRECTNESS_PROXY) == RULE_DIRECTNESS_DIRECT
                    else ""
                )
            if normalized == RULE_DIRECTNESS_DIRECT:
                assigned_group = RULE_DIRECTNESS_DIRECT
                override_group = RULE_DIRECTNESS_DIRECT
                override_active = 1
            elif normalized == RULE_DIRECTNESS_PROXY:
                if assigned_group == RULE_DIRECTNESS_DIRECT:
                    assigned_group = ""
                override_group = assigned_group
                override_active = 1
            else:
                assigned_group = system_default_group
                override_group = ""
                override_active = 0
            cur = self._conn.execute(
                """
                UPDATE rule_categories
                SET assigned_group=?,
                    override_group=?,
                    override_active=?,
                    directness_override=?,
                    updated_at=?
                WHERE name=?
                """,
                (assigned_group, override_group, override_active, normalized, now, name),
            )
            self._conn.commit()
            updated = cur.rowcount > 0
        if updated:
            with self._lock:
                self._sync_service_catalog_entry_locked(
                    name,
                    preserve_manual_contract=False,
                    prefer_category_contract=True,
                )
                self._sync_default_scenario_category_state_locked(name)
                self._conn.commit()
        return updated

    def apply_rule_category_directness_decision(
        self,
        name: str,
        decision: str,
        *,
        lock_after_apply: bool = False,
    ) -> bool:
        normalized = str(decision or "").strip().upper()
        if normalized not in RULE_DIRECTNESS_CHOICES:
            return False
        now = _utc_now()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT assigned_group, lock_source, category_type, system_default_group, system_directness
                FROM rule_categories WHERE name=?
                """,
                (name,),
            ).fetchone()
            if not row:
                return False

            category_type = str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO)
            if category_type != RULE_CATEGORY_TYPE_AUTO:
                return False
            assigned_group = str(row["assigned_group"] or "")
            lock_source = str(row["lock_source"] or "")
            system_default_group = str(row["system_default_group"] or "")
            if not system_default_group:
                system_default_group = (
                    RULE_DIRECTNESS_DIRECT
                    if str(row["system_directness"] or RULE_DIRECTNESS_PROXY) == RULE_DIRECTNESS_DIRECT
                    else ""
                )
            should_lock_manually = lock_after_apply or lock_source == RULE_LOCK_SOURCE_MANUAL
            next_locked = 1 if should_lock_manually else 0
            next_lock_source = RULE_LOCK_SOURCE_MANUAL if should_lock_manually else ""

            if normalized == RULE_DIRECTNESS_DIRECT:
                cur = self._conn.execute(
                    """
                    UPDATE rule_categories
                    SET assigned_group='DIRECT',
                        override_group='DIRECT',
                        override_active=1,
                        directness_override='DIRECT',
                        locked=?,
                        lock_source=?,
                        updated_at=?
                    WHERE name=?
                    """,
                    (next_locked, next_lock_source, now, name),
                )
            else:
                next_group = assigned_group
                if assigned_group == RULE_DIRECTNESS_DIRECT:
                    next_group = ""
                if not next_group and system_default_group and system_default_group != RULE_DIRECTNESS_DIRECT:
                    next_group = system_default_group
                cur = self._conn.execute(
                    """
                    UPDATE rule_categories
                    SET assigned_group=?,
                        override_group=?,
                        override_active=1,
                        directness_override='PROXY',
                        locked=?,
                        lock_source=?,
                        updated_at=?
                    WHERE name=?
                    """,
                    (next_group, next_group, next_locked, next_lock_source, now, name),
                )
            self._conn.commit()
            updated = cur.rowcount > 0
        if updated:
            with self._lock:
                self._sync_service_catalog_entry_locked(
                    name,
                    preserve_manual_contract=False,
                    prefer_category_contract=False,
                )
                self._sync_default_scenario_category_state_locked(name)
                self._conn.commit()
        return updated

    def apply_scenario_category_directness_decision(
        self,
        scenario_id: str,
        name: str,
        decision: str,
        *,
        lock_after_apply: bool = False,
    ) -> bool:
        safe_id = str(scenario_id or "").strip() or _DEFAULT_SCENARIO_ID
        if safe_id == _DEFAULT_SCENARIO_ID:
            return self.apply_rule_category_directness_decision(
                name,
                decision,
                lock_after_apply=lock_after_apply,
            )
        safe_name = str(name or "").strip()
        if not safe_name:
            return False
        normalized = str(decision or "").strip().upper()
        if normalized not in RULE_DIRECTNESS_CHOICES:
            return False
        now = _utc_now()
        with self._lock:
            self._ensure_scenario_category_state_locked(safe_id, safe_name)
            row = self._conn.execute(
                """
                SELECT assigned_group, lock_source, category_type, system_default_group, system_directness
                FROM scenario_category_states
                WHERE scenario_id=? AND category_name=?
                """,
                (safe_id, safe_name),
            ).fetchone()
            if not row:
                return False

            category_type = str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO)
            if category_type != RULE_CATEGORY_TYPE_AUTO:
                return False
            assigned_group = str(row["assigned_group"] or "")
            lock_source = str(row["lock_source"] or "")
            system_default_group = str(row["system_default_group"] or "")
            if not system_default_group:
                system_default_group = (
                    RULE_DIRECTNESS_DIRECT
                    if str(row["system_directness"] or RULE_DIRECTNESS_PROXY) == RULE_DIRECTNESS_DIRECT
                    else ""
                )
            should_lock_manually = lock_after_apply or lock_source == RULE_LOCK_SOURCE_MANUAL
            next_locked = 1 if should_lock_manually else 0
            next_lock_source = RULE_LOCK_SOURCE_MANUAL if should_lock_manually else ""

            if normalized == RULE_DIRECTNESS_DIRECT:
                next_group = RULE_DIRECTNESS_DIRECT
            else:
                next_group = assigned_group
                if assigned_group == RULE_DIRECTNESS_DIRECT:
                    next_group = ""
                if not next_group and system_default_group and system_default_group != RULE_DIRECTNESS_DIRECT:
                    next_group = system_default_group
            next_contract_id = normalize_contract_id(next_group)

            cur = self._conn.execute(
                """
                UPDATE scenario_category_states
                SET assigned_group=?,
                    contract_id=?,
                    override_group=?,
                    override_active=1,
                    directness_override=?,
                    locked=?,
                    lock_source=?,
                    updated_at=?
                WHERE scenario_id=? AND category_name=?
                """,
                (
                    next_group,
                    next_contract_id,
                    next_group,
                    normalized,
                    next_locked,
                    next_lock_source,
                    now,
                    safe_id,
                    safe_name,
                ),
            )
            self._conn.commit()
            updated = cur.rowcount > 0
        if updated:
            self._notify_policy_backup("scenario-directness-apply")
        return updated

    def bulk_assign_rule_categories(
        self, assignments: dict[str, str], *, skip_locked: bool = False,
    ) -> int:
        now = _utc_now()
        updated = 0
        valid_groups = {"", RULE_DIRECTNESS_DIRECT, *QUALITY_GROUPS}
        with self._lock:
            for name, group in assignments.items():
                row = self._conn.execute(
                    """
                    SELECT category_type,locked,system_default_group,system_directness
                    FROM rule_categories
                    WHERE name=?
                    """,
                    (name,),
                ).fetchone()
                if not row:
                    continue
                if skip_locked and bool(row["locked"]):
                    continue

                normalized_group = str(group or "").strip()
                if normalized_group not in valid_groups:
                    normalized_group = ""
                category_type = str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO)
                if category_type == RULE_CATEGORY_TYPE_MANUAL:
                    cur = self._conn.execute(
                        """
                        UPDATE rule_categories
                        SET assigned_group=?,
                            system_default_group=?,
                            system_default_locked=CASE WHEN locked=1 THEN 1 ELSE 0 END,
                            updated_at=?
                        WHERE name=?
                        """,
                        (normalized_group, normalized_group, now, name),
                    )
                else:
                    system_default_group = str(row["system_default_group"] or "")
                    if not system_default_group:
                        system_default_group = (
                            RULE_DIRECTNESS_DIRECT
                            if str(row["system_directness"] or RULE_DIRECTNESS_PROXY) == RULE_DIRECTNESS_DIRECT
                            else ""
                        )
                    directness_override = ""
                    if normalized_group == RULE_DIRECTNESS_DIRECT:
                        directness_override = RULE_DIRECTNESS_DIRECT
                    elif system_default_group == RULE_DIRECTNESS_DIRECT:
                        directness_override = RULE_DIRECTNESS_PROXY
                    cur = self._conn.execute(
                        """
                        UPDATE rule_categories
                        SET assigned_group=?,
                            override_group=?,
                            override_active=1,
                            directness_override=?,
                            updated_at=?
                        WHERE name=?
                        """,
                        (normalized_group, normalized_group, directness_override, now, name),
                    )
                updated += cur.rowcount
            self._conn.commit()
        if updated:
            with self._lock:
                for name in assignments:
                    self._sync_service_catalog_entry_locked(
                        name,
                        preserve_manual_contract=False,
                        prefer_category_contract=True,
                    )
                    self._sync_default_scenario_category_state_locked(name)
                self._conn.commit()
            self._notify_policy_backup("category-bulk-assign")
        return updated

    def update_rule_category_locked(
        self,
        name: str,
        locked: bool,
        *,
        lock_source: str | None = None,
    ) -> bool:
        now = _utc_now()
        normalized_source = (
            str(lock_source).strip()
            if isinstance(lock_source, str)
            else (RULE_LOCK_SOURCE_MANUAL if locked else "")
        )
        if normalized_source and normalized_source not in RULE_LOCK_SOURCES:
            normalized_source = RULE_LOCK_SOURCE_MANUAL if locked else ""
        with self._lock:
            row = self._conn.execute(
                "SELECT category_type FROM rule_categories WHERE name=?",
                (name,),
            ).fetchone()
            if not row:
                return False
            category_type = str(row["category_type"] or RULE_CATEGORY_TYPE_AUTO)
            if category_type == RULE_CATEGORY_TYPE_MANUAL:
                cur = self._conn.execute(
                    """
                    UPDATE rule_categories
                    SET locked=?,
                        lock_source=?,
                        system_default_locked=?,
                        updated_at=?
                    WHERE name=?
                    """,
                    (
                        int(locked),
                        normalized_source if locked else "",
                        int(locked),
                        now,
                        name,
                    ),
                )
                self._conn.commit()
                updated = cur.rowcount > 0
                if updated:
                    self._notify_policy_backup("category-lock")
                return updated
            cur = self._conn.execute(
                "UPDATE rule_categories SET locked=?, lock_source=?, updated_at=? WHERE name=?",
                (int(locked), normalized_source if locked else "", now, name),
            )
            self._conn.commit()
            updated = cur.rowcount > 0
        if updated:
            self._notify_policy_backup("category-lock")
        return updated

    def list_rule_category_directness_reviews(
        self,
        *,
        status: str = RULE_DIRECTNESS_REVIEW_STATUS_PENDING,
    ) -> list[RuleCategoryDirectnessReview]:
        normalized_status = (
            status if status in {"all", *RULE_DIRECTNESS_REVIEW_STATUSES} else RULE_DIRECTNESS_REVIEW_STATUS_PENDING
        )
        with self._lock:
            if normalized_status == "all":
                rows = self._conn.execute(
                    "SELECT * FROM rule_category_directness_reviews ORDER BY created_at DESC, id DESC"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM rule_category_directness_reviews WHERE status=? "
                    "ORDER BY created_at DESC, id DESC",
                    (normalized_status,),
                ).fetchall()
        return [
            RuleCategoryDirectnessReview(
                id=str(row["id"]),
                category_name=str(row["category_name"]),
                proposed_decision=str(row["proposed_decision"] or ""),
                confidence=str(row["confidence"] or ""),
                reason=str(row["reason"] or ""),
                source=str(row["source"] or "llm-import"),
                status=str(row["status"] or RULE_DIRECTNESS_REVIEW_STATUS_PENDING),
                created_at=str(row["created_at"] or ""),
                decided_at=str(row["decided_at"] or ""),
            )
            for row in rows
        ]

    def get_rule_category_directness_reviews_by_ids(
        self,
        review_ids: list[str],
    ) -> list[RuleCategoryDirectnessReview]:
        ids = [str(item).strip() for item in review_ids if str(item).strip()]
        if not ids:
            return []
        placeholders = ",".join(["?"] * len(ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM rule_category_directness_reviews WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        item_map = {
            str(row["id"]): RuleCategoryDirectnessReview(
                id=str(row["id"]),
                category_name=str(row["category_name"]),
                proposed_decision=str(row["proposed_decision"] or ""),
                confidence=str(row["confidence"] or ""),
                reason=str(row["reason"] or ""),
                source=str(row["source"] or "llm-import"),
                status=str(row["status"] or RULE_DIRECTNESS_REVIEW_STATUS_PENDING),
                created_at=str(row["created_at"] or ""),
                decided_at=str(row["decided_at"] or ""),
            )
            for row in rows
        }
        return [item_map[item_id] for item_id in ids if item_id in item_map]

    def replace_pending_rule_category_directness_reviews(
        self,
        reviews: list[RuleCategoryDirectnessReview],
    ) -> int:
        if not reviews:
            return 0
        now = _utc_now()
        with self._lock:
            for review in reviews:
                self._conn.execute(
                    "DELETE FROM rule_category_directness_reviews "
                    "WHERE category_name=? AND status=?",
                    (review.category_name, RULE_DIRECTNESS_REVIEW_STATUS_PENDING),
                )
                self._conn.execute(
                    """
                    INSERT INTO rule_category_directness_reviews (
                        id, category_name, proposed_decision, confidence,
                        reason, source, status, created_at, decided_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        review.id,
                        review.category_name,
                        review.proposed_decision,
                        review.confidence,
                        review.reason,
                        review.source or "llm-import",
                        review.status or RULE_DIRECTNESS_REVIEW_STATUS_PENDING,
                        review.created_at or now,
                        review.decided_at or "",
                    ),
                )
            self._conn.commit()
        return len(reviews)

    def set_rule_category_directness_review_status(
        self,
        review_ids: list[str],
        *,
        status: str,
        decided_at: str = "",
    ) -> int:
        normalized_status = (
            status if status in RULE_DIRECTNESS_REVIEW_STATUSES else RULE_DIRECTNESS_REVIEW_STATUS_PENDING
        )
        ids = [str(item).strip() for item in review_ids if str(item).strip()]
        if not ids:
            return 0
        now = _utc_now()
        ts = decided_at or now
        placeholders = ",".join(["?"] * len(ids))
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE rule_category_directness_reviews "
                f"SET status=?, decided_at=? "
                f"WHERE id IN ({placeholders})",
                [normalized_status, ts, *ids],
            )
            self._conn.commit()
            return int(cur.rowcount or 0)

    def load_rule_cache_entry(self, name: str) -> dict[str, object] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT clash_rules_json, rule_count, source_sha, source_path, fetched_at "
                "FROM rule_category_cache WHERE name=?",
                (name,),
            ).fetchone()
        if not row:
            return None
        payload = _json_loads(str(row["clash_rules_json"]))
        rules = list(payload) if isinstance(payload, list) else []
        return {
            "name": name,
            "rules": rules,
            "rule_count": int(row["rule_count"] or len(rules)),
            "source_sha": str(row["source_sha"] or ""),
            "source_path": str(row["source_path"] or ""),
            "fetched_at": str(row["fetched_at"] or ""),
        }

    def load_rule_cache(self, name: str) -> list[str] | None:
        entry = self.load_rule_cache_entry(name)
        if not entry:
            return None
        rules = entry.get("rules")
        return list(rules) if isinstance(rules, list) else None

    def list_rule_cache_summaries(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, rule_count, source_sha, source_path, fetched_at "
                "FROM rule_category_cache ORDER BY name"
            ).fetchall()
        return [
            {
                "name": str(row["name"] or ""),
                "rule_count": int(row["rule_count"] or 0),
                "source_sha": str(row["source_sha"] or ""),
                "source_path": str(row["source_path"] or ""),
                "fetched_at": str(row["fetched_at"] or ""),
            }
            for row in rows
        ]

    def save_rule_cache(
        self,
        name: str,
        rules: list[str],
        *,
        source_sha: str = "",
        source_path: str = "",
    ) -> None:
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO rule_category_cache (name, clash_rules_json, rule_count, source_sha, source_path, fetched_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                    clash_rules_json=excluded.clash_rules_json,
                    rule_count=excluded.rule_count,
                    source_sha=excluded.source_sha,
                    source_path=excluded.source_path,
                    fetched_at=excluded.fetched_at
                """,
                (
                    name,
                    _json_dumps(rules),
                    len(rules),
                    str(source_sha or ""),
                    str(source_path or ""),
                    now,
                ),
            )
            self._conn.commit()

    def get_runtime_setting(self, key: str) -> object | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value_json FROM runtime_settings WHERE key=?",
                (key,),
            ).fetchone()
        if not row:
            return None
        try:
            return _json_loads(str(row["value_json"]))
        except Exception:
            return None

    def set_runtime_setting(self, key: str, value: object) -> None:
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO runtime_settings (key, value_json, updated_at)
                VALUES (?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json=excluded.value_json,
                    updated_at=excluded.updated_at
                """,
                (key, _json_dumps(value), now),
            )
            self._conn.commit()

    # -- durable runtime recovery state ---------------------------------

    def _get_runtime_setting_locked(self, key: str) -> object | None:
        row = self._conn.execute(
            "SELECT value_json FROM runtime_settings WHERE key=?",
            (key,),
        ).fetchone()
        if not row:
            return None
        try:
            return _json_loads(str(row["value_json"] or ""))
        except Exception:
            return None

    def _set_runtime_setting_locked(self, key: str, value: object, now: str | None = None) -> None:
        self._conn.execute(
            """
            INSERT INTO runtime_settings (key, value_json, updated_at)
            VALUES (?,?,?)
            ON CONFLICT(key) DO UPDATE SET
                value_json=excluded.value_json,
                updated_at=excluded.updated_at
            """,
            (key, _json_dumps(value), now or _utc_now()),
        )

    def record_policy_backup_dirty(self, reason: str = "") -> dict[str, object]:
        """Persist a policy mutation before waking the in-process backup worker.

        The callback used by policy-owned mutations is intentionally backed by
        this table rather than by an asyncio flag.  A process can therefore
        die after a mutation or during a Git push and still recover the exact
        generation on its next start.
        """
        safe_reason = str(reason or "").strip()[:200]
        now = _utc_now()
        with self._lock:
            # The generation is allocated from both runtime_settings and the
            # outbox table.  Serialize that read/insert/update sequence so two
            # processes cannot select the same generation after a restart.
            if self._conn.in_transaction:
                self._conn.commit()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                raw_state = self._get_runtime_setting_locked(_POLICY_BACKUP_STATE_KEY)
                state = dict(raw_state) if isinstance(raw_state, dict) else {}
                latest_generation = int(state.get("dirty_generation") or 0)
                row = self._conn.execute(
                    "SELECT MAX(generation) AS generation FROM policy_backup_outbox"
                ).fetchone()
                latest_generation = max(latest_generation, int(row["generation"] or 0) if row else 0)
                generation = latest_generation + 1
                self._conn.execute(
                    """
                    INSERT INTO policy_backup_outbox (
                        generation, reason, created_at, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (generation, safe_reason, now, _POLICY_BACKUP_OUTBOX_PENDING, now),
                )
                acked_generation = int(state.get("acked_generation") or 0)
                state.update(
                    {
                        "dirty_generation": generation,
                        "acked_generation": acked_generation,
                        "last_dirty_at": now,
                        "last_dirty_reason": safe_reason,
                        "reconciliation_required": bool(state.get("reconciliation_required", False)),
                    }
                )
                self._set_runtime_setting_locked(_POLICY_BACKUP_STATE_KEY, state, now)
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
            pending = self._conn.execute(
                "SELECT COUNT(*) AS count FROM policy_backup_outbox WHERE status=?",
                (_POLICY_BACKUP_OUTBOX_PENDING,),
            ).fetchone()
            state["pending_count"] = int(pending["count"] or 0) if pending else 0
            return state

    # Alias keeps the intent readable to callers that treat this as an outbox
    # append rather than a settings update.
    enqueue_policy_backup_dirty = record_policy_backup_dirty

    def get_policy_backup_state(self) -> dict[str, object]:
        with self._lock:
            raw_state = self._get_runtime_setting_locked(_POLICY_BACKUP_STATE_KEY)
            state = dict(raw_state) if isinstance(raw_state, dict) else {}
            latest_row = self._conn.execute(
                "SELECT MAX(generation) AS generation FROM policy_backup_outbox"
            ).fetchone()
            pending_row = self._conn.execute(
                """
                SELECT COUNT(*) AS count, MIN(created_at) AS oldest_at
                FROM policy_backup_outbox WHERE status=?
                """,
                (_POLICY_BACKUP_OUTBOX_PENDING,),
            ).fetchone()
            latest_generation = max(
                int(state.get("dirty_generation") or 0),
                int(latest_row["generation"] or 0) if latest_row else 0,
            )
            state.setdefault("acked_generation", 0)
            state["dirty_generation"] = latest_generation
            state["pending_count"] = int(pending_row["count"] or 0) if pending_row else 0
            state["oldest_pending_at"] = str(pending_row["oldest_at"] or "") if pending_row else ""
            state.setdefault("reconciliation_required", False)
            return state

    def list_policy_backup_outbox(self, *, limit: int = 100) -> list[dict[str, object]]:
        safe_limit = max(1, min(int(limit), 1000))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT generation, reason, created_at, status, sync_run_id,
                       commit_sha, remote_digest, updated_at
                FROM policy_backup_outbox
                ORDER BY generation
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def acknowledge_policy_backup_generation(
        self,
        generation: int,
        *,
        sync_run_id: str = "",
        commit_sha: str = "",
        remote_digest: str = "",
    ) -> dict[str, object]:
        safe_generation = max(0, int(generation or 0))
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                UPDATE policy_backup_outbox
                SET status=?, sync_run_id=?, commit_sha=?, remote_digest=?, updated_at=?
                WHERE generation<=? AND status=?
                """,
                (
                    _POLICY_BACKUP_OUTBOX_ACKED,
                    str(sync_run_id or "")[:100],
                    str(commit_sha or "")[:100],
                    str(remote_digest or "")[:128],
                    now,
                    safe_generation,
                    _POLICY_BACKUP_OUTBOX_PENDING,
                ),
            )
            state = self.get_policy_backup_state()
            previous_acked = int(state.get("acked_generation") or 0)
            state["acked_generation"] = max(previous_acked, safe_generation)
            if state["pending_count"] == 0:
                state["reconciliation_required"] = False
            state["last_ack_at"] = now
            state["last_ack_commit_sha"] = str(commit_sha or "")[:100]
            state["last_ack_remote_digest"] = str(remote_digest or "")[:128]
            self._set_runtime_setting_locked(_POLICY_BACKUP_STATE_KEY, state, now)
            self._conn.commit()
            return state

    def set_policy_backup_reconciliation(
        self,
        required: bool,
        *,
        error: str = "",
        remote_digest: str = "",
        remote_commit_sha: str = "",
        sync_run_id: str = "",
    ) -> dict[str, object]:
        now = _utc_now()
        with self._lock:
            raw_state = self._get_runtime_setting_locked(_POLICY_BACKUP_STATE_KEY)
            state = dict(raw_state) if isinstance(raw_state, dict) else {}
            state.update(
                {
                    "reconciliation_required": bool(required),
                    "reconciliation_error": str(error or "")[:500],
                    "last_remote_digest": str(remote_digest or "")[:128],
                    "last_remote_commit_sha": str(remote_commit_sha or "")[:100],
                    "last_remote_probe_at": now,
                    "last_reconcile_sync_run_id": str(sync_run_id or "")[:100],
                }
            )
            self._set_runtime_setting_locked(_POLICY_BACKUP_STATE_KEY, state, now)
            self._conn.commit()
            return self.get_policy_backup_state()

    def upsert_runtime_heartbeat(
        self,
        task_name: str,
        *,
        status: str = "running",
        required: bool = True,
        started_at: str | None = None,
        heartbeat_at: str | None = None,
        last_success_at: str | None = None,
        last_error: str = "",
        consecutive_failures: int = 0,
        failure_episode: int | None = None,
        details: dict[str, object] | None = None,
        busy_timeout_ms: int | None = None,
    ) -> dict[str, object]:
        safe_name = str(task_name or "").strip()
        if not safe_name:
            raise ValueError("task_name is required")
        now = heartbeat_at or _utc_now()
        with self._lock:
            previous_busy_timeout: int | None = None
            if busy_timeout_ms is not None:
                previous_busy_timeout = int(
                    self._conn.execute("PRAGMA busy_timeout").fetchone()[0] or 0
                )
                self._conn.execute(f"PRAGMA busy_timeout={max(0, int(busy_timeout_ms))}")
            try:
                existing = self._conn.execute(
                    "SELECT started_at, last_success_at, failure_episode "
                    "FROM runtime_task_heartbeats WHERE task_name=?",
                    (safe_name,),
                ).fetchone()
            except Exception:
                if previous_busy_timeout is not None:
                    self._conn.execute(f"PRAGMA busy_timeout={previous_busy_timeout}")
                raise
            payload = {
                "task_name": safe_name,
                "status": str(status or "running")[:40],
                "required": 1 if required else 0,
                "started_at": str(started_at or (existing["started_at"] if existing else now) or now),
                "heartbeat_at": now,
                "last_success_at": str(last_success_at or (existing["last_success_at"] if existing else "") or ""),
                "last_error": str(last_error or "")[:500],
                "consecutive_failures": max(0, int(consecutive_failures or 0)),
                "failure_episode": max(
                    0,
                    int(
                        failure_episode
                        if failure_episode is not None
                        else (existing["failure_episode"] if existing else 0)
                        or 0
                    ),
                ),
                "details_json": _json_dumps(details or {}),
                "updated_at": now,
            }
            try:
                self._conn.execute(
                    """
                    INSERT INTO runtime_task_heartbeats (
                        task_name, status, required, started_at, heartbeat_at,
                        last_success_at, last_error, consecutive_failures,
                        failure_episode, details_json, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(task_name) DO UPDATE SET
                        status=excluded.status,
                        required=excluded.required,
                        started_at=excluded.started_at,
                        heartbeat_at=excluded.heartbeat_at,
                        last_success_at=excluded.last_success_at,
                        last_error=excluded.last_error,
                        consecutive_failures=excluded.consecutive_failures,
                        failure_episode=excluded.failure_episode,
                        details_json=excluded.details_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        payload["task_name"],
                        payload["status"],
                        payload["required"],
                        payload["started_at"],
                        payload["heartbeat_at"],
                        payload["last_success_at"],
                        payload["last_error"],
                        payload["consecutive_failures"],
                        payload["failure_episode"],
                        payload["details_json"],
                        payload["updated_at"],
                    ),
                )
                self._conn.commit()
            finally:
                if previous_busy_timeout is not None:
                    self._conn.execute(f"PRAGMA busy_timeout={previous_busy_timeout}")
        payload.pop("details_json", None)
        payload["details"] = details or {}
        return payload

    def get_runtime_heartbeat(self, task_name: str) -> dict[str, object] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runtime_task_heartbeats WHERE task_name=?",
                (str(task_name or "").strip(),),
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        try:
            payload["details"] = _json_loads(str(payload.pop("details_json") or "{}")) or {}
        except Exception:
            payload["details"] = {}
            payload.pop("details_json", None)
        return payload

    def list_runtime_heartbeats(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runtime_task_heartbeats ORDER BY task_name"
            ).fetchall()
        output: list[dict[str, object]] = []
        for row in rows:
            payload = dict(row)
            try:
                payload["details"] = _json_loads(str(payload.pop("details_json") or "{}")) or {}
            except Exception:
                payload.pop("details_json", None)
                payload["details"] = {}
            output.append(payload)
        return output

    def create_runtime_alert_receipt(
        self,
        alert_key: str,
        *,
        task_name: str,
        message: str,
        payload: dict[str, object] | None = None,
        severity: str = "fatal",
    ) -> dict[str, object]:
        safe_key = str(alert_key or "").strip()
        if not safe_key:
            raise ValueError("alert_key is required")
        now = _utc_now()
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM runtime_alert_receipts WHERE alert_key=?",
                (safe_key,),
            ).fetchone()
            if existing:
                return dict(existing)
            alert_id = uuid4().hex
            self._conn.execute(
                """
                INSERT INTO runtime_alert_receipts (
                    alert_key, alert_id, task_name, severity, message,
                    payload_json, status, attempts, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    safe_key,
                    alert_id,
                    str(task_name or "")[:100],
                    str(severity or "fatal")[:30],
                    str(message or "")[:1000],
                    _json_dumps(payload or {}),
                    "pending",
                    0,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM runtime_alert_receipts WHERE alert_key=?",
                (safe_key,),
            ).fetchone()
        return dict(row) if row else {"alert_key": safe_key, "status": "pending"}

    def get_runtime_alert_receipt(self, alert_key: str) -> dict[str, object] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runtime_alert_receipts WHERE alert_key=?",
                (str(alert_key or "").strip(),),
            ).fetchone()
        return dict(row) if row else None

    def update_runtime_alert_receipt(
        self,
        alert_key: str,
        *,
        status: str,
        last_error: str = "",
        increment_attempt: bool = True,
        sent_at: str | None = None,
    ) -> dict[str, object] | None:
        now = _utc_now()
        with self._lock:
            row = self._conn.execute(
                "SELECT status, attempts FROM runtime_alert_receipts WHERE alert_key=?",
                (str(alert_key or "").strip(),),
            ).fetchone()
            if not row:
                return None
            # ``sent`` is a terminal receipt state.  A retry that was already
            # in flight when another sender confirmed delivery must not
            # downgrade it to failed/unknown or clear its sent timestamp.
            if str(row["status"] or "") == "sent":
                result = self._conn.execute(
                    "SELECT * FROM runtime_alert_receipts WHERE alert_key=?",
                    (str(alert_key or "").strip(),),
                ).fetchone()
                return dict(result) if result else None
            attempts = int(row["attempts"] or 0) + (1 if increment_attempt else 0)
            self._conn.execute(
                """
                UPDATE runtime_alert_receipts
                SET status=?, attempts=?, sent_at=?, last_error=?, updated_at=?
                WHERE alert_key=?
                """,
                (
                    str(status or "failed")[:20],
                    attempts,
                    str(sent_at or (now if status == "sent" else "")),
                    str(last_error or "")[:1000],
                    now,
                    str(alert_key or "").strip(),
                ),
            )
            self._conn.commit()
            result = self._conn.execute(
                "SELECT * FROM runtime_alert_receipts WHERE alert_key=?",
                (str(alert_key or "").strip(),),
            ).fetchone()
        return dict(result) if result else None

    def list_runtime_alert_receipts(self, *, status: str | None = None) -> list[dict[str, object]]:
        with self._lock:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM runtime_alert_receipts WHERE status=? ORDER BY updated_at DESC",
                    (str(status),),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM runtime_alert_receipts ORDER BY updated_at DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    # -- SQLite backup / restore ----------------------------------------

    @staticmethod
    def _fsync_file(path: Path) -> None:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _live_database_files_digest(self) -> str:
        """Hash the active SQLite main/WAL/SHM pair for crash-recovery CAS."""
        digest = hashlib.sha256()
        for suffix in ("", "-wal", "-shm"):
            path = Path(f"{self.db_path}{suffix}")
            digest.update(suffix.encode("utf-8"))
            if not path.is_file():
                digest.update(b"<missing>")
                continue
            digest.update(b"<present>")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _database_state_digest(connection: sqlite3.Connection) -> str:
        """Hash logical SQLite contents independently of page layout."""
        digest = hashlib.sha256()
        for line in connection.iterdump():
            digest.update(line.encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()

    def _database_state_digest_locked(self) -> str:
        return self._database_state_digest(self._conn)

    def _database_change_token_locked(self) -> str:
        version = int(self._cas_conn.execute("PRAGMA data_version").fetchone()[0] or 0)
        return f"{self._database_generation}:{self._connection_replacement_count}:{version}"

    def _policy_change_token_locked(self) -> str:
        """Return a CAS token for policy-owned state only.

        Runtime heartbeats and other operational writes share this database,
        but they do not change the policy backup generation. Policy restore
        therefore needs a narrower token so an unrelated heartbeat cannot
        make an otherwise safe staged restore retry forever.
        """
        row = self._conn.execute(
            "SELECT MAX(generation) AS generation FROM policy_backup_outbox"
        ).fetchone()
        generation = int(row["generation"] or 0) if row else 0
        return f"{self._database_generation}:policy:{generation}"

    def _change_token_locked(self, scope: str) -> str:
        normalized = str(scope or "database").strip().lower()
        if normalized == "database":
            return self._database_change_token_locked()
        if normalized == "policy":
            return self._policy_change_token_locked()
        raise ValueError("change token scope must be database or policy")

    def _merge_runtime_state_into_staged_database_locked(self, staged_path: Path) -> None:
        """Carry operational rows across a policy-only staged replacement.

        A policy restore intentionally ignores heartbeat churn for its CAS
        decision, but replacing the complete SQLite file must still retain
        heartbeats, alert receipts, and runtime settings written while the
        policy snapshot was being prepared.
        """
        tables = ("runtime_settings", "runtime_task_heartbeats", "runtime_alert_receipts")
        staged_connection = self._open_connection(staged_path)
        try:
            for table in tables:
                source_columns = [
                    str(row[1]) for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
                ]
                staged_columns = [
                    str(row[1]) for row in staged_connection.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                ]
                if source_columns != staged_columns:
                    raise RuntimeError(f"staged database schema mismatch for {table}")
                columns = ", ".join(source_columns)
                placeholders = ", ".join("?" for _ in source_columns)
                rows = self._conn.execute(f"SELECT {columns} FROM {table}").fetchall()
                staged_connection.execute(f"DELETE FROM {table}")
                if rows:
                    staged_connection.executemany(
                        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                        [tuple(row) for row in rows],
                    )
            staged_connection.commit()
        finally:
            staged_connection.close()

    @classmethod
    def inspect_database_file(cls, path: str | Path) -> dict[str, object]:
        database_path = Path(path).expanduser().resolve()
        if not database_path.is_file():
            raise FileNotFoundError(database_path)
        connection = sqlite3.connect(str(database_path), timeout=30)
        try:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0] or "")
            foreign_keys = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
            tables = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
        finally:
            connection.close()
        return {
            "path": str(database_path),
            "size_bytes": database_path.stat().st_size,
            "sha256": hashlib.sha256(database_path.read_bytes()).hexdigest(),
            "integrity_check": integrity,
            "foreign_key_errors": foreign_keys,
            "table_count": len(tables),
            "tables": tables,
            "ok": integrity.lower() == "ok" and not foreign_keys,
        }

    def database_integrity(self) -> dict[str, object]:
        """Run a bounded, read-only health check without holding ``_lock``.

        ``FULL`` WAL checkpoints wait for old readers up to SQLite's busy
        timeout and used to freeze an async readiness handler.  ``PASSIVE``
        never waits for readers; the more expensive file integrity scan is
        performed after releasing the repository lock so callers can keep
        heartbeats and management writes moving.
        """
        with self._lock:
            try:
                # A few legacy backfill helpers update derived rows after
                # their main commit.  Close that otherwise invisible write
                # transaction before asking SQLite to checkpoint/read the
                # file, so readiness never hangs behind its own lock.
                self._conn.commit()
                self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.DatabaseError:
                pass
        return self.inspect_database_file(self.db_path)

    def backup_database(
        self,
        destination: str | Path,
        *,
        change_token_scope: str = "database",
    ) -> dict[str, object]:
        scope = str(change_token_scope or "database").strip().lower()
        if scope not in {"database", "policy"}:
            raise ValueError("change token scope must be database or policy")
        destination_path = Path(destination).expanduser().resolve()
        if destination_path == self.db_path.resolve():
            raise ValueError("backup destination must differ from active database")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = destination_path.parent / f".{destination_path.name}.{uuid4().hex}.tmp"
        copied = False
        state_digest = ""
        change_token = ""
        try:
            with self._lock:
                try:
                    self._conn.commit()
                    # PASSIVE never waits for an old reader.  A FULL
                    # checkpoint here can block the event loop's synchronous
                    # callers for SQLite's 30-second busy timeout.
                    self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except sqlite3.DatabaseError:
                    pass
                change_token = self._change_token_locked(scope)
            # Keep the application lock out of the potentially long SQLite
            # backup.  WAL readers provide a consistent snapshot while normal
            # writers continue; the promotion CAS below rejects a stale
            # snapshot if a writer commits before it is installed.
            source = self._open_connection(self.db_path)
            target = self._open_connection(temporary_path)
            try:
                source.backup(target)
                target.commit()
                state_digest = self._database_state_digest(target)
            finally:
                source.close()
                target.close()
            copied = True
            metadata = self.inspect_database_file(temporary_path)
            if not bool(metadata["ok"]):
                raise RuntimeError("SQLite backup integrity check failed")
            self._fsync_file(temporary_path)
            os.replace(temporary_path, destination_path)
            self._fsync_directory(destination_path.parent)
            metadata = self.inspect_database_file(destination_path)
            metadata["state_digest"] = state_digest
            metadata["change_token"] = change_token
            metadata["change_token_scope"] = scope
            return metadata
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
            # Keep the local variable meaningful in traces without exposing
            # database contents or credentials.
            _ = copied

    def promote_staged_database(
        self,
        staged: str | Path,
        *,
        expected_change_token: str,
        change_token_scope: str = "database",
        fault_injection: str | None = None,
    ) -> dict[str, object]:
        """Promote a prepared database if the live file is unchanged.

        Policy restore prepares and validates its staged database away from
        the live repository.  This method is the short final CAS barrier:
        repository writers are excluded only while the current change token is
        checked and the already-prepared file is atomically renamed.  A
        concurrent write makes the operation return ``promoted=False`` so
        the caller can rebuild from the newer live state rather than lose it.
        """
        staged_path = Path(staged).expanduser().resolve()
        if staged_path == self.db_path.resolve():
            raise ValueError("staged database must differ from active database")
        expected = str(expected_change_token or "").strip().lower()
        if not expected:
            raise ValueError("expected live database change token is required")
        scope = str(change_token_scope or "database").strip().lower()
        if scope not in {"database", "policy"}:
            raise ValueError("change token scope must be database or policy")
        staged_metadata = self.inspect_database_file(staged_path)
        if not bool(staged_metadata["ok"]):
            raise ValueError("staged SQLite restore failed integrity checks")
        self._fsync_file(staged_path)
        self._restore_fault_injection(fault_injection, "after_stage")
        restore_id = uuid4().hex
        promoted = False
        try:
            with self._lock:
                try:
                    self._conn.commit()
                    # Do not wait for readers while taking the short CAS
                    # barrier; the staged file is already a complete backup.
                    self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except sqlite3.DatabaseError:
                    pass
                live_metadata = {
                    "path": str(self.db_path),
                    "change_token": self._change_token_locked(scope),
                    "change_token_scope": scope,
                }
                if str(live_metadata["change_token"]).lower() != expected:
                    return {
                        "promoted": False,
                        "reason": "live database changed during staged restore",
                        "live": live_metadata,
                        "staged": staged_metadata,
                    }
                if scope == "policy":
                    self._merge_runtime_state_into_staged_database_locked(staged_path)
                self._restore_fault_injection(fault_injection, "before_swap")

                old_connection = self._conn
                try:
                    # Record the complete live main/WAL/SHM identity only
                    # after the last non-blocking checkpoint.  If the
                    # process dies before os.replace, startup can compare
                    # this identity before selecting the staged file.
                    old_connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except sqlite3.DatabaseError:
                    pass
                live_files_sha256 = self._live_database_files_digest()
                self._write_promotion_journal(
                    staged_path,
                    restore_id,
                    live_files_sha256=live_files_sha256,
                )
                old_connection.close()
                self._conn = None
                cas_connection = self._cas_conn
                self._cas_conn = None
                cas_connection.close()
                self._connection_replacement_count += 1
                # Replace the complete staged database before removing the
                # old connection's sidecars.  If a process dies after this
                # atomic rename, the journal lets startup remove those old
                # sidecars before opening the new main file.  If it dies
                # before the rename, the journaled staged file is still there
                # for startup recovery, so a committed WAL is never orphaned.
                os.replace(staged_path, self.db_path)
                self._fsync_file(self.db_path)
                self._fsync_directory(self.db_path.parent)
                self._mark_promotion_installed()
                self._restore_fault_injection(fault_injection, "after_replace_before_sidecar_delete")
                self._remove_live_sidecars()
                self._restore_fault_injection(fault_injection, "after_sidecar_delete")
                self._restore_fault_injection(fault_injection, "after_swap")
                self._conn = self._open_connection(self.db_path)
                self._cas_conn = self._open_connection(self.db_path)
                self._clear_promotion_journal()
                promoted = True
        except BaseException:
            # A normal exception after closing the old connection must leave a
            # usable repository only after the journal proves which main file
            # is active and sidecar cleanup has succeeded.  SIGKILL bypasses
            # this block; startup runs the same proof before opening SQLite.
            with self._lock:
                state = self._promotion_state_after_exception(staged_path)
                if state == "unknown":
                    # There is no safe inode identity to reopen.  Keep the
                    # repository closed and force the caller/process to
                    # reconcile the durable filesystem state.
                    self._conn = None
                    self._cas_conn = None
                    raise
                self._reopen_after_promotion()
            raise
        finally:
            if staged_path.exists():
                staged_path.unlink()
        if promoted:
            result = self.inspect_database_file(self.db_path)
            result.update(
                {
                    "promoted": True,
                    "restore_id": restore_id,
                    "change_token_scope": scope,
                    "source": staged_metadata,
                }
            )
            return result

    @staticmethod
    def _restore_fault_injection(mode: str | None, stage: str) -> None:
        normalized = str(mode or "").strip().lower()
        aliases = {
            stage.lower(),
            {
                "after_stage": "after_staged",
                "before_swap": "before_replace",
                "after_replace_before_sidecar_delete": "after_replace",
                "after_sidecar_delete": "after_sidecars",
                "after_swap": "after_promote",
            }.get(stage.lower(), stage.lower()),
        }
        if stage.lower() == "after_sidecar_delete":
            aliases.update({"after_unlink", "after_sidecar_unlink", "after_live_sidecar_delete"})
        if normalized in aliases or any(normalized == f"raise:{item}" for item in aliases):
            raise RuntimeError(f"restore fault injection at {stage}")
        if any(
            normalized in {
                f"sigkill:{item}",
                f"sigkill_{item}",
                f"sigkill-{item}",
            }
            for item in aliases
        ):
            os.kill(os.getpid(), signal.SIGKILL)

    def restore_database(
        self,
        source: str | Path,
        *,
        fault_injection: str | None = None,
        preserve_previous: bool = True,
    ) -> dict[str, object]:
        """Validate and atomically replace the active database from a backup.

        The replacement is staged in the active data directory, validated,
        then installed with ``os.replace`` while no connection can observe a
        partially written file.  ``sigkill:<stage>`` fault modes are intended
        for a child-process drill; they never run by default.
        """
        source_path = Path(source).expanduser().resolve()
        if source_path == self.db_path.resolve():
            raise ValueError("restore source must differ from active database")
        source_metadata = self.inspect_database_file(source_path)
        if not bool(source_metadata["ok"]):
            raise ValueError("restore source failed SQLite integrity checks")

        restore_id = uuid4().hex
        staged_path = self.data_dir / f".subhub-restore-{restore_id}.db"
        previous_path: Path | None = None
        try:
            with self._lock:
                if preserve_previous:
                    previous_dir = self.root / "backups"
                    previous_path = previous_dir / f"subhub-before-restore-{restore_id}.db"
                    self.backup_database(previous_path)

                source_conn = self._open_connection(source_path)
                staged_conn = self._open_connection(staged_path)
                try:
                    source_conn.backup(staged_conn)
                    staged_conn.commit()
                finally:
                    source_conn.close()
                    staged_conn.close()
                staged_metadata = self.inspect_database_file(staged_path)
                if not bool(staged_metadata["ok"]):
                    raise ValueError("staged SQLite restore failed integrity checks")
                self._fsync_file(staged_path)
                self._restore_fault_injection(fault_injection, "after_stage")
                self._restore_fault_injection(fault_injection, "before_swap")

                old_connection = self._conn
                try:
                    # PASSIVE is deliberately before the durable journal and
                    # never FULL: the journal's live-pair digest must describe
                    # the exact files that remain recoverable if a process is
                    # killed before the atomic rename.
                    old_connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except sqlite3.DatabaseError:
                    pass
                live_files_sha256 = self._live_database_files_digest()
                self._write_promotion_journal(
                    staged_path,
                    restore_id,
                    live_files_sha256=live_files_sha256,
                )
                old_connection.close()
                self._conn = None
                cas_connection = self._cas_conn
                self._cas_conn = None
                cas_connection.close()
                self._connection_replacement_count += 1
                os.replace(staged_path, self.db_path)
                self._fsync_file(self.db_path)
                self._fsync_directory(self.db_path.parent)
                self._mark_promotion_installed()
                self._restore_fault_injection(fault_injection, "after_replace_before_sidecar_delete")
                self._remove_live_sidecars()
                self._restore_fault_injection(fault_injection, "after_sidecar_delete")
                self._restore_fault_injection(fault_injection, "after_swap")
                self._conn = self._open_connection(self.db_path)
                self._initialize_database()
                self._cas_conn = self._open_connection(self.db_path)
                self._clear_promotion_journal()
                result = self.inspect_database_file(self.db_path)
                result.update(
                    {
                        "source": source_metadata,
                        "previous_backup_path": str(previous_path) if previous_path else "",
                        "restore_id": restore_id,
                    }
                )
                return result
        except BaseException:
            # Reconnect only after the durable journal/hash proof and strict
            # sidecar cleanup.  If the replacement outcome is ambiguous, keep
            # both connections closed so an old WAL cannot be replayed over a
            # new main file.
            with self._lock:
                state = self._promotion_state_after_exception(staged_path)
                if state == "unknown":
                    self._conn = None
                    self._cas_conn = None
                    raise
                self._reopen_after_promotion()
            raise
        finally:
            if staged_path.exists():
                staged_path.unlink()

    def close(self) -> None:
        with self._lock:
            connection = self._conn
            self._conn = None
            cas_connection = self._cas_conn
            self._cas_conn = None
            if connection is not None:
                connection.close()
            if cas_connection is not None:
                cas_connection.close()

    def reset_policy_backup_owned_state(self, *, clear_contracts: bool = False) -> None:
        with self._lock:
            manual_names = [
                str(row["name"] or "")
                for row in self._conn.execute(
                    "SELECT name FROM rule_categories WHERE category_type=?",
                    (RULE_CATEGORY_TYPE_MANUAL,),
                ).fetchall()
            ]
            if manual_names:
                placeholders = ",".join("?" for _ in manual_names)
                self._conn.execute(
                    f"DELETE FROM rule_category_cache WHERE name IN ({placeholders})",
                    tuple(manual_names),
                )
                self._conn.execute(
                    f"DELETE FROM rule_category_directness_reviews WHERE category_name IN ({placeholders})",
                    tuple(manual_names),
                )
            self._conn.execute("DELETE FROM custom_rules")
            self._conn.execute("DELETE FROM pinned_categories")
            self._conn.execute("DELETE FROM pin_groups")
            self._conn.execute("DELETE FROM service_catalog_entries")
            self._conn.execute("DELETE FROM scenario_category_states")
            self._conn.execute("DELETE FROM scenario_pin_groups")
            self._conn.execute("DELETE FROM scenario_custom_rules")
            self._conn.execute("DELETE FROM scenario_route_contract_views")
            if clear_contracts:
                self._conn.execute("DELETE FROM route_contract_pool_bindings")
                self._conn.execute("DELETE FROM route_contracts")
            self._conn.execute(
                "DELETE FROM rule_categories WHERE category_type=?",
                (RULE_CATEGORY_TYPE_MANUAL,),
            )
            self._conn.execute(
                """
                UPDATE rule_categories
                SET assigned_group=CASE
                        WHEN system_directness=? THEN ?
                        ELSE COALESCE(system_default_group, '')
                    END,
                    locked=CASE
                        WHEN system_directness=? THEN 1
                        ELSE COALESCE(system_default_locked, 0)
                    END,
                    lock_source=CASE
                        WHEN system_directness=? THEN ?
                        WHEN COALESCE(system_default_locked, 0)=1 THEN ?
                        ELSE ''
                    END,
                    override_group='',
                    override_active=0,
                    directness_override='',
                    updated_at=?
                WHERE category_type=?
                """,
                (
                    RULE_DIRECTNESS_DIRECT,
                    RULE_DIRECTNESS_DIRECT,
                    RULE_DIRECTNESS_DIRECT,
                    RULE_DIRECTNESS_DIRECT,
                    RULE_LOCK_SOURCE_SYSTEM,
                    RULE_LOCK_SOURCE_SYSTEM,
                    _utc_now(),
                    RULE_CATEGORY_TYPE_AUTO,
                ),
            )
            self._conn.commit()
        if not clear_contracts:
            self._seed_scenario_route_contract_views()

    def load_cn_judge_cache(self) -> tuple[dict[str, object], str] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json, fetched_at FROM cn_judge_cache WHERE id=1",
            ).fetchone()
        if not row:
            return None
        payload = _json_loads(str(row["payload_json"]))
        if not isinstance(payload, dict):
            return None
        return payload, str(row["fetched_at"] or "")

    def save_cn_judge_cache(self, payload: dict[str, object], fetched_at: str | None = None) -> str:
        ts = fetched_at or _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO cn_judge_cache (id, payload_json, fetched_at)
                VALUES (1,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    fetched_at=excluded.fetched_at
                """,
                (_json_dumps(payload), ts),
            )
            self._conn.commit()
        return ts

    # custom rules
    def list_custom_rules(
        self,
        category_name: str | None = None,
        global_only: bool = False,
    ) -> list[CustomRule]:
        sql = "SELECT * FROM custom_rules"
        params: tuple[Any, ...] = ()
        if global_only:
            sql += " WHERE category_name=''"
        elif category_name is not None:
            sql += " WHERE category_name=?"
            params = (category_name,)
        sql += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            self._row_to_custom_rule(r)
            for r in rows
        ]

    def count_custom_rules_by_category(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT category_name, COUNT(*) AS count
                FROM custom_rules
                WHERE category_name <> ''
                GROUP BY category_name
                """
            ).fetchall()
        return {str(row["category_name"]): int(row["count"] or 0) for row in rows}

    def save_custom_rule(self, rule: CustomRule) -> None:
        target_contract_id = rule.resolved_target_contract_id()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO custom_rules (id,rule_type,value,target_contract_id,target_group,category_name,created_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    rule_type=excluded.rule_type,
                    value=excluded.value,
                    target_contract_id=excluded.target_contract_id,
                    target_group=excluded.target_group,
                    category_name=excluded.category_name
                """,
                (
                    rule.id,
                    rule.rule_type,
                    rule.value,
                    target_contract_id,
                    rule.display_target_group(),
                    rule.category_name,
                    rule.created_at,
                ),
            )
            self._conn.commit()
        self.save_scenario_custom_rule(_DEFAULT_SCENARIO_ID, rule)
        self._notify_policy_backup("custom-rule-save")

    def delete_custom_rule(self, rule_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM custom_rules WHERE id=?", (rule_id,))
            self._conn.commit()
        self.delete_scenario_custom_rule(_DEFAULT_SCENARIO_ID, rule_id)
        self._notify_policy_backup("custom-rule-delete")

    # global device subscriptions
    def list_device_subscriptions(self) -> list[DeviceSubscription]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM device_subscriptions ORDER BY device_name"
            ).fetchall()
        return [
            DeviceSubscription(
                id=str(r["id"]),
                device_key=str(r["device_key"]),
                device_name=str(r["device_name"]),
                token=str(r["token"]),
                public_id=str(r["public_id"] or ""),
                enabled=bool(int(r["enabled"])),
                last_seen_at=(str(r["last_seen_at"]) if r["last_seen_at"] else None),
                last_seen_ip=(str(r["last_seen_ip"]) if r["last_seen_ip"] else None),
            )
            for r in rows
        ]

    def get_device_subscription_by_token(self, token: str) -> DeviceSubscription | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM device_subscriptions WHERE token=?",
                (token,),
            ).fetchone()
        if not row:
            return None
        return DeviceSubscription(
            id=str(row["id"]),
            device_key=str(row["device_key"]),
            device_name=str(row["device_name"]),
            token=str(row["token"]),
            public_id=str(row["public_id"] or ""),
            enabled=bool(int(row["enabled"])),
            last_seen_at=(str(row["last_seen_at"]) if row["last_seen_at"] else None),
            last_seen_ip=(str(row["last_seen_ip"]) if row["last_seen_ip"] else None),
        )

    def get_device_subscription_by_public_id(self, public_id: str) -> DeviceSubscription | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM device_subscriptions WHERE public_id=?",
                (public_id,),
            ).fetchone()
        if not row:
            return None
        return DeviceSubscription(
            id=str(row["id"]),
            device_key=str(row["device_key"]),
            device_name=str(row["device_name"]),
            token=str(row["token"]),
            public_id=str(row["public_id"] or ""),
            enabled=bool(int(row["enabled"])),
            last_seen_at=(str(row["last_seen_at"]) if row["last_seen_at"] else None),
            last_seen_ip=(str(row["last_seen_ip"]) if row["last_seen_ip"] else None),
        )

    def get_device_subscription_by_key(self, device_key: str) -> DeviceSubscription | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM device_subscriptions WHERE device_key=?",
                (device_key,),
            ).fetchone()
        if not row:
            return None
        return DeviceSubscription(
            id=str(row["id"]),
            device_key=str(row["device_key"]),
            device_name=str(row["device_name"]),
            token=str(row["token"]),
            public_id=str(row["public_id"] or ""),
            enabled=bool(int(row["enabled"])),
            last_seen_at=(str(row["last_seen_at"]) if row["last_seen_at"] else None),
            last_seen_ip=(str(row["last_seen_ip"]) if row["last_seen_ip"] else None),
        )

    def save_device_subscription(self, sub: DeviceSubscription) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO device_subscriptions (id,device_key,device_name,token,public_id,enabled,last_seen_at,last_seen_ip)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(device_key) DO UPDATE SET
                    device_name=excluded.device_name,
                    token=excluded.token,
                    public_id=excluded.public_id,
                    enabled=excluded.enabled,
                    last_seen_at=COALESCE(excluded.last_seen_at, device_subscriptions.last_seen_at),
                    last_seen_ip=COALESCE(excluded.last_seen_ip, device_subscriptions.last_seen_ip)
                """,
                (
                    sub.id,
                    sub.device_key,
                    sub.device_name,
                    sub.token,
                    sub.public_id or generate_public_subscription_id(),
                    1 if sub.enabled else 0,
                    sub.last_seen_at,
                    sub.last_seen_ip,
                ),
            )
            self._conn.commit()

    def touch_device_subscription(self, token: str, seen_at: str, seen_ip: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE device_subscriptions SET last_seen_at=?, last_seen_ip=? WHERE token=?",
                (seen_at, seen_ip, token),
            )
            self._conn.commit()

    def touch_device_subscription_by_public_id(self, public_id: str, seen_at: str, seen_ip: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE device_subscriptions SET last_seen_at=?, last_seen_ip=? WHERE public_id=?",
                (seen_at, seen_ip, public_id),
            )
            self._conn.commit()

    # node cache
    def load_gorelay_node_cache(self, source_id: str, device_key: str) -> list[NodeRecord] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT nodes_json FROM gorelay_node_cache WHERE source_id=? AND device_key=?",
                (source_id, device_key),
            ).fetchone()
        if not row:
            return None
        payload = _json_loads(str(row["nodes_json"]))
        if not isinstance(payload, list):
            return None
        return [NodeRecord(**dict(item)) for item in payload if isinstance(item, dict)]

    def save_gorelay_node_cache(
        self,
        source_id: str,
        device_key: str,
        device_name: str,
        nodes: list[NodeRecord],
    ) -> None:
        now = _utc_now()
        serialized = [item.to_dict() for item in nodes]
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO gorelay_node_cache (source_id,device_key,nodes_json,device_name,fetched_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(source_id, device_key) DO UPDATE SET
                    nodes_json=excluded.nodes_json,
                    device_name=excluded.device_name,
                    fetched_at=excluded.fetched_at
                """,
                (source_id, device_key, _json_dumps(serialized), device_name, now),
            )
            self._conn.commit()

    def list_gorelay_cache_device_keys(self, source_id: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT device_key FROM gorelay_node_cache WHERE source_id=? ORDER BY device_key",
                (source_id,),
            ).fetchall()
        return [str(row["device_key"]) for row in rows]

    def load_all_gorelay_cached_nodes(self) -> list[NodeRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT nodes_json FROM gorelay_node_cache ORDER BY fetched_at DESC"
            ).fetchall()

        seen: set[str] = set()
        output: list[NodeRecord] = []
        for row in rows:
            try:
                payload = _json_loads(str(row["nodes_json"]))
            except Exception:
                continue
            if not isinstance(payload, list):
                continue
            for item in payload:
                if not isinstance(item, dict):
                    continue
                try:
                    node = NodeRecord(**dict(item))
                except Exception:
                    continue
                dedupe_key = node.dedupe_key()
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                output.append(node)
        return output

    def load_standard_node_cache(self, source_id: str) -> list[NodeRecord] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT nodes_json FROM standard_node_cache WHERE source_id=?",
                (source_id,),
            ).fetchone()
        if not row:
            return None
        payload = _json_loads(str(row["nodes_json"]))
        if not isinstance(payload, list):
            return None
        return [NodeRecord(**dict(item)) for item in payload if isinstance(item, dict)]

    def save_standard_node_cache(self, source_id: str, nodes: list[NodeRecord]) -> None:
        now = _utc_now()
        serialized = [item.to_dict() for item in nodes]
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO standard_node_cache (source_id,nodes_json,fetched_at)
                VALUES (?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    nodes_json=excluded.nodes_json,
                    fetched_at=excluded.fetched_at
                """,
                (source_id, _json_dumps(serialized), now),
            )
            self._conn.commit()

    def load_lazycat_profile_settings(self) -> dict[str, object] | None:
        profile = self.get_default_general_profile()
        if profile:
            return normalize_lazycat_profile_settings(profile.settings)
        with self._lock:
            row = self._conn.execute(
                "SELECT settings_json FROM lazycat_profile_settings WHERE id=1"
            ).fetchone()
            if not row:
                return None
            payload = _json_loads(str(row["settings_json"]))
            if not isinstance(payload, dict):
                return None
            return normalize_lazycat_profile_settings(payload)

    def save_lazycat_profile_settings(self, settings: dict[str, object]) -> None:  # DEPRECATED - use save_general_profile()
        normalized = normalize_lazycat_profile_settings(settings)
        self.save_general_profile(
            GeneralProfile(
                id=_DEFAULT_GENERAL_PROFILE_ID,
                name="LazyCat Default",
                settings=normalized,
                is_system_default=True,
            )
        )

    # -- pinned categories --

    def list_pinned_categories(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT category_name, pin_group, sort_order, updated_at "
                "FROM pinned_categories ORDER BY sort_order, category_name"
            ).fetchall()
        return [
            {
                "category_name": str(r["category_name"]),
                "pin_group": str(r["pin_group"]),
                "sort_order": int(r["sort_order"]),
                "updated_at": str(r["updated_at"]),
            }
            for r in rows
        ]

    def pin_category(self, name: str, pin_group: str, sort_order: int = 0) -> None:
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO pinned_categories (category_name, pin_group, sort_order, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(category_name) DO UPDATE SET
                    pin_group=excluded.pin_group,
                    sort_order=excluded.sort_order,
                    updated_at=excluded.updated_at
                """,
                (name, pin_group, sort_order, now),
            )
            # auto-create pin group if it doesn't exist
            if pin_group:
                self._conn.execute(
                    """
                    INSERT INTO pin_groups (group_name, sort_order, mode, description, updated_at)
                    VALUES (?, 0, ?, '', ?)
                    ON CONFLICT(group_name) DO NOTHING
                    """,
                    (pin_group, BUSINESS_GROUP_MODE_STANDARD, now),
                )
            self._sync_service_catalog_entry_locked(name, preserve_manual_contract=False)
            self._conn.commit()
        self.pin_scenario_category(_DEFAULT_SCENARIO_ID, name, pin_group, sort_order)

    def unpin_category(self, name: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM pinned_categories WHERE category_name=?", (name,)
            )
            if cur.rowcount > 0:
                self._sync_service_catalog_entry_locked(name, preserve_manual_contract=False)
            self._conn.commit()
            changed = cur.rowcount > 0
        if changed:
            self.unpin_scenario_category(_DEFAULT_SCENARIO_ID, name)
        return changed

    def save_pinned_categories_bulk(self, items: list[dict[str, Any]]) -> None:
        now = _utc_now()
        with self._lock:
            for item in items:
                self._conn.execute(
                    """
                    UPDATE pinned_categories SET sort_order=?, pin_group=?, updated_at=?
                    WHERE category_name=?
                    """,
                    (
                        int(item.get("sort_order", 0)),
                        str(item.get("pin_group", "")),
                        now,
                        str(item["category_name"]),
                    ),
                )
                self._sync_service_catalog_entry_locked(
                    str(item["category_name"]),
                    preserve_manual_contract=False,
                )
            self._conn.commit()
        self.save_scenario_pinned_categories_bulk(_DEFAULT_SCENARIO_ID, items)

    def list_pin_groups(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT group_name, sort_order, mode, description, updated_at "
                "FROM pin_groups ORDER BY sort_order, group_name"
            ).fetchall()
        return [
            {
                "group_name": str(r["group_name"]),
                "sort_order": int(r["sort_order"]),
                "mode": _normalize_business_group_mode(r["mode"]),
                "description": str(r["description"] or ""),
                "updated_at": str(r["updated_at"]),
            }
            for r in rows
        ]

    def create_pin_group(
        self,
        group_name: str,
        mode: str = BUSINESS_GROUP_MODE_STANDARD,
        description: str = "",
    ) -> bool:
        now = _utc_now()
        normalized_mode = _normalize_business_group_mode(mode)
        normalized_description = str(description or "").strip()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO pin_groups (group_name, sort_order, mode, description, updated_at)
                VALUES (?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM pin_groups), ?, ?, ?)
                ON CONFLICT(group_name) DO NOTHING
                """,
                (group_name, normalized_mode, normalized_description, now),
            )
            self._conn.commit()
            created = cur.rowcount > 0
        if created:
            self.create_scenario_pin_group(_DEFAULT_SCENARIO_ID, group_name, mode=mode, description=description)
        return created

    def rename_pin_group(
        self,
        old_name: str,
        new_name: str,
        mode: str | None = None,
        description: str | None = None,
    ) -> bool:
        now = _utc_now()
        with self._lock:
            row = self._conn.execute(
                "SELECT sort_order, mode, description FROM pin_groups WHERE group_name=?", (old_name,)
            ).fetchone()
            if not row:
                return False
            sort_order = int(row["sort_order"] or 0)
            current_mode = _normalize_business_group_mode(row["mode"])
            current_description = str(row["description"] or "")
            next_mode = current_mode if mode is None else _normalize_business_group_mode(mode)
            next_description = current_description if description is None else str(description or "").strip()
            self._conn.execute(
                """
                INSERT INTO pin_groups (group_name, sort_order, mode, description, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(group_name) DO UPDATE SET
                    sort_order=excluded.sort_order,
                    mode=excluded.mode,
                    description=excluded.description,
                    updated_at=excluded.updated_at
                """,
                (new_name, sort_order, next_mode, next_description, now),
            )
            self._conn.execute(
                "UPDATE pinned_categories SET pin_group=?, updated_at=? WHERE pin_group=?",
                (new_name, now, old_name),
            )
            self._conn.execute(
                "UPDATE service_catalog_entries SET catalog_group=?, updated_at=? WHERE catalog_group=?",
                (new_name, now, old_name),
            )
            if old_name != new_name:
                self._conn.execute("DELETE FROM pin_groups WHERE group_name=?", (old_name,))
            self._conn.commit()
        self._backfill_service_catalog_entries()
        self.rename_scenario_pin_group(
            _DEFAULT_SCENARIO_ID,
            old_name,
            new_name,
            mode=mode,
            description=description,
        )
        return True

    def delete_pin_group(self, group_name: str) -> bool:
        affected_categories: list[str] = []
        with self._lock:
            affected_categories = [
                str(row["category_name"] or "")
                for row in self._conn.execute(
                    "SELECT category_name FROM pinned_categories WHERE pin_group=?",
                    (group_name,),
                ).fetchall()
            ]
            cur = self._conn.execute(
                "DELETE FROM pin_groups WHERE group_name=?", (group_name,)
            )
            if cur.rowcount == 0:
                return False
            self._conn.execute(
                "DELETE FROM pinned_categories WHERE pin_group=?", (group_name,)
            )
            self._conn.commit()
        if affected_categories:
            self._backfill_service_catalog_entries()
        self.delete_scenario_pin_group(_DEFAULT_SCENARIO_ID, group_name)
        return True

    def save_pin_group_order(self, items: list[dict[str, Any]]) -> None:
        now = _utc_now()
        with self._lock:
            for item in items:
                self._conn.execute(
                    "UPDATE pin_groups SET sort_order=?, updated_at=? WHERE group_name=?",
                    (int(item.get("sort_order", 0)), now, str(item["group_name"])),
                )
            self._conn.commit()
        self.save_scenario_pin_group_order(_DEFAULT_SCENARIO_ID, items)

    def replace_all_pins(self, assignments: dict[str, str]) -> int:
        now = _utc_now()
        with self._lock:
            existing_modes = {
                str(row["group_name"]): {
                    "mode": _normalize_business_group_mode(row["mode"]),
                    "description": str(row["description"] or ""),
                }
                for row in self._conn.execute("SELECT group_name, mode, description FROM pin_groups").fetchall()
            }
            self._conn.execute("DELETE FROM pinned_categories")
            self._conn.execute("DELETE FROM pin_groups")
            groups_seen: set[str] = set()
            sort_idx = 0
            for cat_name, group_name in assignments.items():
                group_name = str(group_name or "").strip()
                if group_name and group_name not in groups_seen:
                    existing_meta = existing_modes.get(group_name, {})
                    self._conn.execute(
                        "INSERT INTO pin_groups (group_name, sort_order, mode, description, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (
                            group_name,
                            len(groups_seen),
                            existing_meta.get("mode", BUSINESS_GROUP_MODE_STANDARD),
                            existing_meta.get("description", ""),
                            now,
                        ),
                    )
                    groups_seen.add(group_name)
                self._conn.execute(
                    "INSERT INTO pinned_categories (category_name, pin_group, sort_order, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (str(cat_name), group_name, sort_idx, now),
                )
                sort_idx += 1
            self._conn.commit()
        self._backfill_service_catalog_entries()
        with self._lock:
            self._conn.execute(
                "UPDATE scenario_category_states SET catalog_group='', sort_order=0, updated_at=? WHERE scenario_id=?",
                (now, _DEFAULT_SCENARIO_ID),
            )
            self._conn.execute("DELETE FROM scenario_pin_groups WHERE scenario_id=?", (_DEFAULT_SCENARIO_ID,))
            self._conn.commit()
        for index, (cat_name, group_name) in enumerate(assignments.items()):
            if group_name:
                self.create_scenario_pin_group(_DEFAULT_SCENARIO_ID, group_name)
            self.pin_scenario_category(_DEFAULT_SCENARIO_ID, cat_name, group_name, index)
        return len(assignments)

    def replace_all_groupings(self, groups: list[dict[str, Any]]) -> int:
        now = _utc_now()
        with self._lock:
            self._conn.execute("DELETE FROM pinned_categories")
            self._conn.execute("DELETE FROM pin_groups")
            category_count = 0
            for group_sort, group in enumerate(groups):
                group_name = str(group.get("name") or "").strip()
                if not group_name:
                    continue
                mode = _normalize_business_group_mode(group.get("mode"))
                description = str(group.get("description") or "").strip()
                self._conn.execute(
                    """
                    INSERT INTO pin_groups (group_name, sort_order, mode, description, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (group_name, group_sort, mode, description, now),
                )
                for category_sort, category_name in enumerate(group.get("categories") or []):
                    safe_category = str(category_name or "").strip()
                    if not safe_category:
                        continue
                    self._conn.execute(
                        """
                        INSERT INTO pinned_categories (category_name, pin_group, sort_order, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (safe_category, group_name, category_sort, now),
                    )
                    category_count += 1
            self._conn.commit()
        self._backfill_service_catalog_entries()
        with self._lock:
            self._conn.execute(
                "UPDATE scenario_category_states SET catalog_group='', sort_order=0, updated_at=? WHERE scenario_id=?",
                (now, _DEFAULT_SCENARIO_ID),
            )
            self._conn.execute("DELETE FROM scenario_pin_groups WHERE scenario_id=?", (_DEFAULT_SCENARIO_ID,))
            self._conn.commit()
        for group_sort, group in enumerate(groups):
            group_name = str(group.get("name") or "").strip()
            if not group_name:
                continue
            self.create_scenario_pin_group(
                _DEFAULT_SCENARIO_ID,
                group_name,
                mode=_normalize_business_group_mode(group.get("mode")),
                description=str(group.get("description") or "").strip(),
            )
            self.save_scenario_pin_group_order(
                _DEFAULT_SCENARIO_ID,
                [{"group_name": group_name, "sort_order": group_sort}],
            )
            for category_sort, category_name in enumerate(group.get("categories") or []):
                safe_category = str(category_name or "").strip()
                if safe_category:
                    self.pin_scenario_category(_DEFAULT_SCENARIO_ID, safe_category, group_name, category_sort)
        return category_count
