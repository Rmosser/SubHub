from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from app.config import Settings
from app.models import (
    DEVICE_STRATEGY_PRESET_BALANCED,
    DEVICE_STRATEGY_PRESETS,
    CollectedOutbound,
    CollectedRule,
    GoRelayAccount,
    GoRelayAccountSnapshot,
    GoRelayAccountSnapshotPayload,
    GoRelayDeviceProfile,
    GoRelayDeviceSubscription,
    GoRelayDomainBinding,
    GoRelayDomainImportHistory,
    NodeRecord,
    QUALITY_CHAIN_HOME,
    RelayAccount,
)
from app.services.collectors import GoRelayApiCollector
from app.services.device_grouper import build_device_key, extract_device_group
from app.services.error_diagnostics import error_detail
from app.services.domain_binding_service import (
    binding_key,
    normalize_entry_key,
    normalize_entry_name,
    normalize_ip_version,
    normalize_isp,
    parse_customer_reply,
    parse_entry_multiplier_hints,
)
from app.services.normalize import resolve_gorelay_isp
from app.services.runtime_observability import (
    NullRuntimeTaskMonitor,
    RuntimeAlertService,
    RuntimeTaskMonitor,
)
from app.services.node_naming import (
    decorate_high_quality_node_name,
    format_gorelay_node_name,
    resolve_multiplier,
    resolve_quality_group,
)
from app.storage.base import Repo

_MATERIALIZABLE_RULE_STATUSES = {"ready", "pending_domain"}
_SPECIFIC_ISPS = ("ct", "cu", "cm")
_BRACKETED_HOST_PORT_RE = re.compile(r"^\[(.+)\]:(\d{2,5})$")
_logger = logging.getLogger("app.gorelay_service")


@dataclass
class GorelayRuntime:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_refresh_at: str | None = None
    last_error: str | None = None
    last_refresh_status: str = "unknown"
    last_refresh_attempted_count: int = 0
    last_refresh_succeeded_count: int = 0
    last_refresh_failed_count: int = 0
    account_status: dict[str, dict[str, object]] = field(default_factory=dict)
    active_snapshot_by_account: dict[str, str] = field(default_factory=dict)
    pending_domain_count_by_account: dict[str, int] = field(default_factory=dict)


class GorelayService:
    _DOMAIN_IMPORT_HISTORY_KEEP = 200

    def __init__(
        self,
        settings: Settings,
        repo: Repo,
        runtime_monitor: RuntimeTaskMonitor | None = None,
        alerts: RuntimeAlertService | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.collector = GoRelayApiCollector(settings)
        self.runtime = GorelayRuntime()
        self._background_task: asyncio.Task[None] | None = None
        self.runtime_monitor = runtime_monitor or NullRuntimeTaskMonitor()
        self.alerts = alerts
        self._progress_callback: Callable[[dict[str, object]], None] | None = None

    def set_progress_callback(
        self,
        callback: Callable[[dict[str, object]], None] | None,
    ) -> None:
        """Publish completed child work to an owning hub refresh, if any."""
        self._progress_callback = callback

    def _report_progress(self, details: dict[str, object]) -> None:
        callback = self._progress_callback
        if callback is not None:
            try:
                callback(dict(details))
            except Exception:
                # Progress is observability only; a monitor failure must not
                # change the result of the GoRelay refresh itself.
                _logger.exception("GoRelay progress callback failed")

    async def _acquire_runtime_lock_with_progress(self) -> None:
        """Wait for the GoRelay runtime lock without going silent.

        A Hub refresh can legitimately queue behind a healthy resident or
        management GoRelay operation.  The lock waiter is real progress, but
        only the Hub invocation that installed the callback's context may
        consume that progress.  Direct GoRelay callers therefore cannot
        refresh an unrelated Hub heartbeat.
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
                await asyncio.wait_for(self.runtime.lock.acquire(), timeout=interval)
                return
            except asyncio.TimeoutError:
                self._report_progress(
                    {
                        "phase": "waiting_for_runtime_lock",
                        "dependency_lock": "gorelay_runtime",
                    }
                )

    async def ensure_started(self) -> None:
        if self._background_task and not self._background_task.done():
            return
        self.runtime_monitor.register("gorelay.refresh_loop", required=True)
        self._update_runtime_from_repo()
        repair_result = self._repair_accounts_with_resolvable_pending_bindings()
        if repair_result["errors"]:
            self.runtime.last_error = "; ".join(repair_result["errors"])
        self._background_task = asyncio.create_task(self._refresh_loop())
        self.runtime_monitor.watch("gorelay.refresh_loop", self._background_task)
        self.runtime_monitor.startup_success("gorelay.refresh_loop")

    async def shutdown(self) -> None:
        if self._background_task and not self._background_task.done():
            self.runtime_monitor.expect_stop("gorelay.refresh_loop")
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
        self._background_task = None
        self.runtime_monitor.stopped("gorelay.refresh_loop")

    async def _refresh_loop(self) -> None:
        interval = max(self.settings.refresh_interval_minutes, 5) * 60
        while True:
            await self._sleep_with_heartbeat(interval)
            try:
                self.runtime_monitor.heartbeat(
                    "gorelay.refresh_loop",
                    details={"phase": "refreshing"},
                )
                await self.refresh(force=True)
                self.runtime_monitor.success(
                    "gorelay.refresh_loop",
                    details={"phase": "refresh_complete"},
                )
            except Exception as exc:
                detail = error_detail(exc, "scheduled_gorelay_refresh", uuid4().hex)
                self.runtime.last_error = detail["message"]
                _logger.error("scheduled GoRelay refresh failed: %s", detail)
                self.runtime_monitor.failure(
                    "gorelay.refresh_loop",
                    "scheduled GoRelay refresh failed",
                    details=detail,
                )

    async def _sleep_with_heartbeat(self, seconds: int) -> None:
        remaining = max(0, int(seconds))
        interval = max(int(getattr(self.settings, "runtime_heartbeat_interval_seconds", 30)), 5)
        while remaining > 0:
            delay = min(remaining, interval)
            await asyncio.sleep(delay)
            remaining -= delay
            if remaining > 0:
                self.runtime_monitor.heartbeat(
                    "gorelay.refresh_loop",
                    details={"phase": "sleeping", "remaining_seconds": remaining},
                )

    def _selector_config(self, account: GoRelayAccount) -> dict[str, object]:
        try:
            loaded = json.loads(account.selectors_json or "{}")
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _entry_multiplier_overrides(self, account_id: str) -> dict[str, str]:
        output: dict[str, str] = {}
        for item in self.repo.list_gorelay_entry_multiplier_overrides(account_id):
            key = normalize_entry_key(item.entry_key)
            value = str(item.multiplier).strip()
            if key and value:
                output[key] = value
        return output

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

    def list_accounts(self) -> list[GoRelayAccount]:
        return self.repo.list_gorelay_accounts()

    def get_account(self, account_id: str) -> GoRelayAccount | None:
        return self.repo.get_gorelay_account(account_id)

    def resolve_proxy_credentials(self, account_id: str, device_key: str) -> tuple[str, str]:
        account = self.get_account(account_id)
        if not account:
            return "", ""
        return self._resolve_credentials(account, device_key)

    def save_account(self, account: GoRelayAccount) -> None:
        self.repo.save_gorelay_account(account)

    def delete_account(self, account_id: str) -> None:
        self.repo.delete_gorelay_account(account_id)
        self._update_runtime_from_repo()

    def _resolve_profile(self, account_id: str, device_key: str) -> GoRelayDeviceProfile | None:
        for item in self.repo.list_gorelay_device_profiles(account_id):
            if item.device_key == device_key:
                return item
        return None

    def _resolve_credentials(self, account: GoRelayAccount, device_key: str) -> tuple[str, str]:
        profile = self._resolve_profile(account.id, device_key)
        username = account.proxy_username_default
        password = account.proxy_password_default
        if profile:
            if profile.proxy_username_override:
                username = profile.proxy_username_override
            if profile.proxy_password_override:
                password = profile.proxy_password_override
        return username.strip(), password.strip()

    def _apply_credentials_to_nodes(
        self,
        account: GoRelayAccount,
        device_key: str,
        nodes: list[NodeRecord],
    ) -> list[NodeRecord]:
        username, password = self._resolve_credentials(account, device_key)
        output: list[NodeRecord] = []
        for node in nodes:
            output.append(
                NodeRecord(
                    name=node.name,
                    host=node.host,
                    port=node.port,
                    protocol=node.protocol,
                    username=node.username or username,
                    password=node.password or password,
                    quality_group=node.quality_group,
                    source_id=node.source_id,
                    source_type=node.source_type,
                    account_id=node.account_id,
                    device_key=node.device_key,
                    device_name=node.device_name,
                    multiplier=node.multiplier,
                    source_rule_id=node.source_rule_id,
                    source_entry_name=node.source_entry_name,
                    source_entry_tag=node.source_entry_tag,
                    source_isp=node.source_isp,
                    source_ip_version=node.source_ip_version,
                    raw=dict(node.raw),
                )
            )
        return output

    def get_all_active_nodes(self) -> list[NodeRecord]:
        output: list[NodeRecord] = []
        for account in self.list_accounts():
            if not account.enabled:
                continue
            snapshot = self.repo.load_gorelay_active_account_snapshot(account.id)
            if not snapshot:
                continue
            for device_key, nodes in snapshot.device_nodes.items():
                output.extend(self._apply_credentials_to_nodes(account, device_key, nodes))
        return output

    def _sync_device_entities(self, account: GoRelayAccount, device_names: dict[str, str]) -> dict[str, int]:
        profiles = {p.device_key: p for p in self.repo.list_gorelay_device_profiles(account.id)}
        subs = {
            s.device_key: s
            for s in self.repo.list_gorelay_device_subscriptions(account.id, include_disabled=True)
        }
        stale_profiles = 0
        stale_subscriptions = 0

        for key, name in device_names.items():
            profile = profiles.get(key)
            if profile:
                changed = False
                if profile.device_name != name:
                    profile.device_name = name
                    changed = True
                if not profile.enabled:
                    profile.enabled = True
                    changed = True
                if changed:
                    self.repo.upsert_gorelay_device_profile(profile)
            else:
                self.repo.upsert_gorelay_device_profile(
                    GoRelayDeviceProfile(
                        account_id=account.id,
                        device_key=key,
                        device_name=name,
                        enabled=True,
                    )
                )

            sub = subs.get(key)
            if sub:
                changed = False
                if sub.device_name != name:
                    sub.device_name = name
                    changed = True
                if not sub.enabled:
                    sub.enabled = True
                    changed = True
                if changed:
                    self.repo.upsert_gorelay_device_subscription(sub)
            else:
                self.repo.upsert_gorelay_device_subscription(
                    GoRelayDeviceSubscription(
                        id=uuid4().hex,
                        account_id=account.id,
                        device_key=key,
                        device_name=name,
                        token=secrets.token_urlsafe(24),
                        enabled=True,
                    )
                )

        for profile in profiles.values():
            if profile.device_key in device_names:
                continue
            if profile.enabled:
                profile.enabled = False
                stale_profiles += 1
                self.repo.upsert_gorelay_device_profile(profile)

        for sub in subs.values():
            if sub.device_key in device_names:
                continue
            if sub.enabled:
                sub.enabled = False
                stale_subscriptions += 1
                self.repo.upsert_gorelay_device_subscription(sub)

        return {
            "stale_subscription_disabled": stale_subscriptions,
            "stale_profile_marked": stale_profiles,
        }

    def _approved_binding_host(
        self,
        account_id: str,
        entry_name: str,
        isp: str,
        ip_version: str,
        bindings: dict[str, GoRelayDomainBinding],
    ) -> str | None:
        key = binding_key(account_id, entry_name, isp, ip_version)
        item = bindings.get(key)
        if item and item.status == "approved":
            host = str(item.host_value or "").strip()
            if host:
                return host
        return None

    @staticmethod
    def _is_materializable_rule_status(status: object) -> bool:
        return str(status or "").strip().lower() in _MATERIALIZABLE_RULE_STATUSES

    @staticmethod
    def _node_materialization_key(
        *,
        device_key: str,
        entry_name: str,
        isp: str,
        ip_version: str,
        host: str,
        port: int,
    ) -> str:
        return (
            f"{device_key}|{normalize_entry_name(entry_name)}|{normalize_isp(isp)}|"
            f"{normalize_ip_version(ip_version)}|{str(host or '').strip()}:{int(port)}"
        ).lower()

    @staticmethod
    def _effective_rule_isp(rule: CollectedRule) -> str:
        return resolve_gorelay_isp(rule.isp, rule.entry_name)

    def _resolve_rule_targets(
        self,
        rule: CollectedRule,
        bindings: dict[str, GoRelayDomainBinding],
    ) -> list[tuple[str, str, str]]:
        rule_isp = self._effective_rule_isp(rule)
        rule_ip_version = normalize_ip_version(rule.ip_version)

        host = str(rule.host or "").strip()
        if host:
            return [(host, rule_isp, rule_ip_version)]

        if rule_isp == "other":
            split_targets: list[tuple[str, str, str]] = []
            for specific_isp in _SPECIFIC_ISPS:
                specific_host = self._approved_binding_host(
                    account_id=rule.account_id,
                    entry_name=rule.entry_name,
                    isp=specific_isp,
                    ip_version=rule_ip_version,
                    bindings=bindings,
                )
                if specific_host:
                    split_targets.append((specific_host, specific_isp, rule_ip_version))
            if split_targets:
                return split_targets

        exact_host = self._approved_binding_host(
            account_id=rule.account_id,
            entry_name=rule.entry_name,
            isp=rule_isp,
            ip_version=rule_ip_version,
            bindings=bindings,
        )
        if exact_host:
            return [(exact_host, rule_isp, rule_ip_version)]

        fallback_host = self._approved_binding_host(
            account_id=rule.account_id,
            entry_name=rule.entry_name,
            isp="other",
            ip_version=rule_ip_version,
            bindings=bindings,
        )
        if fallback_host:
            return [(fallback_host, rule_isp, rule_ip_version)]
        return []

    def _materialize_chain_home_nodes(
        self,
        account: GoRelayAccount,
        outbounds: list[CollectedOutbound],
        *,
        device_nodes: dict[str, list[NodeRecord]],
        device_names: dict[str, str],
        dedupe: dict[str, set[str]],
    ) -> None:
        for outbound in outbounds:
            device_name = outbound.device_name or extract_device_group(outbound.line_name)[0]
            device_key = build_device_key(device_name)
            device_names[device_key] = device_name
            device_nodes.setdefault(device_key, [])
            dedupe.setdefault(device_key, set())

            multiplier = str(outbound.multiplier or "").strip()
            for target in outbound.targets:
                host, port = self._parse_host_port(target)
                if not host or port <= 0:
                    continue
                key = f"{device_key}|chain_home|{host}:{port}".lower()
                if key in dedupe[device_key]:
                    continue

                label_suffix = f" {multiplier}x" if multiplier else ""
                node = NodeRecord(
                    name=f"{outbound.outbound_group_name or '链式家宽'}{label_suffix}".strip(),
                    host=host,
                    port=port,
                    protocol="socks5",
                    username="",
                    password="",
                    quality_group=QUALITY_CHAIN_HOME,
                    source_id=account.id,
                    source_type="gorelay_chain_home",
                    account_id=account.id,
                    device_key=device_key,
                    device_name=device_name,
                    multiplier=multiplier,
                    source_rule_id=outbound.rule_id,
                    source_entry_name=outbound.outbound_group_name,
                    raw={
                        **dict(outbound.raw),
                        "chain_home": True,
                    },
                )
                device_nodes[device_key].append(node)
                dedupe[device_key].add(key)

    def _materialize_nodes(
        self,
        account: GoRelayAccount,
        rules: list[CollectedRule],
        outbounds: list[CollectedOutbound] | None = None,
    ) -> tuple[dict[str, list[NodeRecord]], dict[str, str], list[dict[str, object]]]:
        binding_items = self.repo.list_gorelay_domain_bindings(account.id)
        bindings = {
            binding_key(item.account_id, item.entry_name, item.isp, item.ip_version): item
            for item in binding_items
        }
        overrides = self._entry_multiplier_overrides(account.id)

        device_nodes: dict[str, list[NodeRecord]] = {}
        device_names: dict[str, str] = {}
        pending_map: dict[str, dict[str, object]] = {}
        dedupe: dict[str, set[str]] = {}

        for rule in rules:
            if not self._is_materializable_rule_status(rule.status):
                continue
            device_name = rule.device_name or extract_device_group(rule.line_name)[0]
            device_key = build_device_key(device_name)
            device_names[device_key] = device_name
            normalized_entry = normalize_entry_name(rule.entry_name)

            targets = self._resolve_rule_targets(rule, bindings)
            if not targets:
                rule_isp = self._effective_rule_isp(rule)
                pending_key = (
                    f"{normalized_entry}|{rule_isp}|{normalize_ip_version(rule.ip_version)}"
                )
                pending = pending_map.setdefault(
                    pending_key,
                    {
                        "entry_name": normalized_entry,
                        "isp": rule_isp,
                        "ip_version": normalize_ip_version(rule.ip_version),
                        "ports": set(),
                    },
                )
                pending["ports"].add(int(rule.port))
                continue

            device_nodes.setdefault(device_key, [])
            dedupe.setdefault(device_key, set())

            manual_multiplier = overrides.get(normalize_entry_key(normalized_entry))
            auto_multiplier = resolve_multiplier(
                entry_name=rule.entry_name,
                line_name=rule.line_name,
                raw=rule.raw,
            )
            multiplier = manual_multiplier or auto_multiplier
            quality_group = resolve_quality_group(multiplier)

            for host, resolved_isp, resolved_ip_version in targets:
                key = self._node_materialization_key(
                    device_key=device_key,
                    entry_name=normalized_entry,
                    isp=resolved_isp,
                    ip_version=resolved_ip_version,
                    host=host,
                    port=int(rule.port),
                )
                if key in dedupe[device_key]:
                    continue

                node_name = decorate_high_quality_node_name(
                    format_gorelay_node_name(
                        entry_name=normalized_entry,
                        isp=resolved_isp,
                        multiplier=multiplier,
                    ),
                    quality_group,
                )
                node = NodeRecord(
                    name=node_name,
                    host=host,
                    port=int(rule.port),
                    protocol="socks5",
                    username="",
                    password="",
                    quality_group=quality_group,
                    source_id=account.id,
                    source_type="gorelay",
                    account_id=account.id,
                    device_key=device_key,
                    device_name=device_name,
                    multiplier=multiplier,
                    source_rule_id=rule.rule_id,
                    source_entry_name=normalized_entry,
                    source_isp=resolved_isp,
                    source_ip_version=resolved_ip_version,
                    raw={**dict(rule.raw), "resolved_isp": resolved_isp},
                )
                device_nodes[device_key].append(node)
                dedupe[device_key].add(key)

        self._materialize_chain_home_nodes(
            account,
            list(outbounds or []),
            device_nodes=device_nodes,
            device_names=device_names,
            dedupe=dedupe,
        )

        pending_bindings: list[dict[str, object]] = []
        for item in pending_map.values():
            pending_bindings.append(
                {
                    "entry_name": item["entry_name"],
                    "isp": item["isp"],
                    "ip_version": item["ip_version"],
                    "ports": sorted(item["ports"]),
                }
            )
        pending_bindings.sort(key=lambda x: (str(x["entry_name"]), str(x["isp"]), str(x["ip_version"])))
        return device_nodes, device_names, pending_bindings

    def _new_snapshot_id(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{stamp}-{uuid4().hex[:8]}"

    def _save_snapshot(
        self,
        account: GoRelayAccount,
        collected_rules: list[CollectedRule],
        collected_outbounds: list[CollectedOutbound],
        device_nodes: dict[str, list[NodeRecord]],
        device_names: dict[str, str],
        pending_bindings: list[dict[str, object]],
        source_status: dict[str, object],
    ) -> GoRelayAccountSnapshot:
        node_count = sum(len(items) for items in device_nodes.values())
        snapshot = GoRelayAccountSnapshot(
            account_id=account.id,
            snapshot_id=self._new_snapshot_id(),
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            node_count=node_count,
            device_count=len(device_nodes),
            status="success" if node_count > 0 else "empty",
            error=None,
        )
        payload = GoRelayAccountSnapshotPayload(
            account=snapshot,
            collected_rules=collected_rules,
            device_nodes=device_nodes,
            device_names=device_names,
            pending_bindings=pending_bindings,
            source_status=source_status,
            collected_outbounds=collected_outbounds,
        )
        self.repo.save_gorelay_account_snapshot(payload)
        current_active = self.repo.load_gorelay_active_snapshot_id(account.id)
        if node_count > 0 or not current_active:
            self.repo.save_gorelay_active_snapshot_id(account.id, snapshot.snapshot_id)
        self.repo.prune_gorelay_account_snapshots(account.id, self.settings.max_snapshots_per_account)
        return snapshot

    async def crawl_account(self, account_id: str) -> dict[str, object]:
        account = self.get_account(account_id)
        if not account:
            raise ValueError("account not found")
        if not account.enabled:
            raise ValueError("account is disabled")

        relay = RelayAccount.from_account(account)
        selectors = self._selector_config(account)
        rules, outbounds, source_status = await self.collector.collect(relay, selectors)

        device_nodes, device_names, pending_bindings = self._materialize_nodes(account, rules, outbounds)
        stale_result = self._sync_device_entities(account, device_names)
        snapshot = self._save_snapshot(
            account,
            rules,
            outbounds,
            device_nodes,
            device_names,
            pending_bindings,
            source_status,
        )
        self._update_runtime_from_repo()
        return {
            "ok": True,
            "account_id": account.id,
            "snapshot_id": snapshot.snapshot_id,
            "node_count": snapshot.node_count,
            "device_count": snapshot.device_count,
            "pending_domain_count": len(pending_bindings),
            "stale_subscription_disabled": stale_result["stale_subscription_disabled"],
            "stale_profile_marked": stale_result["stale_profile_marked"],
            "source_status": source_status,
        }

    async def crawl_all_accounts(self, *, refresh_id: str | None = None) -> list[dict[str, object]]:
        refresh_id = refresh_id or uuid4().hex
        accounts = [item for item in self.list_accounts() if item.enabled]
        if not accounts:
            self._update_runtime_from_repo()
            return []

        semaphore = asyncio.Semaphore(max(self.settings.account_crawl_parallelism, 1))

        async def _run(account: GoRelayAccount) -> dict[str, object]:
            async with semaphore:
                try:
                    result = await self.crawl_account(account.id)
                    # Account crawls can be deliberately parallel and a full
                    # refresh may legitimately outlive the stale threshold.
                    # Each completed account is real progress; publish it so
                    # readiness does not mistake a long refresh for a dead
                    # resident task.
                    self.runtime_monitor.heartbeat(
                        "gorelay.refresh_loop",
                        details={
                            "phase": "refresh_progress",
                            "unit": "account",
                            "account_id": account.id,
                            "ok": True,
                        },
                    )
                    self._report_progress(
                        {
                            "phase": "refresh_progress",
                            "unit": "account",
                            "account_id": account.id,
                            "ok": True,
                        }
                    )
                    return result
                except Exception as exc:
                    diagnostic = error_detail(exc, "gorelay_account_crawl", refresh_id)
                    _logger.error("GoRelay account crawl failed account_id=%s: %s", account.id, diagnostic)
                    latest = self.repo.load_gorelay_latest_account_snapshot(account.id)
                    node_count = latest.account.node_count if latest else 0
                    device_count = latest.account.device_count if latest else 0
                    snapshot = GoRelayAccountSnapshot(
                        account_id=account.id,
                        snapshot_id=self._new_snapshot_id(),
                        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        node_count=node_count,
                        device_count=device_count,
                        status="failed",
                        error=diagnostic["message"],
                    )
                    payload = GoRelayAccountSnapshotPayload(
                        account=snapshot,
                        collected_rules=latest.collected_rules if latest else [],
                        device_nodes=latest.device_nodes if latest else {},
                        device_names=latest.device_names if latest else {},
                        pending_bindings=latest.pending_bindings if latest else [],
                        source_status={
                            "collector": "failed",
                            "error": diagnostic["message"],
                            "error_detail": diagnostic,
                        },
                        collected_outbounds=latest.collected_outbounds if latest else [],
                    )
                    self.repo.save_gorelay_account_snapshot(payload)
                    self.repo.prune_gorelay_account_snapshots(
                        account.id, self.settings.max_snapshots_per_account
                    )
                    result = {
                        "ok": False,
                        "account_id": account.id,
                        "error": diagnostic["message"],
                        "error_detail": diagnostic,
                        "refresh_id": refresh_id,
                    }
                    self.runtime_monitor.heartbeat(
                        "gorelay.refresh_loop",
                        details={
                            "phase": "refresh_progress",
                            "unit": "account",
                            "account_id": account.id,
                            "ok": False,
                        },
                    )
                    self._report_progress(
                        {
                            "phase": "refresh_progress",
                            "unit": "account",
                            "account_id": account.id,
                            "ok": False,
                        }
                    )
                    return result

        results = await asyncio.gather(*[_run(item) for item in accounts])
        self._update_runtime_from_repo()
        return results

    async def refresh(self, force: bool = False) -> GorelayRuntime:
        if not force:
            return self.runtime

        await self._acquire_runtime_lock_with_progress()
        try:
            refresh_id = uuid4().hex
            results = await self.crawl_all_accounts(refresh_id=refresh_id)
            errors = [item.get("error", "") for item in results if item.get("ok") is False]
            self.runtime.last_error = "; ".join([item for item in errors if item]) or None
            self.runtime.last_refresh_attempted_count = len(results)
            self.runtime.last_refresh_failed_count = len(errors)
            self.runtime.last_refresh_succeeded_count = len(results) - len(errors)
            if errors and self.runtime.last_refresh_succeeded_count:
                self.runtime.last_refresh_status = "partial"
            elif errors:
                self.runtime.last_refresh_status = "failed"
            else:
                self.runtime.last_refresh_status = "ok"
            self.runtime.last_refresh_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return self.runtime
        finally:
            self.runtime.lock.release()

    def refresh_summary(self) -> dict[str, object]:
        """Return a stable aggregate outcome for the latest account refresh."""

        failed_count = int(self.runtime.last_refresh_failed_count)
        attempted_count = int(self.runtime.last_refresh_attempted_count)
        succeeded_count = int(self.runtime.last_refresh_succeeded_count)
        if self.runtime.last_error and failed_count == 0:
            failed_count = 1
            attempted_count = max(attempted_count, 1)
        status = self.runtime.last_refresh_status
        if status == "unknown":
            status = "ok" if not self.runtime.last_error else "failed"
        return {
            "ok": failed_count == 0 and not self.runtime.last_error,
            "partial": bool(failed_count and succeeded_count),
            "status": status,
            "attempted_count": attempted_count,
            "succeeded_count": succeeded_count,
            "failed_count": failed_count,
            "errors": [self.runtime.last_error] if self.runtime.last_error else [],
        }

    def _append_domain_import_history(self, item: GoRelayDomainImportHistory) -> None:
        items = self.repo.list_gorelay_domain_import_histories(limit=5000)
        items.append(item)

        account_items = [entry for entry in items if entry.account_id == item.account_id]
        account_items.sort(key=lambda entry: entry.created_at, reverse=True)
        keep_ids = {entry.id for entry in account_items[: self._DOMAIN_IMPORT_HISTORY_KEEP]}

        trimmed = [
            entry
            for entry in items
            if entry.account_id != item.account_id or entry.id in keep_ids
        ]
        self.repo.save_gorelay_domain_import_histories(trimmed)

    def list_pending_bindings(self, account_id: str) -> list[dict[str, object]]:
        latest = self.repo.load_gorelay_latest_account_snapshot(account_id)
        if not latest:
            return []
        return list(latest.pending_bindings)

    @staticmethod
    def _usage_device_items(agg: dict[str, object]) -> list[dict[str, object]]:
        devices: dict[str, dict[str, object]] = agg["devices"]  # type: ignore[assignment]
        items = []
        for dev in devices.values():
            items.append(
                {
                    "device_key": dev["device_key"],
                    "device_name": dev["device_name"],
                    "ports": sorted({int(x) for x in dev["ports"]}),  # type: ignore[arg-type]
                    "rule_count": int(dev.get("rule_count", 0)),
                }
            )
        items.sort(key=lambda x: str(x["device_name"]))
        return items

    def list_entry_usage(self, account_id: str) -> list[dict[str, object]]:
        latest = self.repo.load_gorelay_latest_account_snapshot(account_id)
        if not latest:
            return []
        account = self.get_account(account_id)
        if not account:
            return []

        bindings = [
            item
            for item in self.repo.list_gorelay_domain_bindings(account_id)
            if item.status == "approved"
        ]
        binding_by_key = {
            binding_key(item.account_id, item.entry_name, item.isp, item.ip_version): item
            for item in bindings
        }

        aggregates: dict[str, dict[str, object]] = {}
        for rule in latest.collected_rules:
            entry_name = normalize_entry_name(rule.entry_name)
            isp = self._effective_rule_isp(rule)
            ip_version = normalize_ip_version(rule.ip_version)
            key = binding_key(account_id, entry_name, isp, ip_version)

            agg = aggregates.get(key)
            if not agg:
                agg = {
                    "entry_name": entry_name,
                    "isp": isp,
                    "ip_version": ip_version,
                    "ports": set(),
                    "devices": {},
                    "hosts": set(),
                }
                aggregates[key] = agg

            agg["ports"].add(int(rule.port))

            device_name = rule.device_name or extract_device_group(rule.line_name)[0]
            device_key = build_device_key(device_name)
            devices: dict[str, dict[str, object]] = agg["devices"]  # type: ignore[assignment]
            dev = devices.get(device_key)
            if not dev:
                dev = {
                    "device_key": device_key,
                    "device_name": device_name,
                    "ports": set(),
                    "rule_count": 0,
                }
                devices[device_key] = dev
            dev["ports"].add(int(rule.port))
            dev["rule_count"] = int(dev.get("rule_count", 0)) + 1

            if rule.host:
                agg["hosts"].add(rule.host)

        output: list[dict[str, object]] = []
        for _, agg in aggregates.items():
            entry_name = str(agg["entry_name"])
            isp = str(agg["isp"])
            ip_version = str(agg["ip_version"])
            device_items = self._usage_device_items(agg)
            ports = sorted({int(x) for x in agg["ports"]})  # type: ignore[arg-type]
            hosts = sorted({str(x) for x in agg["hosts"] if x})

            if isp == "other" and not hosts:
                split_items: list[dict[str, object]] = []
                for specific_isp in _SPECIFIC_ISPS:
                    bind = binding_by_key.get(
                        binding_key(account_id, entry_name, specific_isp, ip_version)
                    )
                    if not bind or not str(bind.host_value or "").strip():
                        continue
                    split_items.append(
                        {
                            "entry_name": entry_name,
                            "isp": specific_isp,
                            "ip_version": ip_version,
                            "ports": ports,
                            "devices": device_items,
                            "host_value": bind.host_value,
                            "binding_source": "exact",
                            "resolved": True,
                            "binding_id": bind.id,
                        }
                    )
                if split_items:
                    output.extend(split_items)
                    continue

            item_key = binding_key(account_id, entry_name, isp, ip_version)
            bind = binding_by_key.get(item_key)
            binding_source = "exact"
            if not bind and isp != "other":
                bind = binding_by_key.get(binding_key(account_id, entry_name, "other", ip_version))
                if bind:
                    binding_source = "fallback_other"

            host_value = bind.host_value if bind else (hosts[0] if hosts else "")
            resolved = bool(host_value)

            output.append(
                {
                    "entry_name": entry_name,
                    "isp": isp,
                    "ip_version": ip_version,
                    "ports": ports,
                    "devices": device_items,
                    "host_value": host_value,
                    "binding_source": binding_source if bind else "",
                    "resolved": resolved,
                    "binding_id": bind.id if bind else "",
                }
            )

        output.sort(key=lambda x: (str(x["entry_name"]), str(x["isp"]), str(x["ip_version"])))
        return output

    def _snapshot_has_missing_resolved_pending_nodes(
        self,
        account: GoRelayAccount,
        latest: GoRelayAccountSnapshotPayload,
    ) -> bool:
        binding_items = [
            item
            for item in self.repo.list_gorelay_domain_bindings(account.id)
            if item.status == "approved" and str(item.host_value or "").strip()
        ]
        if not binding_items:
            return False

        bindings = {
            binding_key(item.account_id, item.entry_name, item.isp, item.ip_version): item
            for item in binding_items
        }
        existing_keys: set[str] = set()
        for device_key, nodes in latest.device_nodes.items():
            for node in nodes:
                existing_keys.add(
                    self._node_materialization_key(
                        device_key=str(device_key),
                        entry_name=str(node.source_entry_name or ""),
                        isp=str(node.source_isp or "other"),
                        ip_version=str(node.source_ip_version or "unknown"),
                        host=str(node.host or ""),
                        port=int(node.port),
                    )
                )

        for rule in latest.collected_rules:
            if str(rule.status).strip().lower() != "pending_domain":
                continue
            targets = self._resolve_rule_targets(rule, bindings)
            if not targets:
                continue
            device_name = rule.device_name or extract_device_group(rule.line_name)[0]
            device_key = build_device_key(device_name)
            normalized_entry = normalize_entry_name(rule.entry_name)
            for host, resolved_isp, resolved_ip_version in targets:
                key = self._node_materialization_key(
                    device_key=device_key,
                    entry_name=normalized_entry,
                    isp=resolved_isp,
                    ip_version=resolved_ip_version,
                    host=host,
                    port=int(rule.port),
                )
                if key not in existing_keys:
                    return True
        return False

    def _repair_accounts_with_resolvable_pending_bindings(self) -> dict[str, object]:
        repaired: list[str] = []
        errors: list[str] = []
        for account in self.list_accounts():
            if not account.enabled:
                continue
            latest = self.repo.load_gorelay_latest_account_snapshot(account.id)
            if not latest or not latest.collected_rules:
                continue
            try:
                if not self._snapshot_has_missing_resolved_pending_nodes(account, latest):
                    continue
                result = self.rebuild_account_from_latest_rules(account.id)
                if result.get("ok"):
                    repaired.append(account.id)
            except Exception as exc:
                errors.append(f"{account.id}: {exc}")
        return {"repaired_count": len(repaired), "accounts": repaired, "errors": errors}

    def account_status(self, account_id: str) -> dict[str, object]:
        account = self.get_account(account_id)
        if not account:
            raise ValueError("account not found")
        latest = self.repo.load_gorelay_latest_account_snapshot(account_id)
        active = self.repo.load_gorelay_active_snapshot_id(account_id) or ""
        active_payload = (
            self.repo.load_gorelay_account_snapshot(account_id, active)
            if active
            else None
        )
        status_payload = active_payload or latest
        pending = self.list_pending_bindings(account_id)
        return {
            "ok": True,
            "account_id": account_id,
            "name": account.name,
            "enabled": account.enabled,
            "active_snapshot_id": active,
            "latest_snapshot_id": latest.account.snapshot_id if latest else "",
            "latest_status": latest.account.status if latest else "empty",
            "latest_error": latest.account.error if latest else None,
            "latest_node_count": latest.account.node_count if latest else 0,
            "latest_device_count": latest.account.device_count if latest else 0,
            "pending_domain_count": len(pending),
            "source_status": status_payload.source_status if status_payload else {},
            # Legacy-compatible keys used by the original dashboard.
            "snapshot_id": status_payload.account.snapshot_id if status_payload else None,
            "created_at": status_payload.account.created_at if status_payload else None,
        }

    def list_account_snapshots(self, account_id: str) -> list[GoRelayAccountSnapshot]:
        return self.repo.list_gorelay_account_snapshots(account_id)

    def activate_snapshot(self, account_id: str, snapshot_id: str) -> None:
        payload = self.repo.load_gorelay_account_snapshot(account_id, snapshot_id)
        if not payload:
            raise ValueError("snapshot not found")
        self.repo.save_gorelay_active_snapshot_id(account_id, snapshot_id)
        self._update_runtime_from_repo()

    def list_account_device_views(
        self,
        account_id: str,
        include_stale: bool = False,
    ) -> list[dict[str, object]]:
        account = self.get_account(account_id)
        if not account:
            return []
        snapshot = self.repo.load_gorelay_active_account_snapshot(account_id)
        snapshot_names = snapshot.device_names if snapshot else {}
        profiles = {
            item.device_key: item
            for item in self.repo.list_gorelay_device_profiles(account_id)
        }
        subscriptions_by_key: dict[str, list[GoRelayDeviceSubscription]] = {}
        for item in self.repo.list_gorelay_device_subscriptions(account_id, include_disabled=True):
            subscriptions_by_key.setdefault(item.device_key, []).append(item)

        keys = set(snapshot_names.keys()) | set(profiles.keys()) | set(subscriptions_by_key.keys())
        items: list[dict[str, object]] = []
        for key in sorted(keys):
            is_stale = bool(snapshot and key not in snapshot_names)
            if is_stale and not include_stale:
                continue

            profile = profiles.get(key)
            sub_items = subscriptions_by_key.get(key, [])
            enabled_sub_items = [sub for sub in sub_items if sub.enabled]
            preferred_sub = enabled_sub_items[0] if enabled_sub_items else (sub_items[0] if sub_items else None)

            device_name = (
                (profile.device_name if profile else "")
                or snapshot_names.get(key, "")
                or (preferred_sub.device_name if preferred_sub else "")
                or key
            )
            device_nodes = list(snapshot.device_nodes.get(key, [])) if snapshot else []
            entry_names = sorted({node.source_entry_name for node in device_nodes if node.source_entry_name})

            public_id = enabled_sub_items[0].public_id if enabled_sub_items else ""
            subscription_id = enabled_sub_items[0].id if enabled_sub_items else (preferred_sub.id if preferred_sub else None)
            subscription_enabled = bool(enabled_sub_items)

            items.append(
                {
                    "device_key": key,
                    "device_name": device_name,
                    "node_count": len(device_nodes),
                    "entry_count": len(entry_names),
                    "entries": entry_names,
                    "proxy_username_override": profile.proxy_username_override if profile else "",
                    "proxy_password_override": profile.proxy_password_override if profile else "",
                    "strategy_preset": (
                        profile.strategy_preset if profile and profile.strategy_preset else DEVICE_STRATEGY_PRESET_BALANCED
                    ),
                    "profile_enabled": profile.enabled if profile else True,
                    "subscription_id": subscription_id,
                    "public_id": public_id,
                    "subscription_enabled": subscription_enabled,
                    "subscription_count": len(enabled_sub_items),
                    "is_stale": is_stale,
                    "preview": {
                        "clash": {
                            "available": bool(subscription_enabled and public_id),
                            "reason_text": (
                                ["ok"]
                                if (subscription_enabled and public_id)
                                else ["subscription disabled or subscription id missing"]
                            ),
                        },
                        "shadowrocket": {
                            "available": bool(subscription_enabled and public_id),
                            "reason_text": (
                                ["ok"]
                                if (subscription_enabled and public_id)
                                else ["subscription disabled or subscription id missing"]
                            ),
                        },
                        "surge": {
                            "available": bool(subscription_enabled and public_id),
                            "reason_text": (
                                ["ok"]
                                if (subscription_enabled and public_id)
                                else ["subscription disabled or subscription id missing"]
                            ),
                        },
                    },
                }
            )
        return items

    def update_account_proxy_credentials(
        self,
        account_id: str,
        username: str,
        password: str,
    ) -> GoRelayAccount:
        account = self.get_account(account_id)
        if not account:
            raise ValueError("account not found")
        account.proxy_username_default = username.strip()
        account.proxy_password_default = password.strip()
        self.repo.save_gorelay_account(account)
        return account

    def update_device_proxy_credentials(
        self,
        account_id: str,
        device_key: str,
        username: str,
        password: str,
    ) -> GoRelayDeviceProfile:
        account = self.get_account(account_id)
        if not account:
            raise ValueError("account not found")

        profile = self._resolve_profile(account_id, device_key)
        if not profile:
            profile = GoRelayDeviceProfile(
                account_id=account_id,
                device_key=device_key,
                device_name=device_key,
                enabled=True,
            )
        profile.proxy_username_override = username.strip()
        profile.proxy_password_override = password.strip()
        self.repo.upsert_gorelay_device_profile(profile)
        return profile

    def update_device_strategy_preset(
        self,
        account_id: str,
        device_key: str,
        strategy_preset: str,
    ) -> GoRelayDeviceProfile:
        account = self.get_account(account_id)
        if not account:
            raise ValueError("account not found")
        preset = str(strategy_preset or "").strip().lower()
        if preset not in DEVICE_STRATEGY_PRESETS:
            raise ValueError("invalid strategy_preset")

        profile = self._resolve_profile(account_id, device_key)
        if not profile:
            profile = GoRelayDeviceProfile(
                account_id=account_id,
                device_key=device_key,
                device_name=device_key,
                enabled=True,
            )
        profile.strategy_preset = preset
        self.repo.upsert_gorelay_device_profile(profile)
        return profile

    def update_domain_binding(
        self,
        account_id: str,
        binding_id: str,
        host_value: str,
        status: str,
    ) -> GoRelayDomainBinding:
        items = self.repo.list_gorelay_domain_bindings()
        target: GoRelayDomainBinding | None = None
        for item in items:
            if item.id == binding_id and item.account_id == account_id:
                target = item
                break
        if not target:
            raise ValueError("domain binding not found")
        target.host_value = host_value.strip()
        target.status = status.strip() or "approved"
        target.source = "manual_edit"
        target.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.repo.save_gorelay_domain_bindings(items)
        return target

    def list_domain_import_histories(self, account_id: str, limit: int = 50) -> list[GoRelayDomainImportHistory]:
        return self.repo.list_gorelay_domain_import_histories(account_id=account_id, limit=limit)

    async def delete_domain_import_history(self, account_id: str, history_id: str) -> dict[str, object]:
        account = self.get_account(account_id)
        if not account:
            raise ValueError("account not found")

        histories = self.repo.list_gorelay_domain_import_histories(account_id=account_id, limit=5000)
        target = next((item for item in histories if item.id == history_id), None)
        if not target:
            raise ValueError("domain import history not found")

        bindings = self.repo.list_gorelay_domain_bindings()
        binding_index: dict[str, GoRelayDomainBinding] = {}
        for item in bindings:
            if item.account_id != account_id:
                continue
            binding_index[binding_key(item.account_id, item.entry_name, item.isp, item.ip_version)] = item

        revoke_ids: set[str] = set()
        revoked = 0
        skipped_due_to_drift = 0
        for applied in target.applied_bindings:
            if not isinstance(applied, dict):
                continue
            entry_name = normalize_entry_name(str(applied.get("entry_name", "")))
            isp = normalize_isp(str(applied.get("isp", "")))
            ip_version = normalize_ip_version(str(applied.get("ip_version", "")))
            host_value = str(applied.get("host_value", "")).strip()
            updated_at = str(applied.get("updated_at", "")).strip()
            if not entry_name or not host_value:
                continue
            key = binding_key(account_id, entry_name, isp, ip_version)
            current = binding_index.get(key)
            if not current:
                skipped_due_to_drift += 1
                continue
            if (
                str(current.host_value).strip() == host_value
                and str(current.updated_at).strip() == updated_at
            ):
                revoke_ids.add(current.id)
                revoked += 1
            else:
                skipped_due_to_drift += 1

        if revoke_ids:
            bindings = [item for item in bindings if item.id not in revoke_ids]
            self.repo.save_gorelay_domain_bindings(bindings)

        deleted = self.repo.delete_gorelay_domain_import_history(account_id, history_id)
        if not deleted:
            raise ValueError("domain import history not found")

        latest = self.repo.load_gorelay_latest_account_snapshot(account_id)
        if latest and latest.collected_rules:
            rebuild = self.rebuild_account_from_latest_rules(account_id)
        else:
            rebuild = await self.crawl_account(account_id)

        return {
            "ok": True,
            "account_id": account_id,
            "history_id": history_id,
            "bindings_revoked": revoked,
            "bindings_skipped_drift": skipped_due_to_drift,
            "snapshot_id": str(rebuild.get("snapshot_id", "")),
            "node_count": int(rebuild.get("node_count", 0)),
            "device_count": int(rebuild.get("device_count", 0)),
            "pending_domain_count": int(rebuild.get("pending_domain_count", 0)),
            "stale_subscription_disabled": int(rebuild.get("stale_subscription_disabled", 0)),
            "stale_profile_marked": int(rebuild.get("stale_profile_marked", 0)),
        }

    async def import_domain_bindings_from_text(self, account_id: str, text: str) -> dict[str, object]:
        account = self.get_account(account_id)
        if not account:
            raise ValueError("account not found")

        parsed = parse_customer_reply(text)
        multiplier_hints = parse_entry_multiplier_hints(text)
        if not parsed and not multiplier_hints:
            raise ValueError("no valid domain bindings or multiplier hints parsed from reply text")

        existing = self.repo.list_gorelay_domain_bindings()
        changed = 0
        applied_bindings: list[dict[str, str]] = []
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for item in parsed:
            key = binding_key(account_id, item.entry_name, item.isp, item.ip_version)
            target = None
            for current in existing:
                current_key = binding_key(
                    current.account_id,
                    current.entry_name,
                    current.isp,
                    current.ip_version,
                )
                if current_key == key:
                    target = current
                    break
            if target:
                if target.host_value != item.host_value:
                    target.host_value = item.host_value
                    target.updated_at = now
                    target.status = "approved"
                    target.source = "manual_import"
                    applied_bindings.append(
                        {
                            "entry_name": normalize_entry_name(target.entry_name),
                            "isp": normalize_isp(target.isp),
                            "ip_version": normalize_ip_version(target.ip_version),
                            "host_value": target.host_value,
                            "updated_at": target.updated_at,
                        }
                    )
                    changed += 1
                continue
            created = GoRelayDomainBinding(
                id=uuid4().hex,
                account_id=account_id,
                entry_name=normalize_entry_name(item.entry_name),
                isp=normalize_isp(item.isp),
                ip_version=normalize_ip_version(item.ip_version),
                host_value=item.host_value,
                source="manual_import",
                status="approved",
                updated_at=now,
            )
            existing.append(created)
            applied_bindings.append(
                {
                    "entry_name": created.entry_name,
                    "isp": created.isp,
                    "ip_version": created.ip_version,
                    "host_value": created.host_value,
                    "updated_at": created.updated_at,
                }
            )
            changed += 1

        if parsed:
            self.repo.save_gorelay_domain_bindings(existing)
        multiplier_changed = self.repo.merge_gorelay_entry_multiplier_overrides(
            account_id,
            {
                normalize_entry_key(k): str(v).strip()
                for k, v in multiplier_hints.items()
                if normalize_entry_key(k) and str(v).strip()
            },
        )

        latest = self.repo.load_gorelay_latest_account_snapshot(account_id)
        if latest and latest.collected_rules:
            rebuild = self.rebuild_account_from_latest_rules(account_id)
            stale_result = {
                "stale_subscription_disabled": int(rebuild.get("stale_subscription_disabled", 0)),
                "stale_profile_marked": int(rebuild.get("stale_profile_marked", 0)),
            }
        else:
            await self.crawl_account(account_id)
            stale_result = {"stale_subscription_disabled": 0, "stale_profile_marked": 0}

        self._append_domain_import_history(
            GoRelayDomainImportHistory(
                id=uuid4().hex,
                account_id=account_id,
                raw_text=text,
                parsed_count=len(parsed),
                changed_count=changed,
                multiplier_hint_count=len(multiplier_hints),
                applied_bindings=applied_bindings,
                created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )
        )
        self._update_runtime_from_repo()
        return {
            "ok": True,
            "changed": changed,
            "parsed": len(parsed),
            "multiplier_hint_count": len(multiplier_hints),
            "multiplier_override_changed": multiplier_changed,
            "account_id": account_id,
            "stale_subscription_disabled": stale_result["stale_subscription_disabled"],
            "stale_profile_marked": stale_result["stale_profile_marked"],
        }

    async def import_entry_multipliers_from_text(self, account_id: str, text: str) -> dict[str, object]:
        account = self.get_account(account_id)
        if not account:
            raise ValueError("account not found")

        parsed = {
            normalize_entry_key(k): str(v).strip()
            for k, v in parse_entry_multiplier_hints(text).items()
            if normalize_entry_key(k) and str(v).strip()
        }
        if not parsed:
            raise ValueError("no valid multiplier entries parsed from text")

        replace_stats = self.repo.replace_gorelay_entry_multiplier_overrides(account_id, parsed)

        latest = self.repo.load_gorelay_latest_account_snapshot(account_id)
        if latest and latest.collected_rules:
            rebuild_result = self.rebuild_account_from_latest_rules(account_id)
        else:
            rebuild_result = await self.crawl_account(account_id)

        self._update_runtime_from_repo()
        return {
            "ok": True,
            "account_id": account_id,
            "parsed_count": len(parsed),
            "applied_count": replace_stats["applied_count"],
            "removed_count": replace_stats["removed_count"],
            "unchanged_count": replace_stats["unchanged_count"],
            "snapshot_id": rebuild_result.get("snapshot_id", ""),
            "node_count": int(rebuild_result.get("node_count", 0)),
            "device_count": int(rebuild_result.get("device_count", 0)),
            "pending_domain_count": int(rebuild_result.get("pending_domain_count", 0)),
            "stale_subscription_disabled": int(rebuild_result.get("stale_subscription_disabled", 0)),
            "stale_profile_marked": int(rebuild_result.get("stale_profile_marked", 0)),
        }

    def rebuild_account_from_latest_rules(self, account_id: str) -> dict[str, object]:
        account = self.get_account(account_id)
        if not account:
            raise ValueError("account not found")
        latest = self.repo.load_gorelay_latest_account_snapshot(account_id)
        if not latest or not latest.collected_rules:
            raise ValueError("no collected rules available for rebuild")

        device_nodes, device_names, pending_bindings = self._materialize_nodes(
            account, latest.collected_rules, latest.collected_outbounds
        )
        stale_result = self._sync_device_entities(account, device_names)
        snapshot = self._save_snapshot(
            account,
            latest.collected_rules,
            latest.collected_outbounds,
            device_nodes,
            device_names,
            pending_bindings,
            {"collector": "rebuild_from_latest_rules"},
        )
        self._update_runtime_from_repo()
        return {
            "ok": True,
            "snapshot_id": snapshot.snapshot_id,
            "node_count": snapshot.node_count,
            "device_count": snapshot.device_count,
            "pending_domain_count": len(pending_bindings),
            "stale_subscription_disabled": stale_result["stale_subscription_disabled"],
            "stale_profile_marked": stale_result["stale_profile_marked"],
        }

    def list_subscriptions(
        self,
        account_id: str | None = None,
        include_disabled: bool = False,
    ) -> list[GoRelayDeviceSubscription]:
        return self.repo.list_gorelay_device_subscriptions(
            account_id=account_id,
            include_disabled=include_disabled,
        )

    def disable_subscription(self, subscription_id: str) -> bool:
        return self.repo.disable_gorelay_device_subscription(subscription_id)

    def get_subscription_by_token(self, token: str) -> GoRelayDeviceSubscription | None:
        return self.repo.get_gorelay_device_subscription_by_token(token)

    def get_subscription_by_public_id(self, public_id: str) -> GoRelayDeviceSubscription | None:
        return self.repo.get_gorelay_device_subscription_by_public_id(public_id)

    def get_device_nodes_for_subscription(self, sub: GoRelayDeviceSubscription) -> list[NodeRecord]:
        account = self.get_account(sub.account_id)
        if not account or not account.enabled:
            return []
        snapshot = self.repo.load_gorelay_active_account_snapshot(account.id)
        if not snapshot:
            return []
        nodes = list(snapshot.device_nodes.get(sub.device_key, []))
        return self._apply_credentials_to_nodes(account, sub.device_key, nodes)

    def touch_subscription(self, token: str, client_ip: str) -> None:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.repo.touch_gorelay_device_subscription(token, now, client_ip)

    def touch_subscription_by_public_id(self, public_id: str, client_ip: str) -> None:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.repo.touch_gorelay_device_subscription_by_public_id(public_id, now, client_ip)

    def _update_runtime_from_repo(self) -> None:
        account_status: dict[str, dict[str, object]] = {}
        active_map: dict[str, str] = {}
        pending_count: dict[str, int] = {}
        for account in self.list_accounts():
            active_id = self.repo.load_gorelay_active_snapshot_id(account.id)
            active_map[account.id] = active_id or ""
            latest = self.repo.load_gorelay_latest_account_snapshot(account.id)
            if latest:
                account_status[account.id] = {
                    "name": account.name,
                    "status": latest.account.status,
                    "error": latest.account.error,
                    "snapshot_id": latest.account.snapshot_id,
                    "node_count": latest.account.node_count,
                    "device_count": latest.account.device_count,
                    "created_at": latest.account.created_at,
                }
                pending_count[account.id] = len(latest.pending_bindings)
            else:
                account_status[account.id] = {
                    "name": account.name,
                    "status": "empty",
                    "error": None,
                    "snapshot_id": "",
                    "node_count": 0,
                    "device_count": 0,
                    "created_at": None,
                }
                pending_count[account.id] = 0

        self.runtime.account_status = account_status
        self.runtime.active_snapshot_by_account = active_map
        self.runtime.pending_domain_count_by_account = pending_count

    def status(self) -> dict[str, object]:
        pending_total = sum(self.runtime.pending_domain_count_by_account.values())
        return {
            "last_gorelay_refresh_at": self.runtime.last_refresh_at,
            "gorelay_last_error": self.runtime.last_error,
            "gorelay_refresh_status": self.runtime.last_refresh_status,
            "gorelay_refresh_attempted_count": self.runtime.last_refresh_attempted_count,
            "gorelay_refresh_succeeded_count": self.runtime.last_refresh_succeeded_count,
            "gorelay_refresh_failed_count": self.runtime.last_refresh_failed_count,
            "pending_domain_total": pending_total,
            "snapshot_status_by_account": self.runtime.account_status,
            "active_snapshot_by_account": self.runtime.active_snapshot_by_account,
            "pending_domain_count_by_account": self.runtime.pending_domain_count_by_account,
        }
