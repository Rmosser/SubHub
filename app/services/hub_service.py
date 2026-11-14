from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from app.config import Settings
from app.models import (
    BUSINESS_GROUP_MODE_AD_BLOCK,
    BUSINESS_GROUP_MODE_STANDARD,
    CONTRACT_AD_BLOCK,
    CONTRACT_DIRECT,
    ROUTE_ACTION_REJECT,
    ROUTE_DIRECT_ACTION,
    ROUTE_REJECT_ACTION,
    DEVICE_STRATEGY_PRESET_BALANCED,
    DEVICE_STRATEGY_PRESETS,
    BusinessGroup,
    CollectedOutbound,
    contract_display_name,
    effective_contract_id,
    contract_legacy_group,
    normalize_contract_id,
    ExternalProxyProgramTemplate,
    HIGH_QUALITY_AIRPORT_THRESHOLD,
    DeviceSubscription,
    GeneralProfile,
    HubRuntime,
    MacOverlayTemplate,
    NodeRecord,
    OverlayStatus,
    PolicyIR,
    PolicyRuleEntry,
    ProcessRuleTemplate,
    QUALITY_BULK,
    QUALITY_CHAIN_HOME,
    QUALITY_HIGH_AIRPORT,
    QUALITY_HIGH_PREMIUM,
    QUALITY_HIGH_STANDARD,
    QUALITY_MEDIUM,
    QUALITY_GROUPS,
    QUALITY_REJECT,
    RenderWarning,
    RuleCategory,
    RouteContract,
    ServiceCatalogEntry,
    STANDARD_SOURCE_INGEST_MANUAL_NODES,
    STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT,
    normalize_route_action,
)
from app.services.device_grouper import build_device_key, extract_device_group
from app.services.error_diagnostics import error_detail
from app.services.gorelay_service import GorelayService
from app.services.node_naming import decorate_high_quality_node_name, extract_high_quality_airport_multiplier
from app.services.runtime_observability import (
    NullRuntimeTaskMonitor,
    RuntimeAlertService,
    RuntimeTaskMonitor,
)
from app.services.route_contract_views import (
    scenario_contract_display_name,
    scenario_default_contract_id,
    scenario_route_contracts,
)
from app.services.rule_catalog import RuleCatalog
from app.services.source_fetcher import SourceFetcher
from app.services.source_diagnostics import known_source_secrets, public_runtime, public_source_status, source_error_detail, summarize_pull_errors
from app.services.subscription_builder import build_policy_ir, merge_policy_rule_entries
from app.storage.base import Repo, standard_source_diagnostics_key

RUNTIME_KEY_STANDARD_SOURCE_AUTO_PULL_ENABLED = "refresh_policy.standard_source_auto_pull_enabled"
RUNTIME_KEY_STANDARD_SOURCE_AUTO_PULL_INTERVAL_MINUTES = (
    "refresh_policy.standard_source_auto_pull_interval_minutes"
)
DEFAULT_STANDARD_SOURCE_AUTO_PULL_ENABLED = True
DEFAULT_STANDARD_SOURCE_AUTO_PULL_INTERVAL_MINUTES = 30
RUNTIME_KEY_SURGE_PROCESS_RULES = "surge.process_rules"
RUNTIME_KEY_SURGE_EXTERNAL_PROXY_PROGRAMS = "surge.external_proxy_programs"
_logger = logging.getLogger("app.hub_service")
_UNREAD = object()  # matcher not read yet in this operation (None means "no values")
_BRACKETED_HOST_PORT_RE = re.compile(r"^\[(.+)\]:(\d{2,5})$")


def summarize_refresh_status(source_status: dict[str, object]) -> dict[str, object]:
    """Derive the public refresh outcome from every attempted source.

    Individual collectors intentionally preserve cached data after a failed
    pull.  That is useful for serving subscriptions, but it must not turn a
    failed refresh into a successful API response.  Keep the aggregate next
    to the per-source evidence so callers can make the same decision without
    reimplementing the failure rules.
    """

    failed: list[dict[str, str]] = []
    succeeded = 0

    def add_success(count: int = 1) -> None:
        nonlocal succeeded
        succeeded += count

    def add_failure(key: str, error: object = "") -> None:
        message = str(error or "refresh failed").strip() or "refresh failed"
        failed.append({"source": key, "error": message})

    def nonnegative_count(detail: dict, key: str) -> int:
        try:
            return max(int(detail.get(key) or 0), 0)
        except (TypeError, ValueError):
            return 0

    def add_outcome(key: str, detail: dict, *, fallback_success: bool = True) -> None:
        failure_count = nonnegative_count(detail, "failed_count")
        if detail.get("ok") is False and not failure_count:
            failure_count = 1
        if "succeeded_count" in detail:
            success_count = nonnegative_count(detail, "succeeded_count")
        else:
            success_count = int(detail.get("ok") is True and fallback_success)
        add_success(success_count)
        errors = detail.get("errors")
        for index in range(failure_count):
            error = (
                errors[index] if isinstance(errors, list) and index < len(errors)
                else detail.get("error") or detail.get("last_error")
            )
            add_failure(key, error)

    rule_catalog = source_status.get("rule_catalog")
    if isinstance(rule_catalog, dict):
        rule_outcome = dict(rule_catalog)
        if "succeeded_count" not in rule_outcome and "downloaded_count" in rule_outcome:
            rule_outcome["succeeded_count"] = nonnegative_count(rule_outcome, "downloaded_count")
        add_outcome("rule_catalog", rule_outcome, fallback_success=rule_catalog.get("source") != "cache")

    standard = source_status.get("standard")
    if isinstance(standard, dict):
        for source_id, detail in standard.items():
            if not isinstance(detail, dict):
                continue
            if detail.get("ok") is False:
                add_failure(f"standard:{source_id}", detail.get("error"))
            elif detail.get("ok") is True:
                add_success()

    gorelay = source_status.get("gorelay")
    if isinstance(gorelay, dict):
        accounts = gorelay.get("accounts")
        if "succeeded_count" in gorelay or "failed_count" in gorelay:
            # Collector counts belong to this refresh. Account status may
            # still include disabled accounts and older failed snapshots.
            add_outcome("gorelay", gorelay, fallback_success=False)
        elif isinstance(accounts, dict) and accounts:
            account_failures = 0
            for account_id, detail in accounts.items():
                if not isinstance(detail, dict):
                    continue
                status = str(detail.get("status") or "").strip().lower()
                if detail.get("ok") is False or status in {"failed", "error"} or detail.get("error"):
                    account_failures += 1
                    add_failure(
                        f"gorelay:{account_id}",
                        detail.get("error") or f"account status is {status or 'error'}",
                    )
                elif detail.get("ok") is True or status:
                    add_success()
            if (gorelay.get("ok") is False or gorelay.get("last_error")) and not account_failures:
                add_failure("gorelay", gorelay.get("error") or gorelay.get("last_error"))
        else:
            add_outcome("gorelay", gorelay, fallback_success=bool(gorelay.get("account_id")))
        # A GoRelay service with no enabled accounts is a no-op.  It should
        # not make an unrelated failed source look like a partial success.

    errors = [item["error"] for item in failed]
    failed_count = len(failed)
    return {
        "ok": failed_count == 0,
        "partial": bool(failed_count and succeeded),
        "status": "failed" if failed_count and not succeeded else "partial" if failed_count else "ok",
        "attempted_count": succeeded + failed_count,
        "succeeded_count": succeeded,
        "failed_count": failed_count,
        "errors": errors,
    }


@dataclass
class PolicyIrCacheEntry:
    token: str
    revision: str
    built_at: str
    nodes: list[NodeRecord]
    policy_ir: PolicyIR


@dataclass
class ArtifactCacheEntry:
    kind: str
    cache_key: str
    revision: str
    built_at: str
    value: object

    @property
    def etag(self) -> str:
        return f'"{self.revision}"'

    @property
    def last_modified(self) -> str:
        try:
            ts = datetime.fromisoformat(self.built_at.replace("Z", "+00:00"))
        except Exception:
            ts = datetime.now(timezone.utc)
        return format_datetime(ts.astimezone(timezone.utc), usegmt=True)


class HubService:
    def __init__(
        self,
        settings: Settings,
        repo: Repo,
        rule_catalog: RuleCatalog,
        source_fetcher: SourceFetcher,
        gorelay_service: GorelayService,
        runtime_monitor: RuntimeTaskMonitor | None = None,
        alerts: RuntimeAlertService | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.rule_catalog = rule_catalog
        self.source_fetcher = source_fetcher
        self.gorelay_service = gorelay_service
        self.runtime_monitor = runtime_monitor or NullRuntimeTaskMonitor()
        self.alerts = alerts

        self.runtime = HubRuntime()
        self._lock = asyncio.Lock()
        self._startup_refresh_task: asyncio.Task[None] | None = None
        self._background_task: asyncio.Task[None] | None = None
        self._standard_source_task: asyncio.Task[None] | None = None
        self._standard_source_policy_event = asyncio.Event()
        self._policy_ir_cache: dict[str, PolicyIrCacheEntry] = {}
        self._artifact_cache: dict[str, ArtifactCacheEntry] = {}
        self._refresh_lock_owner: str | None = None
        self._refresh_lock_owner_task: asyncio.Task[object] | None = None
        self._dependency_progress_invocation: ContextVar[str | None] = ContextVar(
            "subhub_dependency_progress_invocation",
            default=None,
        )
        self._active_dependency_invocation: str | None = None
        self._attach_dependency_progress(self.rule_catalog, "rule_catalog")
        self._attach_dependency_progress(self.gorelay_service, "gorelay")

    def _attach_dependency_progress(self, dependency: object, name: str) -> None:
        setter = getattr(dependency, "set_progress_callback", None)
        if callable(setter):
            setter(
                lambda details, dependency_name=name: self._report_dependency_progress(
                    dependency_name,
                    details,
                )
            )

    def _report_dependency_progress(
        self,
        dependency: str,
        details: dict[str, object],
    ) -> None:
        # A dependency may also be refreshed directly by its own resident or
        # management task.  Context-local invocation identity is set only
        # around the dependency call that this HubService is awaiting; an
        # unrelated child therefore cannot make a stale hub task look alive.
        invocation_var = getattr(self, "_dependency_progress_invocation", None)
        invocation_id = invocation_var.get() if invocation_var is not None else None
        if (
            not invocation_id
            or invocation_id != getattr(self, "_active_dependency_invocation", None)
            or self._refresh_lock_owner != "hub.refresh_loop"
        ):
            return
        self.runtime_monitor.heartbeat(
            "hub.refresh_loop",
            details={
                "phase": "dependency_progress",
                "dependency": dependency,
                "refresh_invocation_id": invocation_id,
                **dict(details),
            },
        )

    @contextmanager
    def _dependency_progress_scope(self, invocation_id: str):
        invocation_var = getattr(self, "_dependency_progress_invocation", None)
        if invocation_var is None:
            # ``object.__new__(HubService)`` is used by a few lightweight
            # service tests; lazily provide the same isolation there.
            invocation_var = ContextVar(
                "subhub_dependency_progress_invocation",
                default=None,
            )
            self._dependency_progress_invocation = invocation_var
        token = invocation_var.set(invocation_id)
        previous = getattr(self, "_active_dependency_invocation", None)
        self._active_dependency_invocation = invocation_id
        try:
            yield
        finally:
            self._active_dependency_invocation = previous
            invocation_var.reset(token)

    def _is_cache_fresh(self) -> bool:
        if not self.runtime.last_refresh_at:
            return False
        try:
            ts = datetime.fromisoformat(self.runtime.last_refresh_at.replace("Z", "+00:00"))
        except Exception:
            return False
        age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
        return age_seconds < max(self.settings.refresh_interval_minutes, 1) * 60

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _stable_json_hash(payload: object) -> str:
        normalized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def _node_revision_payload(cls, nodes: list[NodeRecord]) -> list[dict[str, object]]:
        payload = []
        for node in nodes:
            payload.append(
                {
                    "name": node.name,
                    "host": node.host,
                    "port": int(node.port),
                    "protocol": node.protocol,
                    "username": node.username,
                    "quality_group": node.quality_group,
                    "source_id": node.source_id,
                    "source_type": node.source_type,
                    "account_id": node.account_id,
                    "device_key": node.device_key,
                    "multiplier": node.multiplier,
                    "source_rule_id": node.source_rule_id,
                    "raw": dict(node.raw or {}),
                    "dedupe_key": node.dedupe_key(),
                }
            )
        payload.sort(
            key=lambda item: (
                str(item["quality_group"]),
                str(item["source_type"]),
                str(item["source_id"]),
                str(item["name"]),
                str(item["dedupe_key"]),
            )
        )
        return payload

    @staticmethod
    def _cache_key(*parts: object) -> str:
        return "|".join(str(part or "") for part in parts)

    def _clear_artifact_caches(self) -> None:
        self._policy_ir_cache.clear()
        self._artifact_cache.clear()

    @staticmethod
    def _safe_positive_int(value: object) -> int:
        try:
            parsed = int(value or 0)
        except Exception:
            return 0
        return parsed if parsed > 0 else 0

    @staticmethod
    def _normalize_interval(value: object, fallback: int) -> int:
        try:
            minutes = int(value)
        except Exception:
            return fallback
        return minutes if 1 <= minutes <= 1440 else fallback

    def _get_standard_source_auto_pull_enabled(self) -> bool:
        raw = self.repo.get_runtime_setting(RUNTIME_KEY_STANDARD_SOURCE_AUTO_PULL_ENABLED)
        if raw is None:
            return DEFAULT_STANDARD_SOURCE_AUTO_PULL_ENABLED
        return bool(raw)

    def _get_standard_source_auto_pull_interval_minutes(self) -> int:
        raw = self.repo.get_runtime_setting(
            RUNTIME_KEY_STANDARD_SOURCE_AUTO_PULL_INTERVAL_MINUTES
        )
        return self._normalize_interval(raw, DEFAULT_STANDARD_SOURCE_AUTO_PULL_INTERVAL_MINUTES)

    def get_standard_source_refresh_policy(self) -> dict[str, object]:
        return {
            "standard_source_auto_pull_enabled": self._get_standard_source_auto_pull_enabled(),
            "standard_source_auto_pull_interval_minutes": self._get_standard_source_auto_pull_interval_minutes(),
        }

    def update_standard_source_refresh_policy(
        self,
        *,
        enabled: bool | None = None,
        interval_minutes: int | None = None,
    ) -> dict[str, object]:
        if enabled is not None:
            self.repo.set_runtime_setting(
                RUNTIME_KEY_STANDARD_SOURCE_AUTO_PULL_ENABLED,
                bool(enabled),
            )
        if interval_minutes is not None:
            self.repo.set_runtime_setting(
                RUNTIME_KEY_STANDARD_SOURCE_AUTO_PULL_INTERVAL_MINUTES,
                self._normalize_interval(interval_minutes, DEFAULT_STANDARD_SOURCE_AUTO_PULL_INTERVAL_MINUTES),
            )
        # Wake the background loop so updated policy takes effect immediately.
        self._standard_source_policy_event.set()
        return self.get_standard_source_refresh_policy()

    async def ensure_started(self) -> None:
        if not self._startup_refresh_task or self._startup_refresh_task.done():
            self.runtime_monitor.register("hub.startup_refresh", required=False)
            self._startup_refresh_task = asyncio.create_task(self._startup_refresh())
            self.runtime_monitor.startup_success("hub.startup_refresh")
        if not self._background_task or self._background_task.done():
            self.runtime_monitor.register("hub.refresh_loop", required=True)
            self._background_task = asyncio.create_task(self._loop())
            self.runtime_monitor.watch("hub.refresh_loop", self._background_task)
            self.runtime_monitor.startup_success("hub.refresh_loop")
        if not self._standard_source_task or self._standard_source_task.done():
            self.runtime_monitor.register("hub.standard_source_loop", required=True)
            self._standard_source_task = asyncio.create_task(self._standard_source_loop())
            self.runtime_monitor.watch("hub.standard_source_loop", self._standard_source_task)
            self.runtime_monitor.startup_success("hub.standard_source_loop")

    async def shutdown(self) -> None:
        if self._startup_refresh_task:
            self._startup_refresh_task.cancel()
            try:
                await self._startup_refresh_task
            except asyncio.CancelledError:
                pass
            self._startup_refresh_task = None

        if self._standard_source_task:
            self.runtime_monitor.expect_stop("hub.standard_source_loop")
            self._standard_source_task.cancel()
            try:
                await self._standard_source_task
            except asyncio.CancelledError:
                pass
            self._standard_source_task = None

        if self._background_task:
            self.runtime_monitor.expect_stop("hub.refresh_loop")
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
            self._background_task = None
        self.runtime_monitor.stopped("hub.refresh_loop")
        self.runtime_monitor.stopped("hub.standard_source_loop")
        self.runtime_monitor.stopped("hub.startup_refresh")

    async def _startup_refresh(self) -> None:
        refresh_id = uuid4().hex
        self.runtime_monitor.heartbeat(
            "hub.startup_refresh",
            details={"phase": "running", "refresh_id": refresh_id},
        )
        try:
            await self.refresh(force=False, force_rule_catalog=False, rule_catalog_mode="incremental")
            self.runtime_monitor.success(
                "hub.startup_refresh",
                details={"phase": "complete", "refresh_id": refresh_id},
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Startup refresh is best-effort and should never block service availability.
            detail = error_detail(exc, "startup_refresh", refresh_id)
            self.runtime.last_error = detail["message"]
            _logger.error("startup refresh failed: %s", detail)
            self.runtime_monitor.failure(
                "hub.startup_refresh",
                "startup refresh failed",
                details=detail,
            )

    async def _loop(self) -> None:
        interval = max(self.settings.refresh_interval_minutes, 1) * 60
        while True:
            await self._sleep_with_heartbeat(interval, "hub.refresh_loop")
            try:
                # ``refresh`` owns the shared lock and records the owner
                # heartbeat after acquisition.  A direct heartbeat here
                # would make this resident task look healthy while it is
                # merely queued behind another refresh owner.
                await self.refresh(force=True, force_rule_catalog=False, rule_catalog_mode="incremental")
                self.runtime_monitor.success(
                    "hub.refresh_loop",
                    details={"phase": "refresh_complete"},
                )
            except Exception as exc:
                detail = error_detail(exc, "scheduled_refresh", uuid4().hex)
                self.runtime.last_error = detail["message"]
                _logger.error("scheduled refresh failed: %s", detail)
                self.runtime_monitor.failure(
                    "hub.refresh_loop",
                    "scheduled refresh failed",
                    details=detail,
                )

    async def _standard_source_loop(self) -> None:
        while True:
            wait_seconds = max(self._get_standard_source_auto_pull_interval_minutes(), 1) * 60
            if await self._wait_for_standard_source_policy(wait_seconds):
                continue

            if not self._get_standard_source_auto_pull_enabled():
                continue
            try:
                await self.refresh_standard_sources_only()
                self.runtime_monitor.success(
                    "hub.standard_source_loop",
                    details={"phase": "refresh_complete"},
                )
            except Exception as exc:
                detail = error_detail(exc, "scheduled_standard_source_refresh", uuid4().hex)
                self.runtime.last_error = detail["message"]
                _logger.error("scheduled standard-source refresh failed: %s", detail)
                self.runtime_monitor.failure(
                    "hub.standard_source_loop",
                    "scheduled standard-source refresh failed",
                    details=detail,
                )

    async def _wait_for_standard_source_policy(self, seconds: int) -> bool:
        """Wait for policy changes while keeping the resident task observable."""
        remaining = max(int(seconds), 0)
        heartbeat_interval = max(
            int(getattr(self.settings, "runtime_heartbeat_interval_seconds", 30)),
            5,
        )
        while remaining > 0:
            heartbeat_name, heartbeat_kwargs = self._resident_heartbeat_target(
                "hub.standard_source_loop"
            )
            self.runtime_monitor.heartbeat(
                heartbeat_name,
                details={"phase": "waiting", "remaining_seconds": remaining},
                **heartbeat_kwargs,
            )
            timeout = min(remaining, heartbeat_interval)
            try:
                await asyncio.wait_for(self._standard_source_policy_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                remaining -= timeout
                continue
            self._standard_source_policy_event.clear()
            heartbeat_name, heartbeat_kwargs = self._resident_heartbeat_target(
                "hub.standard_source_loop"
            )
            self.runtime_monitor.heartbeat(
                heartbeat_name,
                details={"phase": "policy_changed"},
                **heartbeat_kwargs,
            )
            return True
        return False

    def _resident_heartbeat_target(
        self,
        task_name: str,
    ) -> tuple[str, dict[str, object]]:
        """Keep a resident waiter's heartbeat separate from a stalled owner."""
        heartbeat_name = task_name
        heartbeat_kwargs: dict[str, object] = {}
        owner_task = getattr(self, "_refresh_lock_owner_task", None)
        waiter_names = {
            "hub.refresh_loop": "hub.refresh.waiter",
            "hub.standard_source_loop": "hub.standard_source.waiter",
        }
        if (
            owner_task is not None
            and owner_task is not asyncio.current_task()
            and getattr(self, "_refresh_lock_owner", None) == task_name
            and task_name in waiter_names
        ):
            heartbeat_name = waiter_names[task_name]
            heartbeat_kwargs["required"] = False
        return heartbeat_name, heartbeat_kwargs

    async def _sleep_with_heartbeat(self, seconds: int, task_name: str) -> None:
        remaining = max(0, int(seconds))
        interval = max(int(getattr(self.settings, "runtime_heartbeat_interval_seconds", 30)), 5)
        while remaining > 0:
            delay = min(remaining, interval)
            await asyncio.sleep(delay)
            remaining -= delay
            if remaining > 0:
                # The resident loop can still be in this sleep while a
                # manually-triggered refresh owns the shared lock.  Its
                # liveness heartbeat is not evidence that the other owner is
                # progressing, so keep it on the non-required waiter key.
                heartbeat_name, heartbeat_kwargs = self._resident_heartbeat_target(task_name)
                self.runtime_monitor.heartbeat(
                    heartbeat_name,
                    details={"phase": "sleeping", "remaining_seconds": remaining},
                    **heartbeat_kwargs,
                )

    @asynccontextmanager
    async def _refresh_lock_context(
        self,
        task_name: str,
        *,
        waiter_task_name: str | None = None,
    ):
        """Acquire the shared refresh lock without losing queued-task liveness.

        A standard-source refresh can legitimately queue behind the full
        refresh.  Heartbeat while waiting so the queued worker remains
        observable, but use a separate, non-required task identity when the
        waiter and owner are the same resident task.  Otherwise two
        overlapping ``refresh()`` calls would update ``hub.refresh_loop``
        while the first call is stalled, making a dead owner look healthy.
        The owner's own heartbeat is still required to prove that a real
        refresh is making progress.
        """
        try:
            interval = float(
                getattr(self.settings, "runtime_heartbeat_interval_seconds", 30)
            )
        except (TypeError, ValueError):
            interval = 30.0
        interval = max(interval, 0.05)
        while True:
            try:
                await asyncio.wait_for(self._lock.acquire(), timeout=interval)
                break
            except asyncio.TimeoutError:
                heartbeat_name = task_name
                heartbeat_kwargs: dict[str, object] = {}
                # A same-named invocation is waiting behind the resident
                # owner and must not refresh that owner's required heartbeat.
                # When the owner is a different task (for example a full
                # refresh queued behind a healthy standard-source refresh),
                # the queued task's required heartbeat remains authoritative.
                if waiter_task_name and self._refresh_lock_owner == task_name:
                    heartbeat_name = waiter_task_name
                    heartbeat_kwargs["required"] = False
                self.runtime_monitor.heartbeat(
                    heartbeat_name,
                    details={
                        "phase": "waiting_for_refresh_lock",
                        "lock_owner_task": self._refresh_lock_owner or "unknown",
                    },
                    **heartbeat_kwargs,
                )
        self._refresh_lock_owner = task_name
        self._refresh_lock_owner_task = asyncio.current_task()
        try:
            self.runtime_monitor.heartbeat(
                task_name,
                details={
                    "phase": "refresh_lock_acquired",
                    "lock_owner_task": task_name,
                },
            )
            yield
        finally:
            if self._refresh_lock_owner_task is asyncio.current_task():
                self._refresh_lock_owner_task = None
            self._refresh_lock_owner = None
            self._lock.release()

    async def refresh(
        self,
        force: bool = False,
        force_rule_catalog: bool = False,
        rule_catalog_mode: str = "incremental",
    ) -> HubRuntime:
        if not force and self._is_cache_fresh():
            return self.runtime
        async with self._refresh_lock_context(
            "hub.refresh_loop",
            waiter_task_name="hub.refresh.waiter",
        ):
            if not force and self._is_cache_fresh():
                return self.runtime
            source_status: dict[str, object] = {
                "standard": {},
                "gorelay": {},
            }
            refresh_id = uuid4().hex
            source_status["refresh_id"] = refresh_id
            with self._dependency_progress_scope(refresh_id):
                try:
                    source_status["rule_catalog"] = await self.rule_catalog.refresh_categories(
                        force=force_rule_catalog,
                        mode=rule_catalog_mode,
                    )
                except Exception as exc:
                    detail = error_detail(exc, "rule_catalog_refresh", refresh_id)
                    _logger.error("rule catalog refresh failed: %s", detail)
                    source_status["rule_catalog"] = {
                        "ok": False,
                        "error": detail["message"],
                        "error_detail": detail,
                    }
            self.runtime_monitor.heartbeat(
                "hub.refresh_loop",
                details={
                    "phase": "refresh_progress",
                    "unit": "rule_catalog",
                    "ok": bool((source_status["rule_catalog"] or {}).get("ok", True)),
                },
            )

            with self._dependency_progress_scope(refresh_id):
                try:
                    gorelay_runtime = await self.gorelay_service.refresh(force=force)
                    gorelay_summary = self.gorelay_service.refresh_summary()
                    if not force:
                        # refresh(force=False) serves its cached runtime and
                        # makes no GoRelay attempt in this hub operation.
                        gorelay_summary = {"ok": True, "attempted_count": 0, "succeeded_count": 0, "failed_count": 0}
                    source_status["gorelay"] = {
                        **gorelay_summary,
                        "last_refresh_at": gorelay_runtime.last_refresh_at,
                        "last_error": gorelay_runtime.last_error,
                        "accounts": gorelay_runtime.account_status,
                    }
                except Exception as exc:
                    detail = error_detail(exc, "gorelay_refresh", refresh_id)
                    _logger.error("gorelay refresh failed: %s", detail)
                    source_status["gorelay"] = {
                        "ok": False,
                        "error": detail["message"],
                        "error_detail": detail,
                    }
            self.runtime_monitor.heartbeat(
                "hub.refresh_loop",
                details={
                    "phase": "refresh_progress",
                    "unit": "gorelay",
                    "ok": bool((source_status["gorelay"] or {}).get("ok", True)),
                },
            )

            standard_sources = [item for item in self.repo.list_standard_sources() if item.enabled]
            for source in standard_sources:
                count, detail = await self._refresh_standard_source_with_diagnostics(
                    source, trigger="auto", refresh_id=refresh_id
                )
                source_status["standard"][source.id] = {
                    "source_name": source.name,
                    "node_count": count,
                    **detail,
                }
                self.runtime_monitor.heartbeat(
                    "hub.refresh_loop",
                    details={
                        "phase": "refresh_progress",
                        "unit": "standard_source",
                        "source_id": source.id,
                        "ok": bool(detail.get("ok", False)),
                    },
                )

            discovered_devices = self._collect_gorelay_device_names()
            if discovered_devices:
                self._sync_device_subscriptions(discovered_devices)
            else:
                # In standard-source-only mode keep existing manual subscriptions
                # stable; create a default device only when no subscriptions exist.
                self._ensure_default_device_subscription()

            known_secrets = known_source_secrets(self.repo.list_standard_sources())
            aggregate = summarize_refresh_status(source_status)
            source_status["aggregate"] = aggregate
            self.runtime.last_refresh_at = self._now()
            self.runtime.last_error = "; ".join(
                summarize_pull_errors(error, known_secrets) for error in aggregate["errors"]
            ) or None
            self.runtime.source_status = source_status
            self._clear_artifact_caches()
            return self.runtime

    async def refresh_standard_sources_only(self) -> dict[str, object]:
        async with self._refresh_lock_context(
            "hub.standard_source_loop",
            waiter_task_name="hub.standard_source.waiter",
        ):
            refresh_id = uuid4().hex
            source_status = dict(self.runtime.source_status or {})
            standard_status = dict(source_status.get("standard") or {})
            current_standard_status: dict[str, object] = {}
            standard_sources = [item for item in self.repo.list_standard_sources() if item.enabled]
            for source in standard_sources:
                count, detail = await self._refresh_standard_source_with_diagnostics(
                    source, trigger="auto", refresh_id=refresh_id
                )
                standard_status[source.id] = {
                    "source_name": source.name,
                    "node_count": count,
                    **detail,
                }
                self.runtime_monitor.heartbeat(
                    "hub.standard_source_loop",
                    details={
                        "phase": "refresh_progress",
                        "unit": "standard_source",
                        "source_id": source.id,
                        "ok": bool(detail.get("ok", False)),
                    },
                )
                current_standard_status[source.id] = standard_status[source.id]
            source_status["standard"] = standard_status
            known_secrets = known_source_secrets(self.repo.list_standard_sources())
            aggregate = summarize_refresh_status({"standard": current_standard_status})
            source_status["aggregate"] = aggregate
            source_status["refresh_id"] = refresh_id
            self.runtime.last_error = "; ".join(
                summarize_pull_errors(error, known_secrets) for error in aggregate["errors"]
            ) or None
            self.runtime.source_status = source_status
            self._clear_artifact_caches()
            return public_source_status(
                {**aggregate, "standard": current_standard_status, "refresh_id": refresh_id},
                known_secrets,
            )

    async def refresh_one_standard_source(
        self,
        source_id: str,
        trigger: str = "manual",
    ) -> dict[str, object]:
        async with self._refresh_lock_context(
            "hub.standard_source_loop",
            waiter_task_name="hub.standard_source.waiter",
        ):
            refresh_id = uuid4().hex
            source = self.repo.get_standard_source(source_id)
            if not source:
                raise ValueError("standard source not found")
            count, detail = await self._refresh_standard_source_with_diagnostics(
                source, trigger=trigger, refresh_id=refresh_id
            )
            source_status = dict(self.runtime.source_status or {})
            standard_status = dict(source_status.get("standard") or {})
            standard_status[source.id] = {
                "source_name": source.name,
                "node_count": count,
                **detail,
            }
            source_status["standard"] = standard_status
            known_secrets = known_source_secrets(self.repo.list_standard_sources())
            aggregate = summarize_refresh_status({"standard": {source.id: standard_status[source.id]}})
            source_status["aggregate"] = aggregate
            source_status["refresh_id"] = refresh_id
            self.runtime.last_error = "; ".join(
                summarize_pull_errors(error, known_secrets) for error in aggregate["errors"]
            ) or None
            self.runtime.source_status = source_status
            self._clear_artifact_caches()
            return public_source_status({
                "source_id": source.id,
                "source_name": source.name,
                "node_count": count,
                **detail,
            }, known_secrets)

    async def _refresh_standard_source_with_diagnostics(
        self,
        source,
        *,
        trigger: str,
        refresh_id: str,
    ) -> tuple[int, dict[str, object]]:
        known_secrets: object = _UNREAD
        try:
            count, detail = await self._refresh_standard_source(source, trigger=trigger)
            detail = {**detail, "refresh_id": refresh_id}
        except Exception as exc:
            diagnostic = error_detail(exc, "standard_source_refresh", refresh_id)
            _logger.error("standard source refresh failed source_id=%s: %s", source.id, diagnostic)
            known_secrets = known_source_secrets(self.repo.list_standard_sources())
            diagnostic = source_error_detail(
                exc, "standard_source_refresh", refresh_id, *((known_secrets,) if known_secrets else ()),
            )
            self.repo.save_standard_source_pull_status(
                source.id, attempt_at=self._now(), ok=False, method="", node_count=0,
                error=diagnostic["message"], trigger=trigger,
                reasons=[{"method": "", "code": "refresh_failed", "url": "", "message": diagnostic["message"]}],
            )
            latest = self.repo.get_standard_source(source.id)
            cached_count = len(self.repo.load_standard_node_cache(source.id) or [])
            count = cached_count
            detail = {
                "ok": False,
                "error": diagnostic["message"],
                "error_detail": diagnostic,
                "refresh_id": refresh_id,
                "attempts": [],
                "pull_method": "",
                "pull_node_count": latest.last_pull_node_count if latest else cached_count,
                "cached_node_count": cached_count,
                "last_success_at": latest.last_success_at if latest else None,
            }
        if known_secrets is _UNREAD:
            known_secrets = known_source_secrets(self.repo.list_standard_sources())
        if known_secrets:
            detail = public_source_status(detail, known_secrets)
        self.repo.set_runtime_setting(standard_source_diagnostics_key(source.id), {
            "warning_count": int(detail.get("warning_count") or 0),
            "warnings": list(detail.get("warnings") or []),
            "filtered_technical_count": int(detail.get("filtered_technical_count") or 0),
            "filtered_technical_examples": list(detail.get("filtered_technical_examples") or []),
            "unrecognized_multiplier_count": int(detail.get("unrecognized_multiplier_count") or 0),
            "unrecognized_multiplier_examples": list(detail.get("unrecognized_multiplier_examples") or []),
        })
        return count, detail

    async def _refresh_standard_source(
        self,
        source,
        *,
        trigger: str = "auto",
    ) -> tuple[int, dict[str, object]]:
        if source.resolved_ingest_kind() == STANDARD_SOURCE_INGEST_MANUAL_NODES:
            pull_result = self.source_fetcher.parse_manual_nodes(source)
        else:
            pull_result = await self.source_fetcher.fetch_source(source)
        attempt_at = self._now()
        known_secrets = known_source_secrets(self.repo.list_standard_sources())

        if not pull_result.ok:
            self.repo.save_standard_source_pull_status(
                source.id,
                attempt_at=attempt_at,
                ok=False,
                method="",
                node_count=0,
                error=summarize_pull_errors(pull_result.error, known_secrets) if pull_result.error else "",
                trigger=trigger,
                reasons=pull_result.failure_reasons(known_secrets),
            )
            latest = self.repo.get_standard_source(source.id)
            cached_count = len(self.repo.load_standard_node_cache(source.id) or [])
            preserved_pull_count = (
                int(latest.last_pull_node_count)
                if latest and latest.last_pull_node_count is not None
                else cached_count
            )
            return cached_count, {
                "ok": False,
                "error": pull_result.error,
                "attempts": [item.to_dict(known_secrets) for item in pull_result.attempts],
                "pull_method": "",
                "pull_node_count": max(preserved_pull_count, 0),
                "cached_node_count": cached_count,
                "warning_count": len(pull_result.warnings),
                "warnings": [item.to_dict() for item in pull_result.warnings],
                "filtered_technical_count": int(pull_result.filtered_technical_count),
                "filtered_technical_examples": list(pull_result.filtered_technical_examples),
                "last_success_at": latest.last_success_at if latest else None,
                "config_fingerprint": (
                    latest.config_fingerprint() if latest else source.config_fingerprint()
                ),
                "last_success_config_fingerprint": (
                    latest.last_success_config_fingerprint if latest else ""
                ),
                "pull_network_mode": latest.pull_network_mode if latest else source.pull_network_mode,
                "auto_pull_consecutive_failures": (
                    latest.auto_pull_consecutive_failures
                    if latest
                    else source.auto_pull_consecutive_failures
                ),
                "auto_pull_expired": latest.auto_pull_expired if latest else source.auto_pull_expired,
                "auto_pull_expired_at": (
                    latest.auto_pull_expired_at if latest else source.auto_pull_expired_at
                ),
                "unrecognized_multiplier_count": 0,
                "unrecognized_examples": [],
            }

        normalized: list[NodeRecord] = []
        unrecognized_examples: list[str] = []
        unrecognized_count = 0
        source_mode = source.resolved_source_mode()

        if source_mode == STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT:
            for node in pull_result.nodes:
                multiplier = extract_high_quality_airport_multiplier(node.name, node.raw)
                if not multiplier:
                    unrecognized_count += 1
                    if len(unrecognized_examples) < 5:
                        unrecognized_examples.append(node.name)
                    continue
                try:
                    value = float(multiplier)
                except ValueError:
                    unrecognized_count += 1
                    if len(unrecognized_examples) < 5:
                        unrecognized_examples.append(node.name)
                    continue

                node.quality_group = (
                    QUALITY_HIGH_PREMIUM
                    if value >= HIGH_QUALITY_AIRPORT_THRESHOLD
                    else QUALITY_HIGH_STANDARD
                )
                node.name = decorate_high_quality_node_name(node.name, node.quality_group)
                node.source_id = source.id
                node.source_type = "standard"
                node.multiplier = multiplier
                normalized.append(node)
        else:
            target_contract = self.repo.get_route_contract(source.resolved_target_contract_id())
            default_group = (
                target_contract.primary_legacy_group()
                if target_contract
                else contract_legacy_group(source.resolved_target_contract_id())
            )
            if default_group not in QUALITY_GROUPS or default_group == QUALITY_CHAIN_HOME:
                default_group = QUALITY_MEDIUM
            for node in pull_result.nodes:
                node.quality_group = default_group
                node.source_id = source.id
                node.source_type = "standard"
                normalized.append(node)

        deduped = self._dedupe_nodes(normalized)
        self.repo.save_standard_node_cache(source.id, deduped)
        self.repo.save_standard_source_pull_status(
            source.id,
            attempt_at=attempt_at,
            ok=True,
            method=pull_result.method,
            node_count=len(deduped),
            error="",
            success_config_fingerprint=source.config_fingerprint(),
            trigger=trigger,
        )
        latest = self.repo.get_standard_source(source.id)
        return len(deduped), {
            "ok": True,
            "error": "",
            "attempts": [item.to_dict(known_secrets) for item in pull_result.attempts],
            "pull_method": pull_result.method,
            "pull_node_count": len(deduped),
            "cached_node_count": len(deduped),
            "warning_count": len(pull_result.warnings),
            "warnings": [item.to_dict() for item in pull_result.warnings],
            "filtered_technical_count": int(pull_result.filtered_technical_count),
            "filtered_technical_examples": list(pull_result.filtered_technical_examples),
            "last_success_at": latest.last_success_at if latest else attempt_at,
            "config_fingerprint": (
                latest.config_fingerprint() if latest else source.config_fingerprint()
            ),
            "last_success_config_fingerprint": (
                latest.last_success_config_fingerprint
                if latest
                else source.config_fingerprint()
            ),
            "pull_network_mode": latest.pull_network_mode if latest else source.pull_network_mode,
            "auto_pull_consecutive_failures": (
                latest.auto_pull_consecutive_failures
                if latest
                else source.auto_pull_consecutive_failures
            ),
            "auto_pull_expired": latest.auto_pull_expired if latest else source.auto_pull_expired,
            "auto_pull_expired_at": latest.auto_pull_expired_at if latest else source.auto_pull_expired_at,
            "unrecognized_multiplier_count": unrecognized_count,
            "unrecognized_examples": unrecognized_examples,
        }

    def _collect_gorelay_device_names(self) -> dict[str, str]:
        devices: dict[str, str] = {}
        for account in self.gorelay_service.list_accounts():
            if not account.enabled:
                continue
            snap = self.repo.load_gorelay_active_account_snapshot(account.id)
            if not snap:
                continue
            for key, name in snap.device_names.items():
                devices.setdefault(key, name)
        return devices

    def _ensure_default_device_subscription(self) -> None:
        if self.repo.list_device_subscriptions():
            return
        self.repo.save_device_subscription(
            DeviceSubscription(
                id=uuid4().hex,
                device_key="default",
                device_name="Default",
                token=uuid4().hex,
                enabled=True,
            )
        )

    def _sync_device_subscriptions(self, device_names: dict[str, str]) -> dict[str, int]:
        stats = {
            "added_count": 0,
            "reenabled_count": 0,
            "renamed_count": 0,
            "disabled_count": 0,
        }
        existing = {item.device_key: item for item in self.repo.list_device_subscriptions()}

        for key, item in existing.items():
            if key in device_names:
                continue
            if item.enabled:
                item.enabled = False
                self.repo.save_device_subscription(item)
                stats["disabled_count"] += 1

        for key, name in device_names.items():
            found = existing.get(key)
            if found:
                changed = False
                if found.device_name != name:
                    found.device_name = name
                    changed = True
                    stats["renamed_count"] += 1
                if not found.enabled:
                    found.enabled = True
                    changed = True
                    stats["reenabled_count"] += 1
                if changed:
                    self.repo.save_device_subscription(found)
                continue

            self.repo.save_device_subscription(
                DeviceSubscription(
                    id=uuid4().hex,
                    device_key=key,
                    device_name=name,
                    token=uuid4().hex,
                    enabled=True,
                )
            )
            stats["added_count"] += 1
        return stats

    def sync_devices_from_gorelay_snapshots(self) -> dict[str, int]:
        """Sync management device subscriptions from active GoRelay snapshots only."""
        before_items = self.repo.list_device_subscriptions()
        before_count = len(before_items)
        before_enabled_count = sum(1 for item in before_items if item.enabled)
        discovered_devices = self._collect_gorelay_device_names()

        stats = {
            "added_count": 0,
            "reenabled_count": 0,
            "renamed_count": 0,
            "disabled_count": 0,
        }
        if discovered_devices:
            stats = self._sync_device_subscriptions(discovered_devices)

        after_items = self.repo.list_device_subscriptions()
        after_count = len(after_items)
        after_enabled_count = sum(1 for item in after_items if item.enabled)
        changed_count = (
            stats["added_count"]
            + stats["reenabled_count"]
            + stats["renamed_count"]
            + stats["disabled_count"]
        )
        if changed_count:
            self._clear_artifact_caches()

        return {
            "before_count": before_count,
            "after_count": after_count,
            "before_enabled_count": before_enabled_count,
            "after_enabled_count": after_enabled_count,
            "discovered_count": len(discovered_devices),
            **stats,
        }

    @staticmethod
    def _dedupe_nodes(nodes: list[NodeRecord]) -> list[NodeRecord]:
        seen: set[str] = set()
        output: list[NodeRecord] = []
        for node in nodes:
            key = node.dedupe_key()
            if key in seen:
                continue
            seen.add(key)
            output.append(node)
        return output

    def list_devices(self) -> list[DeviceSubscription]:
        return self.repo.list_device_subscriptions()

    def get_subscription(self, token: str) -> DeviceSubscription | None:
        item = self.repo.get_device_subscription_by_token(token)
        if not item or not item.enabled:
            return None
        return item

    def get_subscription_by_public_id(self, public_id: str) -> DeviceSubscription | None:
        item = self.repo.get_device_subscription_by_public_id(public_id)
        if not item or not item.enabled:
            return None
        return item

    def get_nodes_for_token(self, token: str) -> list[NodeRecord] | None:
        gorelay_sub = self.gorelay_service.get_subscription_by_token(token)
        if gorelay_sub:
            if not gorelay_sub.enabled:
                return None
            merged = self.gorelay_service.get_device_nodes_for_subscription(gorelay_sub)
            merged.extend(self._load_standard_nodes())
            deduped = self._dedupe_nodes(merged)
            return self._with_chain_home_combinations(deduped, device_key=gorelay_sub.device_key)

        sub = self.get_subscription(token)
        if not sub:
            return None

        merged: list[NodeRecord] = []
        for node in self.gorelay_service.get_all_active_nodes():
            if node.device_key == sub.device_key:
                merged.append(node)
        merged.extend(self._load_standard_nodes())
        deduped = self._dedupe_nodes(merged)
        return self._with_chain_home_combinations(deduped, device_key=sub.device_key)

    def get_nodes_for_public_id(self, public_id: str) -> list[NodeRecord] | None:
        gorelay_sub = self.gorelay_service.get_subscription_by_public_id(public_id)
        if gorelay_sub:
            return self.get_nodes_for_token(gorelay_sub.token)
        sub = self.get_subscription_by_public_id(public_id)
        if not sub:
            return None
        return self.get_nodes_for_token(sub.token)

    @staticmethod
    def _is_standalone_chain_home_node(node: NodeRecord) -> bool:
        raw = node.raw or {}
        return node.quality_group == QUALITY_CHAIN_HOME or bool(raw.get("chain_home"))

    @staticmethod
    def _parse_host_port(raw: object) -> tuple[str, int]:
        text = str(raw or "").strip()
        if not text:
            return "", 0
        bracketed = _BRACKETED_HOST_PORT_RE.match(text)
        if bracketed:
            host = str(bracketed.group(1) or "").strip()
            port = int(str(bracketed.group(2) or "").strip() or 0)
            if host and 1 <= port <= 65535:
                return host, port
            return "", 0
        host, sep, port_text = text.rpartition(":")
        if not sep:
            return "", 0
        clean_host = host.strip()
        try:
            port = int(port_text.strip())
        except ValueError:
            return "", 0
        if not clean_host or not (1 <= port <= 65535):
            return "", 0
        return clean_host, port

    @classmethod
    def _parse_chain_target(cls, raw: object) -> tuple[str, int, str, str]:
        text = str(raw or "").strip()
        if not text:
            return "", 0, "", ""

        if "://" in text:
            parsed = urlsplit(text)
            if parsed.scheme.lower() != "socks5":
                return "", 0, "", ""
            host = str(parsed.hostname or "").strip()
            try:
                port = int(parsed.port or 0)
            except ValueError:
                return "", 0, "", ""
            if not host or not (1 <= port <= 65535):
                return "", 0, "", ""
            return (
                host,
                port,
                unquote(str(parsed.username or "").strip()),
                unquote(str(parsed.password or "").strip()),
            )

        auth_part = ""
        host_port = text
        if "@" in text:
            auth_part, host_port = text.rsplit("@", 1)
        host, port = cls._parse_host_port(host_port)
        if not host or port <= 0:
            return "", 0, "", ""

        if not auth_part:
            return host, port, "", ""

        username_raw, sep, password_raw = auth_part.partition(":")
        username = unquote(username_raw.strip())
        password = unquote(password_raw.strip()) if sep else ""
        return host, port, username, password

    @staticmethod
    def _credential_rank(username: str, password: str) -> int:
        return int(bool(str(username or "").strip())) + int(bool(str(password or "").strip()))

    def _resolve_chain_credentials(
        self,
        *,
        account_id: str,
        device_key: str,
        explicit_username: str,
        explicit_password: str,
    ) -> tuple[str, str, str]:
        fallback_username, fallback_password = self.gorelay_service.resolve_proxy_credentials(account_id, device_key)
        username = str(explicit_username or "").strip() or str(fallback_username or "").strip()
        password = str(explicit_password or "").strip() or str(fallback_password or "").strip()
        if explicit_username or explicit_password:
            return username, password, "target"
        if fallback_username or fallback_password:
            return username, password, "device_or_account"
        return "", "", "none"

    def _update_chain_home_auth_diagnostics(self, chain_nodes: list[NodeRecord], *, device_key: str) -> None:
        missing: list[dict[str, object]] = []
        checked = 0
        for node in chain_nodes:
            if node.protocol.lower() != "socks5":
                continue
            checked += 1
            has_username = bool(str(node.username or "").strip())
            has_password = bool(str(node.password or "").strip())
            if has_username and has_password:
                continue
            missing.append(
                {
                    "account_id": str(node.account_id or ""),
                    "device_key": device_key,
                    "rear_target": str((node.raw or {}).get("chain_rear_target", "")),
                    "has_username": has_username,
                    "has_password": has_password,
                }
            )

        source_status = dict(self.runtime.source_status or {})
        previous = dict(source_status.get("chain_home_auth") or {})
        source_status["chain_home_auth"] = {
            "checked_chain_node_count": checked,
            "missing_auth_count": len(missing),
            "missing_auth_examples": missing[:20],
            "updated_at": self._now(),
        }
        self.runtime.source_status = source_status

        previous_count = int(previous.get("missing_auth_count") or 0)
        if missing and previous_count != len(missing):
            _logger.warning(
                "chain_home socks5 auth missing: device=%s count=%s examples=%s",
                device_key,
                len(missing),
                missing[:5],
            )

    @staticmethod
    def _outbound_device_key(outbound: CollectedOutbound) -> str:
        device_name = str(outbound.device_name or "").strip()
        if device_name:
            return build_device_key(device_name)
        derived_name = extract_device_group(outbound.line_name)[0]
        return build_device_key(derived_name)

    def _chain_home_outbounds_for_device(self, device_key: str) -> list[CollectedOutbound]:
        outbounds: list[CollectedOutbound] = []
        for account in self.gorelay_service.list_accounts():
            if not account.enabled:
                continue
            snapshot = self.repo.load_gorelay_active_account_snapshot(account.id)
            if not snapshot:
                continue
            for outbound in snapshot.collected_outbounds:
                if self._outbound_device_key(outbound) != device_key:
                    continue
                outbounds.append(outbound)
        return outbounds

    @staticmethod
    def _build_chain_home_rear_labels(
        rear_targets: dict[tuple[str, str], tuple[str, int, str, str, CollectedOutbound]],
    ) -> dict[tuple[str, str], str]:
        targets_by_account: dict[str, list[str]] = {}
        for account_id, target_key in rear_targets:
            targets_by_account.setdefault(account_id, []).append(target_key)

        labels: dict[tuple[str, str], str] = {}
        for account_id, target_keys in targets_by_account.items():
            for idx, target_key in enumerate(sorted(set(target_keys)), start=1):
                labels[(account_id, target_key)] = f"家宽{idx}"
        return labels

    def _build_chain_home_combo_nodes(
        self,
        front_nodes: list[NodeRecord],
        outbounds: list[CollectedOutbound],
        *,
        device_key: str,
    ) -> list[NodeRecord]:
        if not front_nodes or not outbounds:
            return []

        rear_targets: dict[tuple[str, str], tuple[str, int, str, str, CollectedOutbound]] = {}
        for outbound in outbounds:
            for target in list(outbound.targets or []):
                host, port, target_username, target_password = self._parse_chain_target(target)
                if not host or port <= 0:
                    continue
                target_key = f"{host}:{port}".lower()
                account_id = str(outbound.account_id or "").strip()
                rear_key = (account_id, target_key)
                existing = rear_targets.get(rear_key)
                if existing and (
                    self._credential_rank(target_username, target_password)
                    <= self._credential_rank(existing[2], existing[3])
                ):
                    continue
                rear_targets[rear_key] = (host, port, target_username, target_password, outbound)

        rear_labels = self._build_chain_home_rear_labels(rear_targets)

        combos: list[NodeRecord] = []
        for (account_id, target_key), (
            host,
            port,
            target_username,
            target_password,
            outbound,
        ) in sorted(rear_targets.items(), key=lambda item: item[0]):
            rear_label = rear_labels.get((account_id, target_key), f"{host}:{port}")
            username, password, auth_source = self._resolve_chain_credentials(
                account_id=account_id,
                device_key=device_key,
                explicit_username=target_username,
                explicit_password=target_password,
            )
            combos.append(
                NodeRecord(
                    name=f"链式家宽 | {rear_label}",
                    host=host,
                    port=port,
                    protocol="socks5",
                    username=username,
                    password=password,
                    quality_group=QUALITY_CHAIN_HOME,
                    source_id=account_id,
                    source_type="chain_combo",
                    account_id=account_id,
                    device_key=device_key,
                    device_name=str(outbound.device_name or ""),
                    multiplier=str(outbound.multiplier or ""),
                    source_rule_id=str(outbound.rule_id or ""),
                    source_entry_name=str(outbound.outbound_group_name or ""),
                    raw={
                        "chain_home": True,
                        "chain_rear_label": rear_label,
                        "chain_rear_target": target_key,
                        "chain_rear_group_name": str(outbound.outbound_group_name or ""),
                        "chain_rear_auth_source": auth_source,
                    },
                )
            )
        return combos

    def _with_chain_home_combinations(self, nodes: list[NodeRecord], *, device_key: str) -> list[NodeRecord]:
        base_nodes = [node for node in nodes if not self._is_standalone_chain_home_node(node)]
        front_nodes = [
            node
            for node in base_nodes
            if node.quality_group in {QUALITY_MEDIUM, QUALITY_BULK}
        ]
        outbounds = self._chain_home_outbounds_for_device(device_key)
        combos = self._build_chain_home_combo_nodes(front_nodes, outbounds, device_key=device_key)
        merged = self._dedupe_nodes([*base_nodes, *combos])
        chain_nodes = [node for node in merged if self._is_standalone_chain_home_node(node)]
        self._update_chain_home_auth_diagnostics(chain_nodes, device_key=device_key)
        return merged

    def _load_standard_nodes(self) -> list[NodeRecord]:
        nodes: list[NodeRecord] = []
        for source in self.repo.list_standard_sources():
            if not source.enabled:
                continue
            nodes.extend(self.repo.load_standard_node_cache(source.id) or [])
        return nodes

    def get_shadowrocket_subscription_userinfo(
        self,
        token: str,
        *,
        nodes: list[NodeRecord] | None = None,
    ) -> str | None:
        current_nodes = list(nodes) if nodes is not None else self.get_nodes_for_token(token)
        if not current_nodes:
            return None

        account_ids: set[str] = set()
        for node in current_nodes:
            if node.source_type != "gorelay":
                return None
            account_id = str(node.account_id or "").strip()
            if not account_id:
                return None
            account_ids.add(account_id)
        if len(account_ids) != 1:
            return None

        snapshot = self.repo.load_gorelay_active_account_snapshot(next(iter(account_ids)))
        if not snapshot:
            return None
        quota = snapshot.source_status.get("quota") if isinstance(snapshot.source_status, dict) else None
        if not isinstance(quota, dict):
            return None

        upload = self._safe_positive_int(quota.get("traffic_used"))
        total = self._safe_positive_int(quota.get("traffic_enable"))
        expire = self._safe_positive_int(quota.get("expire"))
        if upload == 0 and total == 0 and expire == 0:
            return None
        return f"upload={upload}; download=0; total={total}; expire={expire}"

    @staticmethod
    def _normalize_strategy_preset(value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in DEVICE_STRATEGY_PRESETS else DEVICE_STRATEGY_PRESET_BALANCED

    def _device_strategy_preset_for_token(self, token: str) -> str:
        gorelay_sub = self.gorelay_service.get_subscription_by_token(token)
        if gorelay_sub:
            profile = self.gorelay_service._resolve_profile(gorelay_sub.account_id, gorelay_sub.device_key)
            if profile:
                return self._normalize_strategy_preset(profile.strategy_preset)
            return DEVICE_STRATEGY_PRESET_BALANCED
        return DEVICE_STRATEGY_PRESET_BALANCED

    @staticmethod
    def _pin_group_mode_map(catalog_bindings: list[ServiceCatalogEntry], pin_groups: list[dict[str, object]]) -> dict[str, str]:
        known = {
            str(item.get("group_name") or "").strip(): str(item.get("mode") or "")
            for item in pin_groups
            if str(item.get("group_name") or "").strip()
        }
        for item in catalog_bindings:
            group_name = str(item.catalog_group or "").strip()
            if group_name and group_name not in known:
                known[group_name] = BUSINESS_GROUP_MODE_STANDARD
        return known

    @staticmethod
    def _effective_contract_for_category(
        category_name: str,
        *,
        category_by_name: dict[str, object],
        binding_by_name: dict[str, ServiceCatalogEntry],
        pin_group_modes: dict[str, str],
    ) -> str:
        category = category_by_name.get(category_name)
        binding = binding_by_name.get(category_name)
        if category is not None and getattr(category, "assigned_group", "") == CONTRACT_DIRECT.upper():
            current_directness = "DIRECT"
        elif category is not None and getattr(category, "override_active", False):
            current_directness = "PROXY"
        elif category is not None and (
            getattr(category, "system_default_group", "") == "DIRECT"
            or getattr(category, "system_directness", "") == "DIRECT"
        ):
            current_directness = "DIRECT"
        else:
            current_directness = "PROXY"
        catalog_group = str(binding.catalog_group or "") if binding else ""
        group_mode = pin_group_modes.get(catalog_group, BUSINESS_GROUP_MODE_STANDARD)
        return effective_contract_id(
            stored_contract_id=binding.contract_id if binding else "",
            catalog_group_mode=group_mode,
            current_directness=current_directness,
        )

    def _contract_business_groups(
        self,
        contracts: list[RouteContract],
        catalog_bindings: list[ServiceCatalogEntry],
        *,
        category_by_name: dict[str, object],
        pin_group_modes: dict[str, str],
    ) -> list[BusinessGroup]:
        binding_by_name = {item.category_name: item for item in catalog_bindings}
        categories_by_contract: dict[str, list[str]] = {}
        for item in catalog_bindings:
            contract_id = self._effective_contract_for_category(
                item.category_name,
                category_by_name=category_by_name,
                binding_by_name=binding_by_name,
                pin_group_modes=pin_group_modes,
            )
            if not contract_id:
                continue
            categories_by_contract.setdefault(contract_id, []).append(item.category_name)
        groups: list[BusinessGroup] = []
        for contract in sorted(contracts, key=lambda item: (item.sort_order, item.display_name, item.id)):
            pool_names: list[str] = []
            for pool_name in [*contract.primary_pools, *contract.fallback_pools]:
                legacy_group = contract_legacy_group(pool_name)
                if legacy_group and legacy_group not in pool_names:
                    pool_names.append(legacy_group)
            groups.append(
                BusinessGroup(
                    name=contract.display_name,
                    sort_order=contract.sort_order,
                    category_names=sorted(categories_by_contract.get(contract.id, [])),
                    pool_names=pool_names,
                    mode=(
                        BUSINESS_GROUP_MODE_AD_BLOCK
                        if normalize_route_action(getattr(contract, "routing_action", "proxy")) == ROUTE_ACTION_REJECT
                        else BUSINESS_GROUP_MODE_STANDARD
                    ),
                    created_by_system=True,
                )
            )
        return groups

    @staticmethod
    def _catalog_contract_sets(
        catalog_bindings: list[ServiceCatalogEntry],
    ) -> dict[str, set[str]]:
        catalog_contracts: dict[str, set[str]] = {}
        for item in catalog_bindings:
            group_name = str(item.catalog_group or "").strip()
            if not group_name or not item.contract_id:
                continue
            catalog_contracts.setdefault(group_name, set()).add(item.contract_id)
        return catalog_contracts

    def _resolve_runtime_contract_entry(
        self,
        entry: dict[str, object],
        *,
        catalog_contracts_by_group: dict[str, set[str]],
        scenario_id: str = "",
    ) -> tuple[str, str, bool, str]:
        contract_id = normalize_contract_id(entry.get("contract_id"))
        legacy_group = str(entry.get("business_group", "") or "").strip()
        warning = ""
        if not contract_id and legacy_group:
            contract_id = normalize_contract_id(legacy_group)
        if not contract_id and legacy_group:
            resolved = catalog_contracts_by_group.get(legacy_group, set())
            if len(resolved) == 1:
                contract_id = next(iter(resolved))
            elif len(resolved) > 1:
                warning = "needs_rebind"
            else:
                warning = "needs_rebind"
        enabled = bool(entry.get("enabled", True))
        if warning == "needs_rebind":
            enabled = False
        display_name = (
            scenario_contract_display_name(self.repo, scenario_id, contract_id)
            if contract_id
            else legacy_group
        )
        return contract_id, display_name, enabled, warning

    def _merge_export_rule_lines(self, lines: list[str]) -> tuple[list[str], int, int]:
        merged: list[str] = []
        seen_keys: set[object] = set()
        cidr_autofixed_count = 0
        dropped_invalid_count = 0
        for line in lines:
            normalized_line, autofixed = self.rule_catalog.normalize_output_rule_line(line)
            if not normalized_line:
                dropped_invalid_count += 1
                continue
            if autofixed:
                cidr_autofixed_count += 1
            identity_key = self.rule_catalog.rule_identity_key(normalized_line)
            dedupe_key: object = identity_key if identity_key is not None else normalized_line
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            merged.append(normalized_line)
        return merged, cidr_autofixed_count, dropped_invalid_count

    @staticmethod
    def _target_contract_id_for_rule_target(target: str) -> str:
        normalized = str(target or "").strip()
        if normalized == QUALITY_REJECT:
            return ROUTE_REJECT_ACTION
        if normalized == "DIRECT":
            return ROUTE_DIRECT_ACTION
        return normalize_contract_id(normalized)

    def _rule_entry_from_line(
        self,
        raw_line: str,
        *,
        source_kind: str,
        category_name: str = "",
        platform_scope: str = "any",
    ) -> PolicyRuleEntry | None:
        normalized_line, _ = self.rule_catalog.normalize_output_rule_line(raw_line)
        if not normalized_line:
            return None
        parts = [item.strip() for item in normalized_line.split(",")]
        if len(parts) < 3:
            return None
        target_contract_id = self._target_contract_id_for_rule_target(parts[2])
        if not target_contract_id:
            return None
        return PolicyRuleEntry(
            target_contract_id=target_contract_id,
            rule_type=parts[0].upper(),
            value=parts[1],
            extras=[item for item in parts[3:] if item],
            source_kind=source_kind,
            category_name=category_name,
            platform_scope=platform_scope,
        )

    def _merge_policy_rule_entries(
        self,
        entries: list[PolicyRuleEntry],
        *,
        contracts: list[RouteContract] | None = None,
    ) -> tuple[list[PolicyRuleEntry], list[RenderWarning], int]:
        policy_context = PolicyIR(
            nodes=[],
            pools={},
            business_groups=[],
            rule_lines=[],
            default_group_name="",
            contracts=list(contracts or []),
            metadata={"contracts_explicit": contracts is not None},
        )
        return merge_policy_rule_entries(entries, policy_ir=policy_context)

    async def _build_policy_rule_entries(
        self,
        *,
        categories: list[RuleCategory] | None = None,
        custom_rules: list[object] | None = None,
        target_resolver=None,
        contracts: list[RouteContract] | None = None,
    ) -> tuple[list[PolicyRuleEntry], list[RenderWarning]]:
        entries: list[PolicyRuleEntry] = []
        warnings: list[RenderWarning] = []
        scoped_categories = list(categories) if categories is not None else self.rule_catalog.list_categories()
        scoped_custom_rules = (
            list(custom_rules)
            if custom_rules is not None
            else self.repo.list_custom_rules()
        )

        for line in self._clash_direct_rule_lines():
            entry = self._rule_entry_from_line(line, source_kind="system")
            if entry:
                entries.append(entry)

        for custom_rule in scoped_custom_rules:
            if str(getattr(custom_rule, "category_name", "") or ""):
                continue
            explicit_target = (
                custom_rule.resolved_target_contract_id()
                if hasattr(custom_rule, "resolved_target_contract_id")
                else ""
            )
            entry = self._rule_entry_from_line(
                custom_rule.to_line(target_group=explicit_target) if explicit_target else custom_rule.to_line(),
                source_kind="custom",
                category_name=custom_rule.category_name,
            )
            if entry:
                entries.append(entry)

        if categories is None and custom_rules is None:
            for item in await self.rule_catalog.get_targeted_rule_entries(target_resolver=target_resolver):
                entry = self._rule_entry_from_line(
                    str(item.get("line") or ""),
                    source_kind=str(item.get("source_kind") or "catalog"),
                    category_name=str(item.get("category_name") or ""),
                )
                if entry:
                    entries.append(entry)
            merged_entries, merge_warnings, merge_dropped_invalid_count = self._merge_policy_rule_entries(
                entries,
                contracts=contracts,
            )
            warnings.extend(merge_warnings)
            if merge_dropped_invalid_count:
                warnings.append(
                    RenderWarning(
                        code="invalid-rule-dropped",
                        message=f"{merge_dropped_invalid_count} invalid rule lines were dropped during compilation",
                        target="rule-compiler",
                        severity="warning",
                    )
                )
            return merged_entries, warnings

        seen: set[tuple[str, str]] = set()
        compiler_dropped_invalid_count = 0
        cidr_autofixed_count = 0
        for item in scoped_categories:
            resolved_target = (
                str(target_resolver(item)).strip()
                if callable(target_resolver)
                else ""
            )
            if not resolved_target:
                continue
            for custom_rule in scoped_custom_rules:
                if str(getattr(custom_rule, "category_name", "") or "") != item.name:
                    continue
                targeted_custom = custom_rule.to_line(target_group=resolved_target)
                normalized_custom, autofixed = self.rule_catalog.normalize_output_rule_line(targeted_custom)
                if not normalized_custom:
                    compiler_dropped_invalid_count += 1
                    continue
                if autofixed:
                    cidr_autofixed_count += 1
                identity_key = self.rule_catalog.rule_identity_key(normalized_custom)
                dedupe_key = (item.name, identity_key if identity_key is not None else normalized_custom)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                entry = self._rule_entry_from_line(
                    normalized_custom,
                    source_kind="custom",
                    category_name=item.name,
                )
                if entry:
                    entries.append(entry)

            if item.category_type == "manual":
                continue

            cached = await self.rule_catalog.get_category_raw_rules(item.name)
            for line in cached or []:
                targeted = self.rule_catalog._retarget_rule(line, resolved_target)
                normalized_targeted, autofixed = self.rule_catalog.normalize_output_rule_line(targeted)
                if not normalized_targeted:
                    compiler_dropped_invalid_count += 1
                    continue
                if autofixed:
                    cidr_autofixed_count += 1
                identity_key = self.rule_catalog.rule_identity_key(normalized_targeted)
                dedupe_key = (item.name, identity_key if identity_key is not None else normalized_targeted)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                entry = self._rule_entry_from_line(
                    normalized_targeted,
                    source_kind="catalog",
                    category_name=item.name,
                )
                if entry:
                    entries.append(entry)

        merged_entries, merge_warnings, merge_dropped_invalid_count = self._merge_policy_rule_entries(
            entries,
            contracts=contracts,
        )
        warnings.extend(merge_warnings)
        if cidr_autofixed_count:
            warnings.append(
                RenderWarning(
                    code="cidr-autofixed",
                    message=f"{cidr_autofixed_count} CIDR rule lines were normalized during compilation",
                    target="rule-compiler",
                    severity="warning",
                )
            )
        total_dropped_invalid_count = compiler_dropped_invalid_count + merge_dropped_invalid_count
        if total_dropped_invalid_count:
            warnings.append(
                RenderWarning(
                    code="invalid-rule-dropped",
                    message=f"{total_dropped_invalid_count} invalid rule lines were dropped during compilation",
                    target="rule-compiler",
                    severity="warning",
                )
            )
        return merged_entries, warnings

    @staticmethod
    def _clash_direct_rule_lines() -> list[str]:
        return [
            "DOMAIN-SUFFIX,heiyu.space,DIRECT",
            "DOMAIN-SUFFIX,lazycat.cloud,DIRECT",
            "DOMAIN-SUFFIX,lazycatmicroserver.com,DIRECT",
            "IP-CIDR,6.6.6.6/32,DIRECT,no-resolve",
            "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve",
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
            "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
            "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
            "IP-CIDR6,::1/128,DIRECT,no-resolve",
            "IP-CIDR6,2000::6666/128,DIRECT,no-resolve",
            "IP-CIDR6,fc00::/7,DIRECT,no-resolve",
            "IP-CIDR6,fe80::/10,DIRECT,no-resolve",
            "IP-CIDR6,ff00::/8,DIRECT,no-resolve",
        ]

    def _load_process_rules(
        self,
        catalog_bindings: list[ServiceCatalogEntry],
        *,
        raw_entries: list[dict[str, object]] | None = None,
        scenario_id: str = "",
    ) -> list[ProcessRuleTemplate]:
        raw = raw_entries if raw_entries is not None else self.repo.get_runtime_setting(RUNTIME_KEY_SURGE_PROCESS_RULES)
        if not isinstance(raw, list):
            return []
        catalog_contracts_by_group = self._catalog_contract_sets(catalog_bindings)
        items: list[ProcessRuleTemplate] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            contract_id, display_name, enabled, warning = self._resolve_runtime_contract_entry(
                entry,
                catalog_contracts_by_group=catalog_contracts_by_group,
                scenario_id=scenario_id,
            )
            items.append(
                ProcessRuleTemplate(
                    id=str(entry.get("id", "") or ""),
                    contract_id=contract_id,
                    contract_display_name=display_name,
                    match_type=str(entry.get("match_type", "") or "PROCESS-NAME").strip().upper(),
                    value=str(entry.get("value", "") or "").strip(),
                    sort_order=int(entry.get("sort_order", 0) or 0),
                    enabled=enabled,
                    migration_warning=warning,
                )
            )
        return [item for item in items if item.value and (item.contract_id or item.migration_warning)]

    def _load_external_proxy_programs(
        self,
        catalog_bindings: list[ServiceCatalogEntry],
        *,
        raw_entries: list[dict[str, object]] | None = None,
        scenario_id: str = "",
    ) -> list[ExternalProxyProgramTemplate]:
        raw = (
            raw_entries
            if raw_entries is not None
            else self.repo.get_runtime_setting(RUNTIME_KEY_SURGE_EXTERNAL_PROXY_PROGRAMS)
        )
        if not isinstance(raw, list):
            return []
        catalog_contracts_by_group = self._catalog_contract_sets(catalog_bindings)
        items: list[ExternalProxyProgramTemplate] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            args = entry.get("args")
            contract_id, display_name, enabled, warning = self._resolve_runtime_contract_entry(
                entry,
                catalog_contracts_by_group=catalog_contracts_by_group,
                scenario_id=scenario_id,
            )
            items.append(
                ExternalProxyProgramTemplate(
                    id=str(entry.get("id", "") or ""),
                    contract_id=contract_id,
                    contract_display_name=display_name,
                    program_path=str(entry.get("program_path", "") or "").strip(),
                    args=[str(item).strip() for item in args] if isinstance(args, list) else [],
                    local_port=int(entry.get("local_port", 0) or 0),
                    name=str(entry.get("name", "") or "").strip(),
                    sort_order=int(entry.get("sort_order", 0) or 0),
                    enabled=enabled,
                    migration_warning=warning,
                )
            )
        return [
            item
            for item in items
            if (item.contract_id or item.migration_warning)
            and item.program_path
            and int(item.local_port or 0) > 0
        ]

    @staticmethod
    def _is_renderable_process_rule(item: ProcessRuleTemplate) -> bool:
        return bool(item.enabled and item.contract_id and item.value)

    @staticmethod
    def _is_renderable_external_proxy_program(item: ExternalProxyProgramTemplate) -> bool:
        return bool(item.enabled and item.contract_id and item.program_path and int(item.local_port or 0) > 0)

    @classmethod
    def _summarize_surge_mac_overlay(
        cls,
        process_rules: list[ProcessRuleTemplate],
        external_proxy_programs: list[ExternalProxyProgramTemplate],
    ) -> OverlayStatus:
        renderable_process_rule_count = sum(1 for item in process_rules if cls._is_renderable_process_rule(item))
        renderable_external_proxy_program_count = sum(
            1 for item in external_proxy_programs if cls._is_renderable_external_proxy_program(item)
        )
        has_needs_rebind = any(item.needs_rebind for item in [*process_rules, *external_proxy_programs])
        if has_needs_rebind:
            reason_code = "needs_rebind"
            reason = (
                "Overlay templates require contract rebinding before they can render. "
                "Open Advanced settings and fix the needs_rebind items."
            )
            return OverlayStatus(
                available=False,
                reason_code=reason_code,
                reason=reason,
                renderable_process_rule_count=renderable_process_rule_count,
                renderable_external_proxy_program_count=renderable_external_proxy_program_count,
            )
        available = bool(renderable_process_rule_count or renderable_external_proxy_program_count)
        if available:
            return OverlayStatus(
                available=True,
                renderable_process_rule_count=renderable_process_rule_count,
                renderable_external_proxy_program_count=renderable_external_proxy_program_count,
            )
        if not process_rules and not external_proxy_programs:
            reason_code = "missing_templates"
            reason = (
                "Overlay is intentionally empty until at least one Surge Process Rule "
                "or External Proxy Program is configured."
            )
        else:
            reason_code = "all_templates_disabled"
            reason = (
                "Overlay templates exist but none are enabled. Enable at least one Surge "
                "Process Rule or External Proxy Program in Advanced settings."
            )
        return OverlayStatus(
            available=False,
            reason_code=reason_code,
            reason=reason,
            renderable_process_rule_count=renderable_process_rule_count,
            renderable_external_proxy_program_count=renderable_external_proxy_program_count,
        )

    def get_surge_mac_overlay_status(self, *, scenario_id: str = "") -> OverlayStatus:
        safe_scenario_id = str(scenario_id or "").strip()
        if safe_scenario_id:
            catalog_bindings = self.repo.list_scenario_service_catalog_entries(safe_scenario_id)
            process_rules = self._load_process_rules(
                catalog_bindings,
                raw_entries=self.repo.list_scenario_process_rules(safe_scenario_id),
                scenario_id=safe_scenario_id,
            )
            external_proxy_programs = self._load_external_proxy_programs(
                catalog_bindings,
                raw_entries=self.repo.list_scenario_external_proxy_programs(safe_scenario_id),
                scenario_id=safe_scenario_id,
            )
        else:
            catalog_bindings = self.repo.list_service_catalog_entries()
            process_rules = self._load_process_rules(catalog_bindings)
            external_proxy_programs = self._load_external_proxy_programs(catalog_bindings)
        return self._summarize_surge_mac_overlay(process_rules, external_proxy_programs)

    def _device_revision_payload(
        self,
        token: str,
        nodes: list[NodeRecord],
        *,
        scenario_id: str = "",
    ) -> dict[str, object]:
        safe_scenario_id = str(scenario_id or "").strip()
        contracts = (
            scenario_route_contracts(self.repo, safe_scenario_id)
            if safe_scenario_id
            else self.repo.list_route_contracts()
        )
        if safe_scenario_id:
            catalog_bindings = self.repo.list_scenario_service_catalog_entries(safe_scenario_id)
            categories = self.repo.list_scenario_categories(safe_scenario_id)
            scenario = self.repo.get_scenario(safe_scenario_id)
            general_profile = (
                GeneralProfile(
                    id=str(scenario.id),
                    name=str(scenario.name),
                    settings=dict(scenario.settings),
                    is_system_default=False,
                    updated_at=scenario.updated_at,
                )
                if scenario
                else self.repo.get_default_general_profile()
            )
            custom_rules = self.repo.list_scenario_custom_rules(safe_scenario_id)
            pin_groups = self.repo.list_scenario_pin_groups(safe_scenario_id)
            process_rules_raw = self.repo.list_scenario_process_rules(safe_scenario_id)
            external_proxy_programs_raw = self.repo.list_scenario_external_proxy_programs(safe_scenario_id)
        else:
            catalog_bindings = self.repo.list_service_catalog_entries()
            categories = self.rule_catalog.list_categories()
            general_profile = self.repo.get_default_general_profile()
            custom_rules = self.repo.list_custom_rules()
            pin_groups = list(self.repo.list_pin_groups())
            process_rules_raw = self.repo.get_runtime_setting(RUNTIME_KEY_SURGE_PROCESS_RULES)
            external_proxy_programs_raw = self.repo.get_runtime_setting(
                RUNTIME_KEY_SURGE_EXTERNAL_PROXY_PROGRAMS
            )
        return {
            "token": str(token or "").strip(),
            "scenario_id": safe_scenario_id,
            "nodes": self._node_revision_payload(nodes),
            "device_strategy_preset": self._device_strategy_preset_for_token(token),
            "rule_categories": [
                {
                    "name": item.name,
                    "assigned_group": item.assigned_group,
                    "rule_count": int(item.rule_count),
                    "rule_source": item.rule_source,
                    "category_type": item.category_type,
                    "custom_rule_count": int(item.custom_rule_count),
                    "updated_at": item.updated_at,
                    "locked": bool(item.locked),
                    "system_directness": item.system_directness,
                    "system_default_group": item.system_default_group,
                    "system_default_locked": bool(item.system_default_locked),
                    "override_group": item.override_group,
                    "override_active": bool(item.override_active),
                    "directness_override": item.directness_override,
                    "lock_source": item.lock_source,
                }
                for item in sorted(categories, key=lambda entry: entry.name)
            ],
            "rule_cache": self.repo.list_rule_cache_summaries(),
            "custom_rules": [
                {
                    "id": item.id,
                    "rule_type": item.rule_type,
                    "value": item.value,
                    "target_contract_id": item.resolved_target_contract_id(),
                    "target_group": item.target_group,
                    "category_name": item.category_name,
                    "created_at": item.created_at,
                }
                for item in sorted(
                    custom_rules,
                    key=lambda entry: (entry.category_name, entry.rule_type, entry.value, entry.id),
                )
            ],
            "contracts": [item.to_dict() for item in sorted(contracts, key=lambda entry: entry.id)],
            "catalog_bindings": [
                item.to_dict()
                for item in sorted(
                    catalog_bindings,
                    key=lambda entry: (entry.sort_order, entry.category_name, entry.catalog_group),
                )
            ],
            "pin_groups": list(pin_groups),
            "general_profile": general_profile.to_dict() if general_profile else None,
            "process_rules_raw": process_rules_raw,
            "external_proxy_programs_raw": external_proxy_programs_raw,
        }

    def _device_revision(
        self,
        token: str,
        *,
        nodes: list[NodeRecord] | None = None,
        scenario_id: str = "",
    ) -> str | None:
        resolved_nodes = list(nodes) if nodes is not None else self.get_nodes_for_token(token)
        if resolved_nodes is None:
            return None
        return self._stable_json_hash(
            self._device_revision_payload(token, resolved_nodes, scenario_id=scenario_id)
        )

    async def _build_policy_ir_from_nodes(
        self,
        token: str,
        nodes: list[NodeRecord],
        *,
        scenario_id: str = "",
    ) -> PolicyIR:
        safe_scenario_id = str(scenario_id or "").strip()
        contracts = (
            scenario_route_contracts(self.repo, safe_scenario_id)
            if safe_scenario_id
            else self.repo.list_route_contracts()
        )
        contract_by_id = {item.id: item for item in contracts}
        catalog_bindings = (
            self.repo.list_scenario_service_catalog_entries(safe_scenario_id)
            if safe_scenario_id
            else self.repo.list_service_catalog_entries()
        )
        binding_map = {item.category_name: item for item in catalog_bindings}
        categories = (
            self.repo.list_scenario_categories(safe_scenario_id)
            if safe_scenario_id
            else self.rule_catalog.list_categories()
        )
        category_by_name = {item.name: item for item in categories}
        pin_group_modes = self._pin_group_mode_map(
            catalog_bindings,
            self.repo.list_scenario_pin_groups(safe_scenario_id)
            if safe_scenario_id
            else self.repo.list_pin_groups(),
        )
        rule_entries, compile_warnings = await self._build_policy_rule_entries(
            categories=categories if safe_scenario_id else None,
            custom_rules=(
                self.repo.list_scenario_custom_rules(safe_scenario_id)
                if safe_scenario_id
                else None
            ),
            target_resolver=lambda category: (
                self._effective_contract_for_category(
                    category.name,
                    category_by_name=category_by_name,
                    binding_by_name=binding_map,
                    pin_group_modes=pin_group_modes,
                )
            ),
            contracts=contracts,
        )
        merged_rules = [entry.to_line() for entry in rule_entries]
        business_groups = self._contract_business_groups(
            contracts,
            catalog_bindings,
            category_by_name=category_by_name,
            pin_group_modes=pin_group_modes,
        )
        process_rules = self._load_process_rules(
            catalog_bindings,
            raw_entries=(
                self.repo.list_scenario_process_rules(safe_scenario_id)
                if safe_scenario_id
                else None
            ),
            scenario_id=safe_scenario_id,
        )
        external_proxy_programs = self._load_external_proxy_programs(
            catalog_bindings,
            raw_entries=(
                self.repo.list_scenario_external_proxy_programs(safe_scenario_id)
                if safe_scenario_id
                else None
            ),
            scenario_id=safe_scenario_id,
        )
        scenario = self.repo.get_scenario(safe_scenario_id) if safe_scenario_id else None
        general_profile = (
            GeneralProfile(
                id=str(scenario.id),
                name=str(scenario.name),
                settings=dict(scenario.settings),
                is_system_default=False,
                updated_at=scenario.updated_at,
            )
            if scenario
            else self.repo.get_default_general_profile()
        )
        requested_default_contract_id = (
            scenario_default_contract_id(self.repo, safe_scenario_id)
            if safe_scenario_id
            else scenario_default_contract_id(self.repo, "scenario-default")
        )
        requested_default_contract_id = normalize_contract_id(requested_default_contract_id)
        default_contract_id = (
            requested_default_contract_id
            if requested_default_contract_id in contract_by_id
            else ""
        )
        ir = build_policy_ir(
            nodes,
            merged_rules,
            rule_entries=rule_entries,
            business_groups=business_groups,
            device_strategy_preset=self._device_strategy_preset_for_token(token),
            contracts=contracts,
            catalog_bindings=catalog_bindings,
            general_profile=general_profile,
            process_rules=process_rules,
            external_proxy_programs=external_proxy_programs,
            default_contract_id=default_contract_id,
        )
        ir.warnings.extend(compile_warnings)
        for item in [*process_rules, *external_proxy_programs]:
            if item.migration_warning == "needs_rebind":
                ir.warnings.append(
                    RenderWarning(
                        code="needs-rebind",
                        message=f"{item.business_group or 'Legacy group'} requires contract rebinding",
                        target=item.business_group or item.contract_id,
                    )
                )
        for binding in catalog_bindings:
            effective_contract = self._effective_contract_for_category(
                binding.category_name,
                category_by_name=category_by_name,
                binding_by_name=binding_map,
                pin_group_modes=pin_group_modes,
            )
            contract = contract_by_id.get(effective_contract)
            if (
                effective_contract
                and effective_contract not in {ROUTE_DIRECT_ACTION, ROUTE_REJECT_ACTION}
                and (not contract or not bool(contract.enabled))
            ):
                ir.warnings.append(
                    RenderWarning(
                        code="missing-contract" if not contract else "disabled-contract",
                        message=(
                            f"{binding.category_name} references missing contract {effective_contract}"
                            if not contract
                            else f"{binding.category_name} references disabled contract {contract.display_name}"
                        ),
                        target=binding.category_name,
                    )
                )
        if any(node.protocol.lower() == "vless" for node in nodes):
            ir.warnings.append(
                RenderWarning(
                    code="surge-vless-unsupported",
                    message="Surge renderer skips VLESS nodes in V1",
                    target="vless",
                )
            )
        return ir

    async def build_policy_ir_for_token(self, token: str, *, scenario_id: str = "") -> PolicyIR | None:
        entry = await self.get_cached_policy_ir(token, scenario_id=scenario_id)
        return entry.policy_ir if entry else None

    async def get_cached_policy_ir(self, token: str, *, scenario_id: str = "") -> PolicyIrCacheEntry | None:
        nodes = self.get_nodes_for_token(token)
        if nodes is None:
            self._policy_ir_cache.pop(f"{str(token or '').strip()}|{str(scenario_id or '').strip()}", None)
            return None

        safe_token = str(token or "").strip()
        safe_scenario_id = str(scenario_id or "").strip()
        revision = self._device_revision(safe_token, nodes=nodes, scenario_id=safe_scenario_id)
        if not revision:
            return None

        cache_key = f"{safe_token}|{safe_scenario_id}"
        cached = self._policy_ir_cache.get(cache_key)
        if cached and cached.revision == revision:
            return cached

        policy_ir = await self._build_policy_ir_from_nodes(
            safe_token,
            list(nodes),
            scenario_id=safe_scenario_id,
        )
        entry = PolicyIrCacheEntry(
            token=safe_token,
            revision=revision,
            built_at=self._now(),
            nodes=list(nodes),
            policy_ir=policy_ir,
        )
        self._policy_ir_cache[cache_key] = entry
        return entry

    def get_cached_artifact(
        self,
        *,
        kind: str,
        token: str,
        revision: str,
        variant: str = "",
    ) -> ArtifactCacheEntry | None:
        cache_key = self._cache_key(kind, token, variant)
        cached = self._artifact_cache.get(cache_key)
        if cached and cached.revision == revision:
            return cached
        return None

    def store_cached_artifact(
        self,
        *,
        kind: str,
        token: str,
        revision: str,
        value: object,
        variant: str = "",
    ) -> ArtifactCacheEntry:
        cache_key = self._cache_key(kind, token, variant)
        entry = ArtifactCacheEntry(
            kind=kind,
            cache_key=cache_key,
            revision=revision,
            built_at=self._now(),
            value=value,
        )
        self._artifact_cache[cache_key] = entry
        return entry

    async def build_surge_mac_overlay(
        self,
        token: str,
        managed_url: str,
        include_url: str,
        *,
        scenario_id: str = "",
    ) -> MacOverlayTemplate | None:
        ir = await self.build_policy_ir_for_token(token, scenario_id=scenario_id)
        if ir is None:
            return None
        overlay_status = self._summarize_surge_mac_overlay(ir.process_rules, ir.external_proxy_programs)
        return MacOverlayTemplate(
            managed_url=managed_url,
            include_url=include_url,
            process_rules=ir.process_rules,
            external_proxy_programs=ir.external_proxy_programs,
            overlay_status=overlay_status,
            warnings=list(ir.warnings),
        )

    async def get_rule_lines(self) -> list[str]:
        custom = [item.to_line() for item in self.repo.list_custom_rules(global_only=True)]
        category = await self.rule_catalog.get_assigned_rule_lines()
        merged, cidr_autofixed_count, dropped_invalid_count = self._merge_export_rule_lines(
            self._clash_direct_rule_lines() + custom + category
        )
        if cidr_autofixed_count or dropped_invalid_count:
            _logger.info(
                "rule export sanitization (global): cidr_autofixed=%s dropped_invalid=%s final_rules=%s",
                cidr_autofixed_count,
                dropped_invalid_count,
                len(merged),
            )
        return merged

    def touch_subscription(self, token: str, client_ip: str) -> None:
        now = self._now()
        if self.gorelay_service.get_subscription_by_token(token):
            self.gorelay_service.touch_subscription(token, client_ip)
            return
        self.repo.touch_device_subscription(token, now, client_ip)

    def touch_subscription_by_public_id(self, public_id: str, client_ip: str) -> None:
        now = self._now()
        if self.gorelay_service.get_subscription_by_public_id(public_id):
            self.gorelay_service.touch_subscription_by_public_id(public_id, client_ip)
            return
        self.repo.touch_device_subscription_by_public_id(public_id, now, client_ip)

    def public_runtime(self) -> dict[str, object]:
        return public_runtime(self.runtime.to_dict(), known_source_secrets(self.repo.list_standard_sources()))

    def status(self) -> dict[str, object]:
        gorelay_status = self.gorelay_service.status()
        runtime = self.public_runtime()
        last_error = runtime["last_error"]
        return {
            "runtime": runtime,
            "last_refresh_at": self.runtime.last_refresh_at,
            "last_error": last_error,
            "gorelay_source_count": len(self.gorelay_service.list_accounts()),
            "standard_source_count": len(self.repo.list_standard_sources()),
            "device_count": len(self.repo.list_device_subscriptions()),
            "rule_category_count": len(self.repo.list_rule_categories()),
            "custom_rule_count": len(self.repo.list_custom_rules()),
            "gorelay_sources": len(self.gorelay_service.list_accounts()),
            "standard_sources": len(self.repo.list_standard_sources()),
            "devices": len(self.repo.list_device_subscriptions()),
            "rule_categories": len(self.repo.list_rule_categories()),
            "custom_rules": len(self.repo.list_custom_rules()),
            "features": {
                "directness_review": True,
            },
            **gorelay_status,
        }
