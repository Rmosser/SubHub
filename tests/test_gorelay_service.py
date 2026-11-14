"""Tests for app.services.gorelay_service.GorelayService.

The service layer is tested by mocking the Repo and Collector, so no DB or
network I/O is required.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from app.config import Settings
from app.models import (
    CollectedRule,
    GoRelayAccount,
    GoRelayAccountSnapshot,
    GoRelayAccountSnapshotPayload,
    GoRelayDeviceProfile,
    GoRelayDeviceSubscription,
    GoRelayDomainBinding,
    GoRelayDomainImportHistory,
    GoRelayEntryMultiplierOverride,
    NodeRecord,
)
from app.services.gorelay_service import GorelayService


# ── Helpers ──────────────────────────────────────────────────────────────────

def _settings(**overrides: Any) -> Settings:
    defaults = dict(
        app_name="test",
        app_base_url="http://localhost",
        storage_root="/tmp/test",
        refresh_interval_minutes=30,
        request_timeout_seconds=10,
        verify_tls=False,
        github_api_base="https://127.0.0.1/invalid",
        github_raw_base="https://127.0.0.1/invalid",
        rule_catalog_refresh_hours=24,
        manage_api_require_login=False,
        max_snapshots_per_account=20,
        account_crawl_parallelism=2,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _account(**overrides: Any) -> GoRelayAccount:
    defaults = dict(
        id="acc1",
        name="TestAcct",
        login_url="https://example.com/api/v1/auth/login",
        gorelay_username="user1",
        gorelay_password="pass1",
        proxy_username_default="proxy_user",
        proxy_password_default="proxy_pass",
        selectors_json="{}",
        enabled=True,
    )
    defaults.update(overrides)
    return GoRelayAccount(**defaults)


def _rule(
    host: str = "relay.example.com",
    port: int = 10443,
    entry_name: str = "IPLC-JP",
    isp: str = "ct",
    ip_version: str = "ipv4",
    device_name: str = "TestDevice",
    status: str = "ready",
    **overrides: Any,
) -> CollectedRule:
    defaults = dict(
        account_id="acc1",
        rule_id="r1",
        device_name=device_name,
        line_name="TestDevice-「IPLC-JP」",
        entry_name=entry_name,
        isp=isp,
        ip_version=ip_version,
        port=port,
        host=host,
        status=status,
        raw={},
    )
    defaults.update(overrides)
    return CollectedRule(**defaults)


def _binding(
    account_id: str = "acc1",
    entry_name: str = "IPLC-JP",
    isp: str = "ct",
    ip_version: str = "ipv4",
    host_value: str = "bound.example.com",
    status: str = "approved",
) -> GoRelayDomainBinding:
    return GoRelayDomainBinding(
        id=uuid4().hex,
        account_id=account_id,
        entry_name=entry_name,
        isp=isp,
        ip_version=ip_version,
        host_value=host_value,
        source="manual_import",
        status=status,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


class FakeRepo:
    """In-memory fake that satisfies the Repo protocol for tests."""

    def __init__(self) -> None:
        self.accounts: dict[str, GoRelayAccount] = {}
        self.device_profiles: list[GoRelayDeviceProfile] = []
        self.device_subscriptions: list[GoRelayDeviceSubscription] = []
        self.domain_bindings: list[GoRelayDomainBinding] = []
        self.domain_import_histories: list[GoRelayDomainImportHistory] = []
        self.entry_multiplier_overrides: list[GoRelayEntryMultiplierOverride] = []
        self.snapshots: dict[str, list[GoRelayAccountSnapshotPayload]] = {}
        self.active_snapshot_ids: dict[str, str] = {}

    # Account methods
    def list_gorelay_accounts(self) -> list[GoRelayAccount]:
        return list(self.accounts.values())

    def get_gorelay_account(self, account_id: str) -> GoRelayAccount | None:
        return self.accounts.get(account_id)

    def save_gorelay_account(self, account: GoRelayAccount) -> None:
        self.accounts[account.id] = account

    def delete_gorelay_account(self, account_id: str) -> None:
        self.accounts.pop(account_id, None)

    # Device profiles
    def list_gorelay_device_profiles(self, account_id: str | None = None) -> list[GoRelayDeviceProfile]:
        if account_id is None:
            return list(self.device_profiles)
        return [p for p in self.device_profiles if p.account_id == account_id]

    def upsert_gorelay_device_profile(self, profile: GoRelayDeviceProfile) -> None:
        self.device_profiles = [
            p for p in self.device_profiles
            if not (p.account_id == profile.account_id and p.device_key == profile.device_key)
        ]
        self.device_profiles.append(profile)

    # Device subscriptions
    def list_gorelay_device_subscriptions(
        self, account_id: str | None = None, include_disabled: bool = True
    ) -> list[GoRelayDeviceSubscription]:
        result = self.device_subscriptions
        if account_id is not None:
            result = [s for s in result if s.account_id == account_id]
        if not include_disabled:
            result = [s for s in result if s.enabled]
        return result

    def upsert_gorelay_device_subscription(self, item: GoRelayDeviceSubscription) -> None:
        if not item.public_id:
            item.public_id = f"pub-{uuid4().hex[:12]}"
        self.device_subscriptions = [
            s for s in self.device_subscriptions
            if not (s.account_id == item.account_id and s.device_key == item.device_key)
        ]
        self.device_subscriptions.append(item)

    def get_gorelay_device_subscription_by_token(self, token: str) -> GoRelayDeviceSubscription | None:
        return next((s for s in self.device_subscriptions if s.token == token), None)

    def get_gorelay_device_subscription_by_public_id(self, public_id: str) -> GoRelayDeviceSubscription | None:
        return next((s for s in self.device_subscriptions if s.public_id == public_id), None)

    def disable_gorelay_device_subscription(self, subscription_id: str) -> bool:
        for s in self.device_subscriptions:
            if s.id == subscription_id:
                s.enabled = False
                return True
        return False

    def touch_gorelay_device_subscription(self, token: str, seen_at: str, seen_ip: str) -> None:
        pass

    def touch_gorelay_device_subscription_by_public_id(self, public_id: str, seen_at: str, seen_ip: str) -> None:
        pass

    # Domain bindings
    def list_gorelay_domain_bindings(self, account_id: str | None = None) -> list[GoRelayDomainBinding]:
        if account_id is None:
            return list(self.domain_bindings)
        return [b for b in self.domain_bindings if b.account_id == account_id]

    def save_gorelay_domain_bindings(self, bindings: list[GoRelayDomainBinding]) -> None:
        self.domain_bindings = list(bindings)

    def list_gorelay_domain_import_histories(
        self, account_id: str | None = None, limit: int = 50
    ) -> list[GoRelayDomainImportHistory]:
        result = self.domain_import_histories
        if account_id is not None:
            result = [h for h in result if h.account_id == account_id]
        return result[:limit]

    def save_gorelay_domain_import_histories(self, items: list[GoRelayDomainImportHistory]) -> None:
        self.domain_import_histories = list(items)

    def delete_gorelay_domain_import_history(self, account_id: str, history_id: str) -> bool:
        before = len(self.domain_import_histories)
        self.domain_import_histories = [
            h for h in self.domain_import_histories
            if not (h.account_id == account_id and h.id == history_id)
        ]
        return len(self.domain_import_histories) < before

    # Entry multiplier overrides
    def list_gorelay_entry_multiplier_overrides(self, account_id: str) -> list[GoRelayEntryMultiplierOverride]:
        return [o for o in self.entry_multiplier_overrides if o.account_id == account_id]

    def replace_gorelay_entry_multiplier_overrides(
        self, account_id: str, overrides: dict[str, str]
    ) -> dict[str, int]:
        self.entry_multiplier_overrides = [
            o for o in self.entry_multiplier_overrides if o.account_id != account_id
        ]
        for k, v in overrides.items():
            self.entry_multiplier_overrides.append(
                GoRelayEntryMultiplierOverride(account_id=account_id, entry_key=k, multiplier=v)
            )
        return {"applied_count": len(overrides), "removed_count": 0, "unchanged_count": 0}

    def merge_gorelay_entry_multiplier_overrides(
        self, account_id: str, overrides: dict[str, str]
    ) -> int:
        changed = 0
        existing = {o.entry_key: o for o in self.entry_multiplier_overrides if o.account_id == account_id}
        for k, v in overrides.items():
            if k in existing:
                if existing[k].multiplier != v:
                    existing[k].multiplier = v  # type: ignore[misc]
                    changed += 1
            else:
                self.entry_multiplier_overrides.append(
                    GoRelayEntryMultiplierOverride(account_id=account_id, entry_key=k, multiplier=v)
                )
                changed += 1
        return changed

    # Snapshots
    def save_gorelay_account_snapshot(self, payload: GoRelayAccountSnapshotPayload) -> None:
        self.snapshots.setdefault(payload.account.account_id, []).append(payload)

    def load_gorelay_account_snapshot(
        self, account_id: str, snapshot_id: str
    ) -> GoRelayAccountSnapshotPayload | None:
        for p in self.snapshots.get(account_id, []):
            if p.account.snapshot_id == snapshot_id:
                return p
        return None

    def load_gorelay_latest_account_snapshot(self, account_id: str) -> GoRelayAccountSnapshotPayload | None:
        items = self.snapshots.get(account_id, [])
        return items[-1] if items else None

    def load_gorelay_active_account_snapshot(self, account_id: str) -> GoRelayAccountSnapshotPayload | None:
        active_id = self.active_snapshot_ids.get(account_id)
        if not active_id:
            return None
        return self.load_gorelay_account_snapshot(account_id, active_id)

    def list_gorelay_account_snapshots(self, account_id: str) -> list[GoRelayAccountSnapshot]:
        return [p.account for p in self.snapshots.get(account_id, [])]

    def save_gorelay_active_snapshot_id(self, account_id: str, snapshot_id: str) -> None:
        self.active_snapshot_ids[account_id] = snapshot_id

    def load_gorelay_active_snapshot_id(self, account_id: str) -> str | None:
        return self.active_snapshot_ids.get(account_id)

    def prune_gorelay_account_snapshots(self, account_id: str, keep: int) -> None:
        items = self.snapshots.get(account_id, [])
        if len(items) > keep:
            self.snapshots[account_id] = items[-keep:]


def _service(repo: FakeRepo | None = None) -> tuple[GorelayService, FakeRepo]:
    repo = repo or FakeRepo()
    settings = _settings()
    svc = GorelayService(settings, repo)
    return svc, repo


# ── _materialize_nodes ───────────────────────────────────────────────────────


class TestMaterializeNodes:
    def test_ready_rules_produce_nodes(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        rules = [
            _rule(host="relay-ct.example.com", isp="ct"),
            _rule(host="relay-cu.example.com", isp="cu"),
        ]
        device_nodes, device_names, pending = svc._materialize_nodes(account, rules)

        assert len(device_nodes) >= 1
        all_nodes = [n for nodes in device_nodes.values() for n in nodes]
        assert len(all_nodes) == 2
        assert all(n.protocol == "socks5" for n in all_nodes)
        assert pending == []

    def test_pending_rules_produce_pending_bindings(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        rules = [_rule(host="", status="ready", isp="ct")]
        device_nodes, device_names, pending = svc._materialize_nodes(account, rules)

        all_nodes = [n for nodes in device_nodes.values() for n in nodes]
        assert all_nodes == []
        assert len(pending) >= 1
        assert pending[0]["isp"] == "ct"

    def test_mobile_entry_pending_rules_use_fallback_isp(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        rules = [_rule(host="", isp="other", entry_name="「Lv2」广东隧道「移动入口」", status="ready")]
        _, _, pending = svc._materialize_nodes(account, rules)

        assert len(pending) == 1
        assert pending[0]["isp"] == "cm"

    def test_binding_resolves_pending(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account
        repo.domain_bindings = [_binding(host_value="bound.example.com", isp="ct")]

        rules = [_rule(host="", status="ready", isp="ct")]
        device_nodes, device_names, pending = svc._materialize_nodes(account, rules)

        all_nodes = [n for nodes in device_nodes.values() for n in nodes]
        assert len(all_nodes) == 1
        assert all_nodes[0].host == "bound.example.com"
        assert pending == []

    def test_pending_domain_rules_with_binding_materialize_nodes(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account
        repo.domain_bindings = [_binding(host_value="bound.example.com", isp="ct")]

        rules = [_rule(host="", status="pending_domain", isp="ct")]
        device_nodes, _, pending = svc._materialize_nodes(account, rules)
        all_nodes = [n for nodes in device_nodes.values() for n in nodes]

        assert len(all_nodes) == 1
        assert all_nodes[0].host == "bound.example.com"
        assert pending == []

    def test_pending_domain_other_isp_splits_to_specific_bindings(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account
        repo.domain_bindings = [
            _binding(isp="ct", host_value="ct.example.com"),
            _binding(isp="cu", host_value="cu.example.com"),
        ]

        rules = [_rule(host="", isp="other", status="pending_domain")]
        device_nodes, _, pending = svc._materialize_nodes(account, rules)
        all_nodes = [n for nodes in device_nodes.values() for n in nodes]

        assert len(all_nodes) == 2
        assert {n.host for n in all_nodes} == {"ct.example.com", "cu.example.com"}
        assert pending == []

    def test_non_materializable_rules_skipped(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        rules = [_rule(host="relay.example.com", status="failed")]
        device_nodes, _, pending = svc._materialize_nodes(account, rules)
        all_nodes = [n for nodes in device_nodes.values() for n in nodes]
        assert all_nodes == []
        assert pending == []

    def test_deduplication(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        rules = [
            _rule(host="relay.example.com", isp="ct"),
            _rule(host="relay.example.com", isp="ct"),  # duplicate
        ]
        device_nodes, _, _ = svc._materialize_nodes(account, rules)
        all_nodes = [n for nodes in device_nodes.values() for n in nodes]
        assert len(all_nodes) == 1

    def test_multiplier_override(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account
        repo.entry_multiplier_overrides = [
            GoRelayEntryMultiplierOverride(account_id="acc1", entry_key="IPLC-JP", multiplier="5")
        ]

        rules = [_rule(host="relay.example.com")]
        device_nodes, _, _ = svc._materialize_nodes(account, rules)
        all_nodes = [n for nodes in device_nodes.values() for n in nodes]
        assert len(all_nodes) == 1
        assert all_nodes[0].multiplier == "5"
        assert all_nodes[0].name.startswith("🇺🇸 美国 · 电信 · 5x ·")

    def test_other_isp_splits_to_specific_bindings(self):
        """A rule with isp=other and no host should split into ct/cu/cm if bindings exist."""
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account
        repo.domain_bindings = [
            _binding(isp="ct", host_value="ct.example.com"),
            _binding(isp="cu", host_value="cu.example.com"),
        ]

        rules = [_rule(host="", isp="other", status="ready")]
        device_nodes, _, pending = svc._materialize_nodes(account, rules)
        all_nodes = [n for nodes in device_nodes.values() for n in nodes]
        assert len(all_nodes) == 2
        hosts = {n.host for n in all_nodes}
        assert "ct.example.com" in hosts
        assert "cu.example.com" in hosts

    def test_mobile_entry_hosted_rule_uses_fallback_isp_for_node_name(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        rules = [
            _rule(
                host="2409:8c54:1841:2008:0:1:0:1e5",
                ip_version="ipv6",
                isp="other",
                entry_name="「Lv2」广东隧道「移动入口」",
            )
        ]
        device_nodes, _, _ = svc._materialize_nodes(account, rules)
        all_nodes = [n for nodes in device_nodes.values() for n in nodes]

        assert len(all_nodes) == 1
        assert all_nodes[0].name.startswith("🇺🇸 美国 · 移动")
        assert all_nodes[0].source_isp == "cm"


# ── _resolve_rule_targets ────────────────────────────────────────────────────


class TestResolveRuleTargets:
    def test_host_already_set(self):
        svc, _ = _service()
        rule = _rule(host="relay.example.com")
        targets = svc._resolve_rule_targets(rule, {})
        assert targets == [("relay.example.com", "ct", "ipv4")]

    def test_exact_binding_match(self):
        svc, _ = _service()
        binding = _binding(isp="ct", ip_version="ipv4", host_value="bound.example.com")
        from app.services.domain_binding_service import binding_key
        key = binding_key("acc1", "IPLC-JP", "ct", "ipv4")
        bindings = {key: binding}

        rule = _rule(host="", isp="ct")
        targets = svc._resolve_rule_targets(rule, bindings)
        assert len(targets) == 1
        assert targets[0][0] == "bound.example.com"

    def test_fallback_to_other_binding(self):
        svc, _ = _service()
        binding = _binding(isp="other", ip_version="ipv4", host_value="fallback.example.com")
        from app.services.domain_binding_service import binding_key
        key = binding_key("acc1", "IPLC-JP", "other", "ipv4")
        bindings = {key: binding}

        rule = _rule(host="", isp="ct")
        targets = svc._resolve_rule_targets(rule, bindings)
        assert len(targets) == 1
        assert targets[0][0] == "fallback.example.com"

    def test_no_binding_returns_empty(self):
        svc, _ = _service()
        rule = _rule(host="", isp="ct")
        targets = svc._resolve_rule_targets(rule, {})
        assert targets == []


class TestSnapshotRebuildCompatibility:
    def test_rebuild_account_from_latest_rules_fixes_mobile_entry_names(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account
        repo.snapshots[account.id] = [
            GoRelayAccountSnapshotPayload(
                account=GoRelayAccountSnapshot(
                    account_id=account.id,
                    snapshot_id="snap-old",
                    created_at="2025-01-01T00:00:00Z",
                    node_count=0,
                    device_count=0,
                    status="success",
                ),
                collected_rules=[
                    _rule(
                        account_id=account.id,
                        host="2409:8c54:1841:2008:0:1:0:1e5",
                        ip_version="ipv6",
                        isp="other",
                        entry_name="「Lv2」广东隧道「移动入口」",
                    )
                ],
                device_nodes={},
                device_names={},
                pending_bindings=[],
                source_status={},
            )
        ]

        result = svc.rebuild_account_from_latest_rules(account.id)
        rebuilt = repo.load_gorelay_latest_account_snapshot(account.id)

        assert result["ok"] is True
        assert rebuilt is not None
        nodes = [n for items in rebuilt.device_nodes.values() for n in items]
        assert len(nodes) == 1
        assert nodes[0].name.startswith("🇺🇸 美国 · 移动")
        assert nodes[0].source_isp == "cm"

    def test_list_entry_usage_uses_effective_isp_for_legacy_rules(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account
        repo.snapshots[account.id] = [
            GoRelayAccountSnapshotPayload(
                account=GoRelayAccountSnapshot(
                    account_id=account.id,
                    snapshot_id="snap-old",
                    created_at="2025-01-01T00:00:00Z",
                    node_count=0,
                    device_count=0,
                    status="success",
                ),
                collected_rules=[
                    _rule(
                        account_id=account.id,
                        host="",
                        isp="other",
                        entry_name="「Lv2」广东隧道「移动入口」",
                    )
                ],
                device_nodes={},
                device_names={},
                pending_bindings=[],
                source_status={},
            )
        ]

        items = svc.list_entry_usage(account.id)

        assert len(items) == 1
        assert items[0]["entry_name"] == "「Lv2」广东隧道「移动入口」"
        assert items[0]["isp"] == "cm"

    def test_list_entry_usage_splits_other_rows_to_specific_bindings(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account
        repo.domain_bindings = [
            _binding(
                account_id=account.id,
                entry_name="「Lv1」广东隧道「电信联通」",
                isp="ct",
                host_value="ct.example.com",
            ),
            _binding(
                account_id=account.id,
                entry_name="「Lv1」广东隧道「电信联通」",
                isp="cu",
                host_value="cu.example.com",
            ),
        ]
        repo.snapshots[account.id] = [
            GoRelayAccountSnapshotPayload(
                account=GoRelayAccountSnapshot(
                    account_id=account.id,
                    snapshot_id="snap-split",
                    created_at="2025-01-01T00:00:00Z",
                    node_count=0,
                    device_count=0,
                    status="success",
                ),
                collected_rules=[
                    _rule(
                        account_id=account.id,
                        host="",
                        isp="other",
                        entry_name="「Lv1」广东隧道「电信联通」",
                        status="pending_domain",
                    )
                ],
                device_nodes={},
                device_names={},
                pending_bindings=[],
                source_status={},
            )
        ]

        items = svc.list_entry_usage(account.id)

        assert len(items) == 2
        assert {item["isp"] for item in items} == {"ct", "cu"}
        assert all(item["resolved"] is True for item in items)
        assert all(item["binding_source"] == "exact" for item in items)
        assert all(item["devices"][0]["device_name"] == "TestDevice" for item in items)

    def test_repair_accounts_with_resolvable_pending_bindings_rebuilds_once(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account
        repo.domain_bindings = [_binding(account_id=account.id, host_value="bound.example.com", isp="ct")]
        repo.snapshots[account.id] = [
            GoRelayAccountSnapshotPayload(
                account=GoRelayAccountSnapshot(
                    account_id=account.id,
                    snapshot_id="snap-repair",
                    created_at="2025-01-01T00:00:00Z",
                    node_count=0,
                    device_count=0,
                    status="success",
                ),
                collected_rules=[
                    _rule(
                        account_id=account.id,
                        host="",
                        isp="ct",
                        status="pending_domain",
                    )
                ],
                device_nodes={},
                device_names={},
                pending_bindings=[],
                source_status={},
            )
        ]

        first = svc._repair_accounts_with_resolvable_pending_bindings()
        rebuilt = repo.load_gorelay_latest_account_snapshot(account.id)
        second = svc._repair_accounts_with_resolvable_pending_bindings()

        assert first["repaired_count"] == 1
        assert rebuilt is not None
        nodes = [n for items in rebuilt.device_nodes.values() for n in items]
        assert len(nodes) == 1
        assert nodes[0].host == "bound.example.com"
        assert second["repaired_count"] == 0


# ── _sync_device_entities ────────────────────────────────────────────────────


class TestSyncDeviceEntities:
    def test_creates_new_profile_and_subscription(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        device_names = {"dev-a": "DeviceA", "dev-b": "DeviceB"}
        result = svc._sync_device_entities(account, device_names)

        assert len(repo.device_profiles) == 2
        assert len(repo.device_subscriptions) == 2
        assert result["stale_subscription_disabled"] == 0
        assert result["stale_profile_marked"] == 0

    def test_marks_stale_profiles_and_subscriptions(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        repo.device_profiles = [
            GoRelayDeviceProfile(account_id="acc1", device_key="old-dev", device_name="OldDev", enabled=True)
        ]
        repo.device_subscriptions = [
            GoRelayDeviceSubscription(
                id="sub-old", account_id="acc1", device_key="old-dev",
                device_name="OldDev", token="tok-old", enabled=True,
            )
        ]

        device_names = {"new-dev": "NewDev"}
        result = svc._sync_device_entities(account, device_names)

        assert result["stale_profile_marked"] == 1
        assert result["stale_subscription_disabled"] == 1
        old_profile = next(p for p in repo.device_profiles if p.device_key == "old-dev")
        assert old_profile.enabled is False
        new_profile = next(p for p in repo.device_profiles if p.device_key == "new-dev")
        assert new_profile.enabled is True

    def test_updates_existing_device_name(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        repo.device_profiles = [
            GoRelayDeviceProfile(account_id="acc1", device_key="dev-a", device_name="OldName", enabled=True)
        ]
        repo.device_subscriptions = [
            GoRelayDeviceSubscription(
                id="sub1", account_id="acc1", device_key="dev-a",
                device_name="OldName", token="tok1", enabled=True,
            )
        ]

        device_names = {"dev-a": "NewName"}
        svc._sync_device_entities(account, device_names)

        profile = next(p for p in repo.device_profiles if p.device_key == "dev-a")
        assert profile.device_name == "NewName"
        sub = next(s for s in repo.device_subscriptions if s.device_key == "dev-a")
        assert sub.device_name == "NewName"


# ── _apply_credentials_to_nodes ──────────────────────────────────────────────


class TestApplyCredentials:
    def test_default_credentials(self):
        svc, repo = _service()
        account = _account(proxy_username_default="u_default", proxy_password_default="p_default")
        repo.accounts[account.id] = account

        nodes = [
            NodeRecord(name="n1", host="relay.example.com", port=443, protocol="socks5"),
        ]
        result = svc._apply_credentials_to_nodes(account, "some-device", nodes)
        assert len(result) == 1
        assert result[0].username == "u_default"
        assert result[0].password == "p_default"

    def test_device_override_credentials(self):
        svc, repo = _service()
        account = _account(proxy_username_default="u_default", proxy_password_default="p_default")
        repo.accounts[account.id] = account
        repo.device_profiles = [
            GoRelayDeviceProfile(
                account_id="acc1", device_key="dev-x",
                device_name="DevX",
                proxy_username_override="u_override",
                proxy_password_override="p_override",
                enabled=True,
            )
        ]

        nodes = [
            NodeRecord(name="n1", host="relay.example.com", port=443, protocol="socks5"),
        ]
        result = svc._apply_credentials_to_nodes(account, "dev-x", nodes)
        assert result[0].username == "u_override"
        assert result[0].password == "p_override"

    def test_node_with_existing_credentials_preserved(self):
        svc, repo = _service()
        account = _account(proxy_username_default="u_default", proxy_password_default="p_default")
        repo.accounts[account.id] = account

        nodes = [
            NodeRecord(
                name="n1", host="relay.example.com", port=443,
                protocol="socks5", username="existing_u", password="existing_p",
            ),
        ]
        result = svc._apply_credentials_to_nodes(account, "some-device", nodes)
        assert result[0].username == "existing_u"
        assert result[0].password == "existing_p"


# ── import_domain_bindings_from_text ─────────────────────────────────────────


class TestImportDomainBindings:
    def test_basic_import(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        snapshot = GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="acc1", snapshot_id="snap1",
                created_at="2025-01-01T00:00:00Z",
                node_count=0, device_count=0, status="empty",
            ),
            collected_rules=[
                _rule(host="", isp="ct", status="ready"),
            ],
            device_nodes={},
            device_names={},
            pending_bindings=[],
            source_status={},
        )
        repo.snapshots["acc1"] = [snapshot]

        text = """\
「IPLC-JP」
【电信 IPv4】new-host-ct.example.com
【联通 IPv4】new-host-cu.example.com
"""
        result = asyncio.run(svc.import_domain_bindings_from_text("acc1", text))
        assert result["ok"] is True
        assert result["parsed"] == 2
        assert result["changed"] == 2
        assert len(repo.domain_bindings) == 2

    def test_import_no_valid_data_raises(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        with pytest.raises(ValueError, match="no valid domain bindings"):
            asyncio.run(svc.import_domain_bindings_from_text("acc1", "random garbage text"))

    def test_import_nonexistent_account_raises(self):
        svc, repo = _service()
        with pytest.raises(ValueError, match="account not found"):
            asyncio.run(svc.import_domain_bindings_from_text("nonexistent", "「Entry」\n【电信 IPv4】host.example.com"))

    def test_import_updates_existing_binding(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        existing_binding = _binding(entry_name="「IPLC-JP」", isp="ct", host_value="old.example.com")
        repo.domain_bindings = [existing_binding]

        snapshot = GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="acc1", snapshot_id="snap1",
                created_at="2025-01-01T00:00:00Z",
                node_count=0, device_count=0, status="empty",
            ),
            collected_rules=[_rule(host="", isp="ct", status="ready")],
            device_nodes={},
            device_names={},
            pending_bindings=[],
            source_status={},
        )
        repo.snapshots["acc1"] = [snapshot]

        text = """\
「IPLC-JP」
【电信 IPv4】updated.example.com
"""
        result = asyncio.run(svc.import_domain_bindings_from_text("acc1", text))
        assert result["changed"] == 1
        ct_bindings = [b for b in repo.domain_bindings if b.isp == "ct"]
        assert len(ct_bindings) == 1
        assert ct_bindings[0].host_value == "updated.example.com"


# ── get_all_active_nodes ─────────────────────────────────────────────────────


class TestGetAllActiveNodes:
    def test_returns_nodes_with_credentials(self):
        svc, repo = _service()
        account = _account()
        repo.accounts[account.id] = account

        node = NodeRecord(
            name="n1", host="relay.example.com", port=443, protocol="socks5",
            source_id="acc1", account_id="acc1", device_key="dev-a",
        )
        snapshot = GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="acc1", snapshot_id="snap1",
                created_at="2025-01-01T00:00:00Z",
                node_count=1, device_count=1, status="success",
            ),
            collected_rules=[],
            device_nodes={"dev-a": [node]},
            device_names={"dev-a": "DevA"},
            pending_bindings=[],
            source_status={},
        )
        repo.snapshots["acc1"] = [snapshot]
        repo.active_snapshot_ids["acc1"] = "snap1"

        nodes = svc.get_all_active_nodes()
        assert len(nodes) == 1
        assert nodes[0].username == "proxy_user"
        assert nodes[0].password == "proxy_pass"

    def test_disabled_account_excluded(self):
        svc, repo = _service()
        account = _account(enabled=False)
        repo.accounts[account.id] = account

        nodes = svc.get_all_active_nodes()
        assert nodes == []
