from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from app.config import Settings
from app.models import (
    STANDARD_SOURCE_AUTO_PULL_FAILURE_EXPIRED_THRESHOLD,
    CollectedOutbound,
    CollectedRule,
    CustomRule,
    DeviceSubscription,
    GoRelayAccount,
    GoRelayAccountSnapshot,
    GoRelayAccountSnapshotPayload,
    GoRelayDeviceProfile,
    GoRelayDeviceSubscription,
    NodeRecord,
    QUALITY_BULK,
    QUALITY_CHAIN_HOME,
    QUALITY_HIGH_PREMIUM,
    QUALITY_HIGH_STANDARD,
    QUALITY_MEDIUM,
    RuleCategory,
    StandardSource,
)
from app.services.gorelay_service import GorelayService
from app.services.hub_service import HubService, summarize_refresh_status
from app.services.rule_catalog import RuleCatalog
from app.services.source_fetcher import SourceFetcher, SourcePullResult
from app.services.source_diagnostics import public_runtime, summarize_hub_error
from app.storage.sqlite_repo import SqliteRepo


def _settings(tmp_path) -> Settings:
    return Settings(
        app_name="SubHub",
        app_base_url="",
        storage_root=str(tmp_path),
        refresh_interval_minutes=30,
        request_timeout_seconds=20,
        verify_tls=True,
        github_api_base="https://127.0.0.1/invalid",
        github_raw_base="https://127.0.0.1/invalid",
        rule_catalog_refresh_hours=24,
        manage_api_require_login=False,
        max_snapshots_per_account=20,
        account_crawl_parallelism=2,
    )


@pytest.mark.parametrize("refresh_kind", ["all", "standard", "single"])
def test_hub_errors_deduplicate_within_sources_and_preserve_source_boundaries(tmp_path, monkeypatch, refresh_kind) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    for source_id in ("first", "second"):
        repo.save_standard_source(StandardSource(id=source_id, name=source_id, clash_url="https://example.test/sub"))
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), GorelayService(settings, repo))
    url = "https://private-user:private-pass@sub.example/link/0123456789abcdef?x=private-query#private-fragment"
    entry = f"clash: HTTP 404 ({url})"
    original = "; ".join([entry] * 3 + ["surge: 0 valid nodes parsed; reason1; reason2"] * 2)
    clean = "clash: HTTP 404 (https://sub.example/link/<redacted>); surge: 0 valid nodes parsed; reason1; reason2"

    async def failed_fetch(source):
        return SourcePullResult(ok=False, error=original)

    async def cached_rules(**kwargs):
        return {"ok": True, "source": "cache"}

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", failed_fetch)
    monkeypatch.setattr(hub.rule_catalog, "refresh_categories", cached_rules)
    if refresh_kind == "all":
        asyncio.run(hub.refresh(force=True))
    elif refresh_kind == "standard":
        asyncio.run(hub.refresh_standard_sources_only())
    else:
        asyncio.run(hub.refresh_one_standard_source("first"))
    count = 1 if refresh_kind == "single" else 2
    expected = "; ".join([clean] * count)
    assert hub.runtime.last_error == expected
    aggregate = hub.runtime.source_status["aggregate"]
    assert aggregate["errors"] == [original] * count
    assert (aggregate["attempted_count"], aggregate["failed_count"], aggregate["succeeded_count"]) == (count, count, 0)
    assert aggregate["status"] == "failed"
    assert hub.status()["runtime"]["last_error"] == expected

    # Emulate an in-memory summary produced before the change, with its actual
    # aggregate evidence. Reading it must not collapse the two source failures.
    old_last_error = "; ".join(aggregate["errors"])
    hub.runtime.last_error = old_last_error
    for _ in range(2):
        status = hub.status()
        assert status["last_error"] == status["runtime"]["last_error"] == expected
    assert hub.runtime.last_error == old_last_error
    assert hub.runtime.source_status["aggregate"] == aggregate
    repo.close()


def test_hub_error_without_source_boundaries_only_redacts() -> None:
    original = "clash: HTTP 404; clash: HTTP 404; failed https://user:secret@sub.example/s/0123456789abcdef?x=private#private"
    expected = "clash: HTTP 404; clash: HTTP 404; failed https://sub.example/s/<redacted>"
    assert summarize_hub_error(original, None) == expected
    assert summarize_hub_error(original, ["stale source error"]) == expected
    assert summarize_hub_error(None, []) is None
    assert summarize_hub_error("", []) == ""


@pytest.mark.parametrize("url, public_url", [
    ("//private-user:private-pass@host.test/link/abc123def456?q=query-secret#fragment-secret",
     "//host.test/link/<redacted>"),
    ("https://h.test/a//abc123def456", "https://h.test/a//<redacted>"),
    ("https://h/link/AAparseAAAAAAAAAAAAAhttps://x", "https://h/link/<redacted>https://x"),
    ("1://u:p@h/link/abc123def456", "1://h/link/<redacted>"),
])
def test_public_runtime_projection_is_independent_idempotent_and_concurrent(url, public_url) -> None:
    entry = f"clash: HTTP 404 ({url})"
    old = f"{entry}; {entry}"
    attempt = {"url": url, "error": entry, "skip_reasons": [entry]}
    original = {
        "last_error": f"{old}; {old}",
        "source_status": {
            "aggregate": {"errors": [old, old], "failed_count": 2},
            "standard": {"first": {"error": old, "attempts": [attempt]}, "second": {"error": old, "attempts": [attempt]}},
        },
    }
    before = deepcopy(original)
    clean = f"clash: HTTP 404 ({public_url})"
    with ThreadPoolExecutor(max_workers=4) as pool:
        copies = list(pool.map(public_runtime, [original] * 12))
    for payload in copies:
        assert payload["last_error"] == f"{clean}; {clean}"
        assert payload["source_status"]["aggregate"]["errors"] == [clean, clean]
        assert public_runtime(payload) == payload
    copies[0]["source_status"]["standard"]["first"]["attempts"][0]["skip_reasons"].append("changed")
    assert copies[0] != copies[1]
    assert original == before


def test_refresh_summary_counts_fresh_attempts_without_promoting_cached_rules() -> None:
    mixed = summarize_refresh_status({
        "rule_catalog": {"ok": False, "partial": True, "count": 9, "downloaded_count": 1,
                         "reused_count": 6, "failed_count": 2, "succeeded_count": 1},
        "standard": {"fresh": {"ok": True}, "failed": {"ok": False, "cached_node_count": 10}},
        "gorelay": {"ok": True, "failed_count": 0, "succeeded_count": 1,
                    "accounts": {"old-disabled": {"status": "failed", "error": "old failure"}}},
    })
    assert mixed["status"] == "partial"
    assert (mixed["attempted_count"], mixed["succeeded_count"], mixed["failed_count"]) == (6, 3, 3)
    failed = summarize_refresh_status({
        "rule_catalog": {"ok": False, "count": 4, "reused_count": 4, "failed_count": 2,
                         "downloaded_count": 0, "succeeded_count": 0},
        "gorelay": {"ok": True, "accounts": {}},
    })
    assert failed["partial"] is False
    assert failed["status"] == "failed"
    assert (failed["attempted_count"], failed["succeeded_count"], failed["failed_count"]) == (2, 0, 2)
    cached = summarize_refresh_status({"rule_catalog": {"ok": True, "source": "cache", "count": 40,
                                                               "failed_count": 0, "succeeded_count": 0}})
    assert cached["attempted_count"] == cached["succeeded_count"] == 0
    single = summarize_refresh_status({"gorelay": {"ok": True, "account_id": "one"}})
    assert single["attempted_count"] == single["succeeded_count"] == 1


def test_standard_only_refresh_counts_current_sources_and_keeps_history_separate(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_standard_source(StandardSource(id="active", name="Active", ingest_kind="manual_nodes",
                                            manual_nodes_text="trojan://p@active.example:443#Active", target_contract_id="medium"))
    repo.save_standard_source(StandardSource(id="disabled", name="Disabled", enabled=False, target_contract_id="medium"))
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), GorelayService(settings, repo))
    hub.runtime.source_status = {
        "standard": {"disabled": {"ok": False, "error": "old"}, "deleted": {"ok": False, "error": "deleted"}},
        "rule_catalog": {"ok": False, "failed_count": 2, "error": "earlier rules"},
        "gorelay": {"ok": False, "failed_count": 1, "error": "earlier account"},
    }
    result = asyncio.run(hub.refresh_standard_sources_only())
    assert result["ok"] is True
    assert (result["attempted_count"], result["succeeded_count"], result["failed_count"]) == (1, 1, 0)
    assert set(result["standard"]) == {"active"}
    assert "disabled" in hub.runtime.source_status["standard"]
    assert hub.runtime.source_status["aggregate"]["attempted_count"] == 1
    assert hub.runtime.last_error is None
    asyncio.run(hub.refresh_one_standard_source("active"))
    assert hub.runtime.source_status["aggregate"]["failed_count"] == 0


def test_standard_refresh_exception_persists_failure_and_retains_last_nodes(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    source = StandardSource(id="source", name="Source", clash_url="https://example.test/sub", target_contract_id="medium")
    repo.save_standard_source(source)
    repo.save_standard_node_cache(source.id, [NodeRecord("Saved", "saved.example", 443, "trojan", password="saved")])
    repo.save_standard_source_pull_status(source.id, attempt_at="2026-01-01T00:00:00Z", ok=True, method="clash", node_count=1, error="", trigger="manual")
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), GorelayService(settings, repo))

    async def failed_fetch(source):
        raise RuntimeError("collector exception")

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", failed_fetch)
    result = asyncio.run(hub.refresh_one_standard_source(source.id))
    assert result["ok"] is False
    assert result["cached_node_count"] == result["pull_node_count"] == 1
    latest = repo.get_standard_source(source.id)
    assert latest.last_pull_ok is False
    assert latest.last_success_at == "2026-01-01T00:00:00Z"
    assert latest.last_pull_error == "collector exception"
    assert len(repo.load_standard_node_cache(source.id)) == 1


async def _fake_collect(*args, **kwargs):
    rules = [
        CollectedRule(
            account_id="g1",
            rule_id="r1",
            device_name="Mac",
            line_name="Mac #1",
            entry_name="上海 1x",
            isp="电信",
            ip_version="ipv4",
            port=1080,
            host="1.1.1.1",
            status="ready",
            raw={"multiplier": "1"},
        ),
        CollectedRule(
            account_id="g1",
            rule_id="r2",
            device_name="iPhone",
            line_name="iPhone #1",
            entry_name="东京 4x",
            isp="联通",
            ip_version="ipv4",
            port=1081,
            host="2.2.2.2",
            status="ready",
            raw={"multiplier": "4"},
        ),
    ]
    return rules, [], {"collector": "mock"}


async def _fake_fetch_source(*args, **kwargs):
    nodes = [
        NodeRecord(
            name="[机场B] shared",
            host="shared.example.com",
            port=443,
            protocol="http",
            quality_group="中等质量",
            source_id="s1",
            source_type="standard",
        )
    ]
    return SourcePullResult(ok=True, method="clash", node_count=1, nodes=nodes)


def test_hub_refresh_builds_devices_and_merges_nodes(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_gorelay_account(
        GoRelayAccount(
            id="g1",
            name="家宽",
            login_url="https://relay.example.com",
            rules_url="https://relay.example.com",
            gorelay_username="u",
            gorelay_password="p",
            enabled=True,
        )
    )
    repo.save_standard_source(
        StandardSource(
            id="s1",
            name="机场B",
            clash_url="https://x/clash",
            shadowrocket_url="https://x/sr",
            quality_group="中等质量",
            enabled=True,
        )
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)
    monkeypatch.setattr(gorelay.collector, "collect", _fake_collect)
    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _fake_fetch_source)

    import asyncio

    asyncio.run(hub.refresh(force=True))

    devices = hub.list_devices()
    assert len(devices) == 2
    mac = next(item for item in devices if item.device_name == "Mac")
    nodes = hub.get_nodes_for_token(mac.token)
    assert nodes is not None
    assert any(n.source_type == "gorelay" for n in nodes)
    assert any(n.source_type == "standard" for n in nodes)


def test_sync_devices_from_gorelay_snapshots_updates_management_subscriptions(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_gorelay_account(
        GoRelayAccount(
            id="g1",
            name="家宽",
            login_url="https://relay.example.com",
            rules_url="https://relay.example.com",
            gorelay_username="u",
            gorelay_password="p",
            enabled=True,
        )
    )
    repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="g1",
                snapshot_id="snap-1",
                created_at="2026-03-10T00:00:00Z",
                node_count=0,
                device_count=2,
                status="empty",
            ),
            collected_rules=[],
            device_nodes={},
            device_names={"mac": "Mac", "iphone": "iPhone"},
            pending_bindings=[],
            source_status={},
        )
    )
    repo.save_gorelay_active_snapshot_id("g1", "snap-1")
    repo.save_device_subscription(
        DeviceSubscription(
            id="sub-mac",
            device_key="mac",
            device_name="Old Mac",
            token="tok-mac",
            enabled=False,
        )
    )
    repo.save_device_subscription(
        DeviceSubscription(
            id="sub-stale",
            device_key="stale-device",
            device_name="Stale Device",
            token="tok-stale",
            enabled=True,
        )
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    summary = hub.sync_devices_from_gorelay_snapshots()
    assert summary["before_count"] == 2
    assert summary["after_count"] == 3
    assert summary["added_count"] == 1
    assert summary["reenabled_count"] == 1
    assert summary["disabled_count"] == 1

    devices = {item.device_key: item for item in repo.list_device_subscriptions()}
    assert devices["mac"].device_name == "Mac"
    assert devices["mac"].enabled is True
    assert devices["iphone"].enabled is True
    assert devices["stale-device"].enabled is False


def test_get_nodes_for_token_builds_chain_home_combinations_from_fronts_and_unique_rears(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_gorelay_account(
        GoRelayAccount(
            id="g1",
            name="家宽",
            login_url="https://relay.example.com",
            rules_url="https://relay.example.com",
            gorelay_username="u",
            gorelay_password="p",
            enabled=True,
        )
    )
    repo.upsert_gorelay_device_subscription(
        GoRelayDeviceSubscription(
            id="sub-1",
            account_id="g1",
            device_key="mac",
            device_name="Mac",
            token="tok-mac",
            enabled=True,
        )
    )
    repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="g1",
                snapshot_id="snap-1",
                created_at="2026-03-10T00:00:00Z",
                node_count=1,
                device_count=1,
                status="success",
            ),
            collected_rules=[],
            device_nodes={
                "mac": [
                    NodeRecord(
                        name="旧链式家宽",
                        host="legacy.example.com",
                        port=1080,
                        protocol="socks5",
                        quality_group=QUALITY_CHAIN_HOME,
                        source_type="gorelay",
                        device_key="mac",
                        device_name="Mac",
                        raw={"chain_home": True},
                    )
                ]
            },
            device_names={"mac": "Mac"},
            pending_bindings=[],
            source_status={},
            collected_outbounds=[
                CollectedOutbound(
                    account_id="g1",
                    rule_id="r1",
                    device_name="Mac",
                    line_name="Mac #1",
                    outbound_group_id="og-1",
                    outbound_group_name="家宽 A",
                    targets=["rear-a.example.com:3001"],
                ),
                CollectedOutbound(
                    account_id="g1",
                    rule_id="r2",
                    device_name="Mac",
                    line_name="Mac #2",
                    outbound_group_id="og-2",
                    outbound_group_name="家宽 A 重复",
                    targets=["rear-a.example.com:3001"],
                ),
                CollectedOutbound(
                    account_id="g1",
                    rule_id="r3",
                    device_name="Mac",
                    line_name="Mac #3",
                    outbound_group_id="og-3",
                    outbound_group_name="家宽 B",
                    targets=["rear-b.example.com:3002"],
                ),
            ],
        )
    )
    repo.save_gorelay_active_snapshot_id("g1", "snap-1")
    repo.save_standard_source(
        StandardSource(
            id="s-medium",
            name="机场M",
            clash_url="https://m.example.com/clash",
            shadowrocket_url="https://m.example.com/sr",
            quality_group=QUALITY_MEDIUM,
            enabled=True,
        )
    )
    repo.save_standard_node_cache(
        "s-medium",
        [
            NodeRecord(
                name="medium-front",
                host="medium.example.com",
                port=443,
                protocol="http",
                quality_group=QUALITY_MEDIUM,
                source_id="s-medium",
                source_type="standard",
            )
        ],
    )
    repo.save_standard_source(
        StandardSource(
            id="s-bulk",
            name="机场B",
            clash_url="https://b.example.com/clash",
            shadowrocket_url="https://b.example.com/sr",
            quality_group=QUALITY_BULK,
            enabled=True,
        )
    )
    repo.save_standard_node_cache(
        "s-bulk",
        [
            NodeRecord(
                name="bulk-front",
                host="bulk.example.com",
                port=443,
                protocol="http",
                quality_group=QUALITY_BULK,
                source_id="s-bulk",
                source_type="standard",
            )
        ],
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    nodes = hub.get_nodes_for_token("tok-mac")
    assert nodes is not None

    chain_nodes = [node for node in nodes if node.quality_group == QUALITY_CHAIN_HOME]
    assert len(chain_nodes) == 2
    assert {node.raw.get("chain_rear_target") for node in chain_nodes} == {
        "rear-a.example.com:3001",
        "rear-b.example.com:3002",
    }
    labels_by_target = {
        str(node.raw.get("chain_rear_target")): str(node.raw.get("chain_rear_label"))
        for node in chain_nodes
    }
    assert labels_by_target == {
        "rear-a.example.com:3001": "家宽1",
        "rear-b.example.com:3002": "家宽2",
    }
    assert {
        (str(node.raw.get("chain_rear_target")), str(node.raw.get("chain_rear_group_name")))
        for node in chain_nodes
    } == {
        ("rear-a.example.com:3001", "家宽 A"),
        ("rear-b.example.com:3002", "家宽 B"),
    }
    assert {node.name for node in chain_nodes} == {"链式家宽 | 家宽1", "链式家宽 | 家宽2"}
    assert not any("front" in node.name for node in chain_nodes)
    assert all("chain_front_dedupe_key" not in (node.raw or {}) for node in chain_nodes)
    assert all("chain_front_source_name" not in (node.raw or {}) for node in chain_nodes)
    assert not any(node.name == "旧链式家宽" for node in nodes)


def test_parse_chain_target_supports_auth_variants() -> None:
    assert HubService._parse_chain_target("rear-a.example.com:3001") == (
        "rear-a.example.com",
        3001,
        "",
        "",
    )
    assert HubService._parse_chain_target("user-a:pass-a@rear-b.example.com:3002") == (
        "rear-b.example.com",
        3002,
        "user-a",
        "pass-a",
    )
    assert HubService._parse_chain_target("socks5://u%20ser:p%3A1@rear-c.example.com:3003") == (
        "rear-c.example.com",
        3003,
        "u ser",
        "p:1",
    )
    assert HubService._parse_chain_target("http://rear-d.example.com:3004") == ("", 0, "", "")
    assert HubService._parse_chain_target("invalid-target") == ("", 0, "", "")


def test_chain_home_nodes_apply_target_then_device_then_account_credentials(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_gorelay_account(
        GoRelayAccount(
            id="g1",
            name="家宽",
            login_url="https://relay.example.com",
            rules_url="https://relay.example.com",
            gorelay_username="u",
            gorelay_password="p",
            proxy_username_default="acc-user",
            proxy_password_default="acc-pass",
            enabled=True,
        )
    )
    repo.upsert_gorelay_device_profile(
        GoRelayDeviceProfile(
            account_id="g1",
            device_key="mac",
            device_name="Mac",
            proxy_username_override="dev-user",
            # Leave password override empty to verify fallback to account default.
            proxy_password_override="",
            enabled=True,
        )
    )
    repo.upsert_gorelay_device_subscription(
        GoRelayDeviceSubscription(
            id="sub-1",
            account_id="g1",
            device_key="mac",
            device_name="Mac",
            token="tok-mac",
            enabled=True,
        )
    )
    repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="g1",
                snapshot_id="snap-1",
                created_at="2026-03-10T00:00:00Z",
                node_count=0,
                device_count=1,
                status="success",
            ),
            collected_rules=[],
            device_nodes={"mac": []},
            device_names={"mac": "Mac"},
            pending_bindings=[],
            source_status={},
            collected_outbounds=[
                CollectedOutbound(
                    account_id="g1",
                    rule_id="r1",
                    device_name="Mac",
                    line_name="Mac #1",
                    outbound_group_id="og-1",
                    outbound_group_name="家宽 A",
                    targets=["target-user:target-pass@rear-a.example.com:3001"],
                ),
                CollectedOutbound(
                    account_id="g1",
                    rule_id="r2",
                    device_name="Mac",
                    line_name="Mac #2",
                    outbound_group_id="og-2",
                    outbound_group_name="家宽 B",
                    targets=["socks5://u%20ser:p%3A1@rear-b.example.com:3002"],
                ),
                CollectedOutbound(
                    account_id="g1",
                    rule_id="r3",
                    device_name="Mac",
                    line_name="Mac #3",
                    outbound_group_id="og-3",
                    outbound_group_name="家宽 C",
                    targets=["rear-c.example.com:3003"],
                ),
            ],
        )
    )
    repo.save_gorelay_active_snapshot_id("g1", "snap-1")
    repo.save_standard_source(
        StandardSource(
            id="s-medium",
            name="机场M",
            clash_url="https://m.example.com/clash",
            shadowrocket_url="https://m.example.com/sr",
            quality_group=QUALITY_MEDIUM,
            enabled=True,
        )
    )
    repo.save_standard_node_cache(
        "s-medium",
        [
            NodeRecord(
                name="medium-front",
                host="medium.example.com",
                port=443,
                protocol="http",
                quality_group=QUALITY_MEDIUM,
                source_id="s-medium",
                source_type="standard",
            )
        ],
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    nodes = hub.get_nodes_for_token("tok-mac")
    assert nodes is not None

    chain_nodes = [node for node in nodes if node.quality_group == QUALITY_CHAIN_HOME]
    assert len(chain_nodes) == 3
    by_target = {str(node.raw.get("chain_rear_target")): node for node in chain_nodes}

    node_a = by_target["rear-a.example.com:3001"]
    assert node_a.username == "target-user"
    assert node_a.password == "target-pass"
    assert node_a.raw.get("chain_rear_auth_source") == "target"

    node_b = by_target["rear-b.example.com:3002"]
    assert node_b.username == "u ser"
    assert node_b.password == "p:1"
    assert node_b.raw.get("chain_rear_auth_source") == "target"

    node_c = by_target["rear-c.example.com:3003"]
    assert node_c.username == "dev-user"
    assert node_c.password == "acc-pass"
    assert node_c.raw.get("chain_rear_auth_source") == "device_or_account"

    chain_auth = (hub.runtime.source_status or {}).get("chain_home_auth") or {}
    assert chain_auth.get("missing_auth_count") == 0
    assert chain_auth.get("checked_chain_node_count") == 3


def test_chain_home_missing_credentials_exposed_in_runtime_status(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_gorelay_account(
        GoRelayAccount(
            id="g1",
            name="家宽",
            login_url="https://relay.example.com",
            rules_url="https://relay.example.com",
            gorelay_username="u",
            gorelay_password="p",
            enabled=True,
        )
    )
    repo.upsert_gorelay_device_subscription(
        GoRelayDeviceSubscription(
            id="sub-1",
            account_id="g1",
            device_key="mac",
            device_name="Mac",
            token="tok-mac",
            enabled=True,
        )
    )
    repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="g1",
                snapshot_id="snap-1",
                created_at="2026-03-10T00:00:00Z",
                node_count=0,
                device_count=1,
                status="success",
            ),
            collected_rules=[],
            device_nodes={"mac": []},
            device_names={"mac": "Mac"},
            pending_bindings=[],
            source_status={},
            collected_outbounds=[
                CollectedOutbound(
                    account_id="g1",
                    rule_id="r1",
                    device_name="Mac",
                    line_name="Mac #1",
                    outbound_group_id="og-1",
                    outbound_group_name="家宽 A",
                    targets=["rear-a.example.com:3001"],
                )
            ],
        )
    )
    repo.save_gorelay_active_snapshot_id("g1", "snap-1")
    repo.save_standard_source(
        StandardSource(
            id="s-medium",
            name="机场M",
            clash_url="https://m.example.com/clash",
            shadowrocket_url="https://m.example.com/sr",
            quality_group=QUALITY_MEDIUM,
            enabled=True,
        )
    )
    repo.save_standard_node_cache(
        "s-medium",
        [
            NodeRecord(
                name="medium-front",
                host="medium.example.com",
                port=443,
                protocol="http",
                quality_group=QUALITY_MEDIUM,
                source_id="s-medium",
                source_type="standard",
            )
        ],
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    nodes = hub.get_nodes_for_token("tok-mac")
    assert nodes is not None

    chain_nodes = [node for node in nodes if node.quality_group == QUALITY_CHAIN_HOME]
    assert len(chain_nodes) == 1
    assert chain_nodes[0].username == ""
    assert chain_nodes[0].password == ""

    chain_auth = (hub.runtime.source_status or {}).get("chain_home_auth") or {}
    assert chain_auth.get("missing_auth_count") == 1
    assert chain_auth.get("checked_chain_node_count") == 1
    examples = list(chain_auth.get("missing_auth_examples") or [])
    assert len(examples) == 1
    assert examples[0]["account_id"] == "g1"
    assert examples[0]["device_key"] == "mac"
    assert examples[0]["rear_target"] == "rear-a.example.com:3001"


def test_get_nodes_for_token_skips_chain_home_when_fronts_or_rears_missing(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_gorelay_account(
        GoRelayAccount(
            id="g1",
            name="家宽",
            login_url="https://relay.example.com",
            rules_url="https://relay.example.com",
            gorelay_username="u",
            gorelay_password="p",
            enabled=True,
        )
    )
    repo.upsert_gorelay_device_subscription(
        GoRelayDeviceSubscription(
            id="sub-1",
            account_id="g1",
            device_key="mac",
            device_name="Mac",
            token="tok-mac",
            enabled=True,
        )
    )
    repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="g1",
                snapshot_id="snap-1",
                created_at="2026-03-10T00:00:00Z",
                node_count=0,
                device_count=1,
                status="success",
            ),
            collected_rules=[],
            device_nodes={"mac": []},
            device_names={"mac": "Mac"},
            pending_bindings=[],
            source_status={},
            collected_outbounds=[
                CollectedOutbound(
                    account_id="g1",
                    rule_id="r1",
                    device_name="Mac",
                    line_name="Mac #1",
                    outbound_group_id="og-1",
                    outbound_group_name="家宽 A",
                    targets=["rear-a.example.com:3001"],
                )
            ],
        )
    )
    repo.save_gorelay_active_snapshot_id("g1", "snap-1")

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    nodes = hub.get_nodes_for_token("tok-mac")
    assert nodes is not None
    assert not any(node.quality_group == QUALITY_CHAIN_HOME for node in nodes)


def test_get_nodes_for_token_builds_chain_home_labels_per_account_with_stable_sorting(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    for account_id in ("g1", "g2"):
        repo.save_gorelay_account(
            GoRelayAccount(
                id=account_id,
                name=f"家宽-{account_id}",
                login_url="https://relay.example.com",
                rules_url="https://relay.example.com",
                gorelay_username="u",
                gorelay_password="p",
                enabled=True,
            )
        )
        repo.save_gorelay_active_snapshot_id(account_id, f"snap-{account_id}")
    repo.upsert_gorelay_device_subscription(
        GoRelayDeviceSubscription(
            id="sub-1",
            account_id="g1",
            device_key="mac",
            device_name="Mac",
            token="tok-mac",
            enabled=True,
        )
    )
    repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="g1",
                snapshot_id="snap-g1",
                created_at="2026-03-10T00:00:00Z",
                node_count=0,
                device_count=1,
                status="success",
            ),
            collected_rules=[],
            device_nodes={"mac": []},
            device_names={"mac": "Mac"},
            pending_bindings=[],
            source_status={},
            collected_outbounds=[
                CollectedOutbound(
                    account_id="g1",
                    rule_id="r1",
                    device_name="Mac",
                    line_name="Mac #1",
                    outbound_group_id="og-2",
                    outbound_group_name="后出现但应为家宽2",
                    targets=["rear-b.example.com:3002"],
                ),
                CollectedOutbound(
                    account_id="g1",
                    rule_id="r2",
                    device_name="Mac",
                    line_name="Mac #2",
                    outbound_group_id="og-1",
                    outbound_group_name="先排序应为家宽1",
                    targets=["rear-a.example.com:3001"],
                ),
            ],
        )
    )
    repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="g2",
                snapshot_id="snap-g2",
                created_at="2026-03-11T00:00:00Z",
                node_count=0,
                device_count=1,
                status="success",
            ),
            collected_rules=[],
            device_nodes={"mac": []},
            device_names={"mac": "Mac"},
            pending_bindings=[],
            source_status={},
            collected_outbounds=[
                CollectedOutbound(
                    account_id="g2",
                    rule_id="r3",
                    device_name="Mac",
                    line_name="Mac #3",
                    outbound_group_id="og-3",
                    outbound_group_name="另一个账号自己的家宽1",
                    targets=["rear-c.example.com:3003"],
                )
            ],
        )
    )
    repo.save_standard_source(
        StandardSource(
            id="s-medium",
            name="机场M",
            clash_url="https://m.example.com/clash",
            shadowrocket_url="https://m.example.com/sr",
            quality_group=QUALITY_MEDIUM,
            enabled=True,
        )
    )
    repo.save_standard_node_cache(
        "s-medium",
        [
            NodeRecord(
                name="medium-front",
                host="medium.example.com",
                port=443,
                protocol="http",
                quality_group=QUALITY_MEDIUM,
                source_id="s-medium",
                source_type="standard",
            )
        ],
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    nodes = hub.get_nodes_for_token("tok-mac")
    assert nodes is not None

    chain_nodes = [node for node in nodes if node.quality_group == QUALITY_CHAIN_HOME]
    labels_by_account_target = {
        (str(node.account_id), str(node.raw.get("chain_rear_target"))): str(node.raw.get("chain_rear_label"))
        for node in chain_nodes
    }
    assert labels_by_account_target == {
        ("g1", "rear-a.example.com:3001"): "家宽1",
        ("g1", "rear-b.example.com:3002"): "家宽2",
        ("g2", "rear-c.example.com:3003"): "家宽1",
    }
    assert {
        (str(node.account_id), node.name) for node in chain_nodes
    } == {
        ("g1", "链式家宽 | 家宽1"),
        ("g1", "链式家宽 | 家宽2"),
        ("g2", "链式家宽 | 家宽1"),
    }


def test_get_rule_lines_uses_global_custom_rules_only(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_custom_rule(
        CustomRule(
            id="global-rule",
            rule_type="DOMAIN-SUFFIX",
            value="global.example.com",
            target_group="中等质量",
            category_name="",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    repo.save_custom_rule(
        CustomRule(
            id="category-rule",
            rule_type="DOMAIN-SUFFIX",
            value="category.example.com",
            target_group="",
            category_name="OpenAI",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    async def _fake_category_lines():
        return ["DOMAIN-SUFFIX,openai.com,中等质量"]

    monkeypatch.setattr(hub.rule_catalog, "get_assigned_rule_lines", _fake_category_lines)

    import asyncio

    lines = asyncio.run(hub.get_rule_lines())
    assert "DOMAIN-SUFFIX,global.example.com,中等质量" in lines
    assert "DOMAIN-SUFFIX,category.example.com,中等质量" not in lines
    assert lines.index("DOMAIN-SUFFIX,global.example.com,中等质量") < lines.index(
        "DOMAIN-SUFFIX,openai.com,中等质量"
    )


def test_build_policy_rule_entries_uses_target_resolver_without_assigned_group(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_rule_categories([RuleCategory(name="OpenAI", assigned_group="", rule_count=1)])
    repo.save_custom_rule(
        CustomRule(
            id="category-rule",
            rule_type="DOMAIN-SUFFIX",
            value="api.openai.com",
            target_group="",
            category_name="OpenAI",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), GorelayService(settings, repo))
    async def _fake_category_raw_rules(_name: str) -> list[str]:
        return []
    hub.rule_catalog.get_category_raw_rules = _fake_category_raw_rules  # type: ignore[method-assign]
    entries, warnings = asyncio.run(
        hub._build_policy_rule_entries(
            categories=[RuleCategory(name="OpenAI", assigned_group="", rule_count=1)],
            custom_rules=repo.list_custom_rules(category_name="OpenAI"),
            target_resolver=lambda category: "中等质量" if category.name == "OpenAI" else "",
        )
    )

    assert warnings == []
    rendered_lines = [entry.to_line() for entry in entries]
    assert "DOMAIN-SUFFIX,api.openai.com,中等质量" in rendered_lines


def test_get_rule_lines_backfills_legacy_assignment_contracts(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_rule_categories([RuleCategory(name="OpenAI", assigned_group="中等质量", rule_count=1)])
    repo.save_rule_cache("OpenAI", ["DOMAIN-SUFFIX,openai.com,PLACEHOLDER"])

    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), GorelayService(settings, repo))
    lines = asyncio.run(hub.get_rule_lines())

    catalog_entries = repo.list_service_catalog_entries()
    assert len(catalog_entries) == 1
    assert catalog_entries[0].contract_id == "medium"
    assert "DOMAIN-SUFFIX,openai.com,中等质量" in lines


def test_get_rule_lines_sanitizes_cidr_from_global_and_category_sources(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_custom_rule(
        CustomRule(
            id="global-cidr6",
            rule_type="IP-CIDR6",
            value="2001:db8::2",
            target_group="DIRECT",
            category_name="",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    repo.save_custom_rule(
        CustomRule(
            id="global-invalid",
            rule_type="IP-CIDR6",
            value="not-an-ipv6",
            target_group="DIRECT",
            category_name="",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    async def _fake_category_lines():
        return [
            "IP-CIDR6,2001:db8::1,中等质量",
            "IP-CIDR6,invalid-ipv6,中等质量",
        ]

    monkeypatch.setattr(hub.rule_catalog, "get_assigned_rule_lines", _fake_category_lines)

    lines = asyncio.run(hub.get_rule_lines())
    assert "IP-CIDR6,2001:db8::2/128,DIRECT" in lines
    assert "IP-CIDR6,2001:db8::1/128,中等质量" in lines
    assert not any("invalid-ipv6" in line for line in lines)


def test_get_rule_lines_dedupes_conflicts_by_rule_identity(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_custom_rule(
        CustomRule(
            id="global-direct",
            rule_type="DOMAIN-SUFFIX",
            value="ad.xiaomi.com",
            target_group="DIRECT",
            category_name="",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    async def _fake_category_lines():
        return [
            "DOMAIN-SUFFIX,ad.xiaomi.com,中等质量",
            "PROCESS-NAME,com.taobao.taobao,地区规则",
            "PROCESS-NAME,com.taobao.taobao,购物",
        ]

    monkeypatch.setattr(hub.rule_catalog, "get_assigned_rule_lines", _fake_category_lines)

    lines = asyncio.run(hub.get_rule_lines())
    assert "DOMAIN-SUFFIX,ad.xiaomi.com,DIRECT" in lines
    assert "DOMAIN-SUFFIX,ad.xiaomi.com,中等质量" not in lines
    assert "PROCESS-NAME,com.taobao.taobao,地区规则" in lines
    assert "PROCESS-NAME,com.taobao.taobao,购物" not in lines


def test_get_rule_lines_private_direct_rules_override_later_conflicts(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_custom_rule(
        CustomRule(
            id="global-private",
            rule_type="IP-CIDR",
            value="10.0.0.0/8",
            target_group="DIRECT",
            category_name="",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    async def _fake_category_lines():
        return [
            "IP-CIDR,10.0.0.0/8,中等质量,no-resolve",
        ]

    monkeypatch.setattr(hub.rule_catalog, "get_assigned_rule_lines", _fake_category_lines)

    lines = asyncio.run(hub.get_rule_lines())
    assert "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve" in lines
    assert "IP-CIDR,10.0.0.0/8,中等质量,no-resolve" not in lines


def test_build_policy_ir_for_token_applies_shared_rule_precedence(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_custom_rule(
        CustomRule(
            id="global-custom",
            rule_type="DOMAIN",
            value="custom.example.com",
            target_group="中等质量",
            category_name="",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)
    monkeypatch.setattr(hub, "get_nodes_for_token", lambda token: [])

    async def _fake_targeted_entries(target_resolver=None):
        return [
            {
                "line": "DOMAIN,custom.example.com,高质量-高倍率",
                "source_kind": "catalog",
                "category_name": "catalog-premium",
            },
            {
                "line": "DOMAIN,tier.example.com,DIRECT",
                "source_kind": "catalog",
                "category_name": "catalog-direct",
            },
            {
                "line": "DOMAIN,tier.example.com,高质量-高倍率",
                "source_kind": "catalog",
                "category_name": "catalog-premium-tier",
            },
            {
                "line": "DOMAIN-SUFFIX,heiyu.space,高质量-高倍率",
                "source_kind": "catalog",
                "category_name": "catalog-system-conflict",
            },
            {
                "line": "IP-CIDR,198.18.0.0/15,中等质量,no-resolve",
                "source_kind": "catalog",
                "category_name": "catalog-ip-medium",
            },
            {
                "line": "IP-CIDR,198.18.0.0/15,高质量-低倍率,no-resolve",
                "source_kind": "catalog",
                "category_name": "catalog-ip-standard",
            },
            {
                "line": "IP-CIDR,198.18.0.0/15,高质量-低倍率,no-resolve",
                "source_kind": "catalog",
                "category_name": "catalog-ip-duplicate",
            },
        ]

    monkeypatch.setattr(hub.rule_catalog, "get_targeted_rule_entries", _fake_targeted_entries)

    ir = asyncio.run(hub.build_policy_ir_for_token("tok-precedence"))
    assert ir is not None

    rendered_lines = [entry.to_line() for entry in ir.rule_entries]
    assert "DOMAIN,custom.example.com,中等质量" in rendered_lines
    assert "DOMAIN,custom.example.com,高质量-高倍率" not in rendered_lines
    assert "DOMAIN,tier.example.com,高质量-高倍率" in rendered_lines
    assert "DOMAIN,tier.example.com,DIRECT" not in rendered_lines
    assert "DOMAIN-SUFFIX,heiyu.space,DIRECT" in rendered_lines
    assert "DOMAIN-SUFFIX,heiyu.space,高质量-高倍率" not in rendered_lines
    assert "IP-CIDR,198.18.0.0/15,高质量-低倍率,no-resolve" in rendered_lines
    assert "IP-CIDR,198.18.0.0/15,中等质量,no-resolve" not in rendered_lines

    warning_codes = [item.code for item in ir.warnings]
    assert warning_codes.count("conflicting-rule-target") >= 4
    assert "duplicate-ip-rule" in warning_codes


def test_high_quality_airport_source_auto_splits_and_warns(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_standard_source(
        StandardSource(
            id="s-high",
            name="高质量机场A",
            clash_url="https://x/clash",
            shadowrocket_url="https://x/sr",
            quality_group="高质量机场",
            enabled=True,
        )
    )

    async def _fake_high_quality_fetch(*args, **kwargs):
        nodes = [
            NodeRecord(
                name="[高质量机场A] 双线 · 10x · 广港 IEPL",
                host="h10.example.com",
                port=443,
                protocol="trojan",
                source_id="s-high",
                source_type="standard",
            ),
            NodeRecord(
                name="[高质量机场A] 电信 · 2.3x · 广东隧道",
                host="h23.example.com",
                port=443,
                protocol="trojan",
                source_id="s-high",
                source_type="standard",
            ),
            NodeRecord(
                name="[高质量机场A] 双线 · 未知倍率 · 广港 IEPL",
                host="unknown.example.com",
                port=443,
                protocol="trojan",
                source_id="s-high",
                source_type="standard",
            ),
        ]
        return SourcePullResult(ok=True, method="clash", node_count=len(nodes), nodes=nodes)

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)
    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _fake_high_quality_fetch)

    import asyncio

    runtime = asyncio.run(hub.refresh(force=True))
    nodes = repo.load_standard_node_cache("s-high")
    assert len(nodes) == 2
    groups = {item.quality_group for item in nodes}
    assert groups == {QUALITY_HIGH_STANDARD, QUALITY_HIGH_PREMIUM}
    assert all(item.host != "unknown.example.com" for item in nodes)
    assert all(item.name.startswith("[高质量机场A] 🇺🇸 美国 · ") for item in nodes)

    status = runtime.source_status["standard"]["s-high"]
    assert status["unrecognized_multiplier_count"] == 1
    assert status["unrecognized_examples"] == ["[高质量机场A] 双线 · 未知倍率 · 广港 IEPL"]


def test_refresh_one_standard_source_reports_filtered_technical_nodes(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_standard_source(
        StandardSource(
            id="s1",
            name="机场A",
            clash_url="https://x/clash",
            shadowrocket_url="https://x/sr",
            quality_group="中等质量",
            enabled=True,
        )
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    async def _fetch_with_technical_nodes(*args, **kwargs):
        nodes = [
            NodeRecord(
                name="[机场A] Traffic: 2.29 GB | 20 GB",
                host="traffic.example.com",
                port=443,
                protocol="http",
                source_id="s1",
                source_type="standard",
            ),
            NodeRecord(
                name="[机场A] 日本 01",
                host="jp.example.com",
                port=443,
                protocol="http",
                source_id="s1",
                source_type="standard",
            ),
        ]
        return SourcePullResult(
            ok=True,
            method="clash",
            node_count=1,
            nodes=[nodes[1]],
            filtered_technical_count=1,
            filtered_technical_examples=[nodes[0].name],
        )

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _fetch_with_technical_nodes)

    result = asyncio.run(hub.refresh_one_standard_source("s1", trigger="manual"))
    assert result["ok"] is True
    assert result["filtered_technical_count"] == 1
    assert result["filtered_technical_examples"] == ["[机场A] Traffic: 2.29 GB | 20 GB"]

    cached = repo.load_standard_node_cache("s1")
    assert len(cached) == 1
    assert cached[0].name == "[机场A] 日本 01"

    runtime_item = hub.runtime.source_status["standard"]["s1"]
    assert runtime_item["filtered_technical_count"] == 1
    assert runtime_item["filtered_technical_examples"] == ["[机场A] Traffic: 2.29 GB | 20 GB"]


def test_refresh_one_manual_nodes_source_parses_uri_text_and_skips_network_fetch(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_standard_source(
        StandardSource(
            id="s-manual",
            name="自建节点",
            target_contract_id="medium",
            ingest_kind="manual_nodes",
            manual_nodes_text=(
                "vless://uuid-1@manual.example.com:443?encryption=none&security=reality"
                "&pbk=pub-key-1&sid=short-1&type=tcp#Fast%20Lane\n"
                "not-a-node\n"
            ),
            enabled=True,
        )
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    async def _unexpected_fetch(*args, **kwargs):
        raise AssertionError("manual_nodes ingest should not use remote fetch_source")

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _unexpected_fetch)

    result = asyncio.run(hub.refresh_one_standard_source("s-manual", trigger="manual"))
    assert result["ok"] is True
    assert result["pull_method"] == "manual_nodes"
    assert result["pull_node_count"] == 1

    cached = repo.load_standard_node_cache("s-manual")
    assert cached is not None
    assert len(cached) == 1
    assert cached[0].protocol == "vless"
    assert cached[0].quality_group == QUALITY_MEDIUM


def test_refresh_one_standard_source_failure_keeps_last_success_and_cache(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_standard_source(
        StandardSource(
            id="s1",
            name="机场A",
            clash_url="https://x/clash",
            shadowrocket_url="https://x/sr",
            quality_group="中等质量",
            enabled=True,
        )
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    async def _success_fetch(*args, **kwargs):
        nodes = [
            NodeRecord(
                name="[机场A] ok",
                host="ok.example.com",
                port=443,
                protocol="http",
                source_id="s1",
                source_type="standard",
            )
        ]
        return SourcePullResult(ok=True, method="clash", node_count=1, nodes=nodes)

    async def _failure_fetch(*args, **kwargs):
        return SourcePullResult(ok=False, error="clash: timeout", attempts=[])

    import asyncio

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _success_fetch)
    first = asyncio.run(hub.refresh_one_standard_source("s1"))
    assert first["ok"] is True

    source_after_success = repo.get_standard_source("s1")
    assert source_after_success is not None
    assert source_after_success.last_success_at
    assert source_after_success.last_pull_ok is True
    assert source_after_success.last_pull_node_count == 1
    cached_after_success = repo.load_standard_node_cache("s1")
    assert cached_after_success and len(cached_after_success) == 1
    success_at = source_after_success.last_success_at

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _failure_fetch)
    second = asyncio.run(hub.refresh_one_standard_source("s1"))
    assert second["ok"] is False
    assert second["pull_node_count"] == 1
    assert second["cached_node_count"] == 1

    source_after_failure = repo.get_standard_source("s1")
    assert source_after_failure is not None
    assert source_after_failure.last_pull_ok is False
    assert source_after_failure.last_success_at == success_at
    assert source_after_failure.last_pull_node_count == 1
    assert "timeout" in source_after_failure.last_pull_error
    cached_after_failure = repo.load_standard_node_cache("s1")
    assert cached_after_failure and len(cached_after_failure) == 1


def test_auto_pull_failure_marks_expired_and_success_clears(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_standard_source(
        StandardSource(
            id="s1",
            name="机场A",
            clash_url="https://x/clash",
            shadowrocket_url="https://x/sr",
            quality_group="中等质量",
            enabled=True,
        )
    )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    async def _failure_fetch(*args, **kwargs):
        return SourcePullResult(ok=False, error="expired", attempts=[])

    import asyncio

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _failure_fetch)
    for _ in range(STANDARD_SOURCE_AUTO_PULL_FAILURE_EXPIRED_THRESHOLD):
        asyncio.run(hub.refresh_standard_sources_only())

    source = repo.get_standard_source("s1")
    assert source is not None
    assert source.auto_pull_consecutive_failures == STANDARD_SOURCE_AUTO_PULL_FAILURE_EXPIRED_THRESHOLD
    assert source.auto_pull_expired is True
    assert source.auto_pull_expired_at

    asyncio.run(hub.refresh_standard_sources_only())
    source_more = repo.get_standard_source("s1")
    assert source_more is not None
    assert (
        source_more.auto_pull_consecutive_failures
        == STANDARD_SOURCE_AUTO_PULL_FAILURE_EXPIRED_THRESHOLD + 1
    )
    assert source_more.auto_pull_expired is True

    async def _success_fetch(*args, **kwargs):
        nodes = [
            NodeRecord(
                name="[机场A] ok",
                host="ok.example.com",
                port=443,
                protocol="http",
                source_id="s1",
                source_type="standard",
            )
        ]
        return SourcePullResult(ok=True, method="clash", node_count=1, nodes=nodes)

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _success_fetch)
    asyncio.run(hub.refresh_standard_sources_only())
    source_after_success = repo.get_standard_source("s1")
    assert source_after_success is not None
    assert source_after_success.auto_pull_consecutive_failures == 0
    assert source_after_success.auto_pull_expired is False
    assert source_after_success.auto_pull_expired_at is None


def test_manual_failure_not_increment_and_manual_success_clears_expired(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_standard_source(
        StandardSource(
            id="s1",
            name="机场A",
            clash_url="https://x/clash",
            shadowrocket_url="https://x/sr",
            quality_group="中等质量",
            enabled=True,
        )
    )
    for idx in range(STANDARD_SOURCE_AUTO_PULL_FAILURE_EXPIRED_THRESHOLD):
        repo.save_standard_source_pull_status(
            "s1",
            attempt_at=f"2026-01-01T00:00:{idx:02d}Z",
            ok=False,
            method="",
            node_count=0,
            error="expired",
            trigger="auto",
        )

    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    async def _failure_fetch(*args, **kwargs):
        return SourcePullResult(ok=False, error="manual failed", attempts=[])

    import asyncio

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _failure_fetch)
    asyncio.run(hub.refresh_one_standard_source("s1", trigger="manual"))
    source_after_manual_failure = repo.get_standard_source("s1")
    assert source_after_manual_failure is not None
    assert (
        source_after_manual_failure.auto_pull_consecutive_failures
        == STANDARD_SOURCE_AUTO_PULL_FAILURE_EXPIRED_THRESHOLD
    )
    assert source_after_manual_failure.auto_pull_expired is True

    async def _success_fetch(*args, **kwargs):
        nodes = [
            NodeRecord(
                name="[机场A] ok",
                host="ok.example.com",
                port=443,
                protocol="http",
                source_id="s1",
                source_type="standard",
            )
        ]
        return SourcePullResult(ok=True, method="clash", node_count=1, nodes=nodes)

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _success_fetch)
    asyncio.run(hub.refresh_one_standard_source("s1", trigger="manual"))
    source_after_manual_success = repo.get_standard_source("s1")
    assert source_after_manual_success is not None
    assert source_after_manual_success.auto_pull_consecutive_failures == 0
    assert source_after_manual_success.auto_pull_expired is False
    assert source_after_manual_success.auto_pull_expired_at is None


def test_standard_source_config_fingerprint_stable_and_sensitive_to_network_mode() -> None:
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url=" https://example.com/clash ",
        shadowrocket_url="https://example.com/sr",
        surge_url="https://example.com/surge",
        login_url="https://example.com/login",
        quality_group="中等质量",
        enabled=True,
        pull_network_mode="direct_only",
    )
    same = StandardSource(
        id="s2",
        name="机场A",
        clash_url="https://example.com/clash",
        shadowrocket_url="https://example.com/sr",
        surge_url="https://example.com/surge",
        login_url="https://example.com/login",
        quality_group="中等质量",
        enabled=True,
        pull_network_mode="direct_only",
    )
    changed = StandardSource(
        id="s3",
        name="机场A",
        clash_url="https://example.com/clash",
        shadowrocket_url="https://example.com/sr",
        surge_url="https://example.com/surge",
        login_url="https://example.com/login",
        quality_group="中等质量",
        enabled=True,
        pull_network_mode="direct_then_proxy",
    )

    assert source.config_fingerprint() == same.config_fingerprint()
    assert source.config_fingerprint() != changed.config_fingerprint()


def test_successful_pull_tracks_last_success_config_fingerprint_and_failure_preserves_it(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash",
        shadowrocket_url="https://example.com/sr",
        quality_group="中等质量",
        enabled=True,
        pull_network_mode="direct_only",
    )
    repo.save_standard_source(source)
    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    async def _success_fetch(*args, **kwargs):
        return SourcePullResult(
            ok=True,
            method="clash",
            node_count=1,
            nodes=[
                NodeRecord(
                    name="[机场A] ok",
                    host="ok.example.com",
                    port=443,
                    protocol="http",
                    source_id="s1",
                    source_type="standard",
                )
            ],
        )

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _success_fetch)
    asyncio.run(hub.refresh_one_standard_source("s1", trigger="manual"))

    saved = repo.get_standard_source("s1")
    assert saved is not None
    first_fingerprint = saved.config_fingerprint()
    assert saved.last_success_config_fingerprint == first_fingerprint

    saved.pull_network_mode = "direct_then_proxy"
    repo.save_standard_source(saved)

    async def _failure_fetch(*args, **kwargs):
        return SourcePullResult(ok=False, error="http 403", attempts=[])

    monkeypatch.setattr(hub.source_fetcher, "fetch_source", _failure_fetch)
    asyncio.run(hub.refresh_one_standard_source("s1", trigger="manual"))

    failed = repo.get_standard_source("s1")
    assert failed is not None
    assert failed.config_fingerprint() != first_fingerprint
    assert failed.last_success_config_fingerprint == first_fingerprint


def test_update_standard_source_refresh_policy_wakes_background_loop(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    assert hub._standard_source_policy_event.is_set() is False

    policy = hub.update_standard_source_refresh_policy(enabled=True, interval_minutes=1)

    assert policy["standard_source_auto_pull_enabled"] is True
    assert policy["standard_source_auto_pull_interval_minutes"] == 1
    assert hub._standard_source_policy_event.is_set() is True


def test_ensure_started_non_blocking_triggers_startup_refresh(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    refresh_started = asyncio.Event()
    refresh_unblock = asyncio.Event()

    async def _slow_refresh(*args, **kwargs):
        refresh_started.set()
        await refresh_unblock.wait()
        return hub.runtime

    monkeypatch.setattr(hub, "refresh", _slow_refresh)

    async def _run() -> None:
        await asyncio.wait_for(hub.ensure_started(), timeout=0.3)
        assert hub._startup_refresh_task is not None
        assert hub._startup_refresh_task.done() is False
        await asyncio.wait_for(refresh_started.wait(), timeout=0.3)
        refresh_unblock.set()
        await asyncio.wait_for(hub._startup_refresh_task, timeout=0.3)
        await hub.shutdown()

    asyncio.run(_run())


def test_ensure_started_idempotent_task_creation(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    refresh_unblock = asyncio.Event()

    async def _slow_refresh(*args, **kwargs):
        await refresh_unblock.wait()
        return hub.runtime

    monkeypatch.setattr(hub, "refresh", _slow_refresh)

    async def _run() -> None:
        await hub.ensure_started()
        startup_task = hub._startup_refresh_task
        background_task = hub._background_task
        standard_task = hub._standard_source_task

        await hub.ensure_started()
        assert hub._startup_refresh_task is startup_task
        assert hub._background_task is background_task
        assert hub._standard_source_task is standard_task

        refresh_unblock.set()
        await asyncio.wait_for(hub._startup_refresh_task, timeout=0.3)
        await hub.shutdown()

    asyncio.run(_run())


def test_shutdown_cancels_startup_refresh_task(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    gorelay = GorelayService(settings, repo)
    hub = HubService(settings, repo, RuleCatalog(settings, repo), SourceFetcher(settings), gorelay)

    refresh_started = asyncio.Event()
    refresh_unblock = asyncio.Event()

    async def _slow_refresh(*args, **kwargs):
        refresh_started.set()
        await refresh_unblock.wait()
        return hub.runtime

    monkeypatch.setattr(hub, "refresh", _slow_refresh)

    async def _run() -> None:
        await hub.ensure_started()
        await asyncio.wait_for(refresh_started.wait(), timeout=0.3)
        await hub.shutdown()
        assert hub._startup_refresh_task is None
        assert hub._background_task is None
        assert hub._standard_source_task is None

    asyncio.run(_run())
