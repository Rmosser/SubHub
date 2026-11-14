from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Callable, Any

from fastapi import HTTPException, Request

from app.config import Settings
from app.services.field_cipher import FieldCipher

_logger = logging.getLogger("app.tenant_registry")
_STORAGE_RECOVERY = "user storage unavailable; restore the original database and field_cipher.key, then retry"


class TenantRegistry:
    """Persist user storage boundaries and resolve public subscription owners.

    Only initialization registers users. Public requests never create a tenant,
    and legacy storage can only be assigned by an explicit operator setting.
    """

    def __init__(self, settings: Settings, factory: Callable[[Settings], Any], shared_services: Any):
        self.settings = settings
        self.factory = factory
        self.shared_services = shared_services
        self._services: dict[str, Any] = {}
        self._started: set[str] = set()
        self._lock = threading.RLock()
        self._running = False
        self._unavailable: set[str] = set()
        registry_dir = Path(settings.storage_root) / "data"
        registry_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(registry_dir / "tenant_registry.db", check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS tenants (user_id TEXT PRIMARY KEY, storage_kind TEXT NOT NULL)"
        )
        self._conn.commit()
        owner = str(settings.legacy_data_owner_id or "").strip()
        if settings.manage_api_require_login and owner:
            with self._lock:
                existing = self._conn.execute(
                    "SELECT user_id FROM tenants WHERE storage_kind='legacy'"
                ).fetchone()
                if existing and existing[0] != owner:
                    raise ValueError("LEGACY_DATA_OWNER_ID cannot reassign registered legacy data")
                current = self._conn.execute(
                    "SELECT storage_kind FROM tenants WHERE user_id=?", (owner,)
                ).fetchone()
                if current and current[0] != "legacy":
                    raise ValueError("LEGACY_DATA_OWNER_ID already has separate tenant storage")
                self._conn.execute("INSERT OR IGNORE INTO tenants VALUES (?, 'legacy')", (owner,))
                self._conn.commit()

    @staticmethod
    def tenant_key(user_id: str) -> str:
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    def _records(self) -> list[tuple[str, str]]:
        with self._lock:
            return self._conn.execute("SELECT user_id, storage_kind FROM tenants ORDER BY user_id").fetchall()

    def status(self, user_id: str) -> dict[str, object]:
        records = dict(self._records())
        local = not self.settings.manage_api_require_login
        return {
            "ok": True,
            "setup_required": not local and user_id not in records,
            "instance_initialized": local or bool(records),
            "legacy_claim_allowed": bool(user_id and user_id == self.settings.legacy_data_owner_id),
            "access_mode": "single-user" if local else "per-user",
            "storage_status": "unavailable" if user_id in self._unavailable else "ready" if local or user_id in records else "uninitialized",
            "recovery_hint": _STORAGE_RECOVERY if user_id in self._unavailable else "",
        }

    def _storage_root(self, user_id: str, storage_kind: str) -> Path:
        root = Path(self.settings.storage_root)
        return root if storage_kind == "legacy" else root / "tenants" / self.tenant_key(user_id)

    def _mark_unavailable(self, user_id: str) -> None:
        self._unavailable.add(user_id)
        _logger.error("tenant storage unavailable tenant=%s; restore database and original field_cipher.key", self.tenant_key(user_id))

    def _load(self, user_id: str, storage_kind: str):
        with self._lock:
            if user_id in self._services:
                return self._services[user_id]
            try:
                registered = self._conn.execute("SELECT 1 FROM tenants WHERE user_id=?", (user_id,)).fetchone()
                if registered and storage_kind != "legacy" and not (self._storage_root(user_id, storage_kind) / "data" / "subhub.db").is_file():
                    raise ValueError("registered tenant database is missing")
                if storage_kind == "legacy":
                    # Preserve old files, backup paths, and signed URLs.
                    services = self.shared_services or self.factory(replace(self.settings))
                else:
                    tenant_settings = replace(
                        self.settings,
                        storage_root=str(self._storage_root(user_id, storage_kind)),
                        policy_backup_subdir=str(Path(self.settings.policy_backup_subdir) / "tenants" / self.tenant_key(user_id)),
                    )
                    if not tenant_settings.url_signing_secret:
                        FieldCipher(tenant_settings.field_cipher_key_path)
                        tenant_settings.url_signing_secret = hashlib.sha256(
                            b"subhub subscription signing\0"
                            + tenant_settings.field_cipher_key_path.read_bytes().strip()
                        ).hexdigest()
                    services = self.factory(tenant_settings)
            except Exception as exc:
                self._mark_unavailable(user_id)
                raise HTTPException(status_code=503, detail=_STORAGE_RECOVERY) from exc
            self._unavailable.discard(user_id)
            self._services[user_id] = services
            return services

    def initialize(self, user_id: str):
        if not self.settings.manage_api_require_login:
            self.shared_services.hub_service._ensure_default_device_subscription()
            return self.shared_services
        user_id = str(user_id or "").strip()
        if not user_id:
            raise HTTPException(status_code=401, detail="lazycat login required")
        with self._lock:
            row = self._conn.execute("SELECT storage_kind FROM tenants WHERE user_id=?", (user_id,)).fetchone()
            kind = row[0] if row else "tenant"
            services = self._load(user_id, kind)
            services.hub_service._ensure_default_device_subscription()
            # The storage and encryption key exist before registration commits.
            self._conn.execute("INSERT OR IGNORE INTO tenants VALUES (?, ?)", (user_id, kind))
            self._conn.commit()
            return services

    def for_user(self, user_id: str):
        if not self.settings.manage_api_require_login:
            return self.shared_services
        user_id = str(user_id or "").strip()
        if not user_id:
            raise HTTPException(status_code=401, detail="lazycat login required")
        with self._lock:
            row = self._conn.execute("SELECT storage_kind FROM tenants WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=409, detail="setup required")
        return self._load(user_id, row[0])

    @staticmethod
    def _owns_subscription(services, subscription_id: str) -> bool:
        repo = services.repo
        return any((
            repo.get_device_subscription_by_token(subscription_id),
            repo.get_device_subscription_by_public_id(subscription_id),
            repo.get_gorelay_device_subscription_by_token(subscription_id),
            repo.get_gorelay_device_subscription_by_public_id(subscription_id),
        ))

    def for_subscription(self, subscription_id: str):
        if not subscription_id:
            return None
        if not self.settings.manage_api_require_login:
            return self.shared_services if self._owns_subscription(self.shared_services, subscription_id) else None
        matches: list[tuple[str, str]] = []
        for user_id, kind in self._records():
            db_path = self._storage_root(user_id, kind) / "data" / "subhub.db"
            try:
                # Locate identifiers without decrypting/loading unrelated users.
                with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                    found = False
                    for table in ("device_subscriptions", "gorelay_device_subscriptions"):
                        row = connection.execute(
                            f"SELECT 1 FROM {table} WHERE token=? OR public_id=? LIMIT 1",
                            (subscription_id, subscription_id),
                        ).fetchone()
                        found = found or row is not None
                    if found:
                        matches.append((user_id, kind))
            except sqlite3.Error:
                self._mark_unavailable(user_id)
        # Ambiguous imported identifiers must fail closed.
        return self._load(*matches[0]) if len(matches) == 1 else None

    async def ensure_started(self, services) -> None:
        if not self._running:
            return
        identity = str(services.repo.db_path)
        if identity in self._started:
            return
        self._started.add(identity)
        try:
            await services.gorelay_service.ensure_started()
            await services.hub_service.ensure_started()
            await services.policy_backup.ensure_started()
        except Exception:
            self._started.discard(identity)
            raise

    async def start(self) -> None:
        self._running = True
        if not self.settings.manage_api_require_login:
            await self.ensure_started(self.shared_services)
        else:
            for user_id, kind in self._records():
                try:
                    await self.ensure_started(self._load(user_id, kind))
                except Exception:
                    self._mark_unavailable(user_id)

    async def shutdown(self) -> None:
        self._running = False
        services_list = [self.shared_services, *self._services.values()]
        seen: set[int] = set()
        for services in services_list:
            if services is None or id(services) in seen:
                continue
            seen.add(id(services))
            await services.policy_backup.shutdown()
            await services.hub_service.shutdown()
            await services.gorelay_service.shutdown()
        self._started.clear()


def request_services(request: Request):
    state = getattr(request, "state", None)
    selected = getattr(state, "services", None)
    if selected is not None:
        return selected
    registry = getattr(request.app.state, "tenant_registry", None)
    if registry is None:
        return request.app.state.services
    if request.url.path.startswith(("/sub/", "/rules/")):
        subscription_id = str(request.path_params.get("token") or request.query_params.get("token") or "")
        selected = registry.for_subscription(subscription_id)
        if selected is None:
            raise HTTPException(status_code=403, detail="invalid or disabled subscription id")
        request.state.services = selected
        return selected
    return registry.for_user(str(getattr(state, "lazycat_user_id", "") or ""))
