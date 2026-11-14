from __future__ import annotations

import sqlite3

import pytest

from app.config import Settings
from app.models import (
    BUSINESS_GROUP_MODE_AD_BLOCK,
    GoRelayAccount,
    GoRelayAccountSnapshot,
    GoRelayAccountSnapshotPayload,
    NodeRecord,
    RouteContract,
    RouteContractView,
    RuleCategory,
    ScenarioProfile,
    ServiceCatalogEntry,
    StandardSource,
)
from app.services.route_contract_views import scenario_route_contract
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


def test_sqlite_repo_backfills_pin_group_mode_column_for_legacy_db(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "subhub.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE pin_groups (
            group_name TEXT PRIMARY KEY,
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO pin_groups (group_name, sort_order, updated_at) VALUES (?, ?, ?)",
        ("广告拦截", 0, "2026-03-09T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    repo = SqliteRepo(_settings(tmp_path))
    columns = {
        row["name"]
        for row in repo._conn.execute("PRAGMA table_info(pin_groups)").fetchall()
    }
    assert "mode" in columns
    assert "description" in columns
    groups = repo.list_pin_groups()
    assert groups[0]["group_name"] == "广告拦截"
    assert groups[0]["mode"] == "standard"
    assert groups[0]["description"] == ""


def test_sqlite_repo_pin_group_mode_does_not_overwrite_stored_contract(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1)]
    )
    repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="",
            contract_id="hq_premium",
            sort_order=0,
            source="manual",
        )
    )
    assert repo.create_pin_group(
        "广告拦截",
        mode=BUSINESS_GROUP_MODE_AD_BLOCK,
        description="广告相关分类",
    )

    repo.pin_category("OpenAI", "广告拦截")

    entry = repo.get_service_catalog_entry("OpenAI")
    assert entry is not None
    assert entry.contract_id == "hq_premium"
    assert entry.catalog_group == "广告拦截"

    groups = {item["group_name"]: item for item in repo.list_pin_groups()}
    assert groups["广告拦截"]["mode"] == BUSINESS_GROUP_MODE_AD_BLOCK
    assert groups["广告拦截"]["description"] == "广告相关分类"


def test_sqlite_repo_backfill_restores_catalog_group_from_pins_without_overwriting_contract(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1)]
    )
    repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="hq_premium",
            sort_order=3,
            source="manual",
        )
    )

    with repo._lock:
        repo._conn.execute(
            "UPDATE service_catalog_entries SET catalog_group='' WHERE category_name=?",
            ("OpenAI",),
        )
        repo._conn.commit()

    repo._backfill_service_catalog_entries()

    entry = repo.get_service_catalog_entry("OpenAI")
    assert entry is not None
    assert entry.catalog_group == "AI 服务"
    assert entry.contract_id == "hq_premium"
    assert entry.sort_order == 3


def test_sqlite_repo_bulk_update_scenario_service_catalog_groups_preserves_contract_and_allows_empty(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories(
        [
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1),
            RuleCategory(name="Notion", assigned_group="", rule_count=1),
        ]
    )
    repo.save_scenario_service_catalog_entry(
        "scenario-work",
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="旧分组",
            contract_id="hq_premium",
            sort_order=7,
            source="manual",
        )
    )

    updated = repo.bulk_update_scenario_service_catalog_groups(
        "scenario-work",
        {"OpenAI": "AI 服务", "Notion": ""},
    )

    assert updated == 2
    entries = {
        item.category_name: item for item in repo.list_scenario_service_catalog_entries("scenario-work")
    }
    assert entries["OpenAI"].catalog_group == "AI 服务"
    assert entries["OpenAI"].contract_id == "hq_premium"
    assert entries["OpenAI"].sort_order == 7
    assert "Notion" not in entries


def test_sqlite_repo_bulk_update_service_catalog_groups_preserves_contract_and_syncs_default_scenario(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories(
        [
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1),
            RuleCategory(name="Notion", assigned_group="", rule_count=1),
        ]
    )
    repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="旧分组",
            contract_id="hq_premium",
            sort_order=7,
            source="manual",
        )
    )

    updated = repo.bulk_update_service_catalog_groups(
        {"OpenAI": "AI 服务", "Notion": ""}
    )

    assert updated == 2
    entries = {item.category_name: item for item in repo.list_service_catalog_entries()}
    assert entries["OpenAI"].catalog_group == "AI 服务"
    assert entries["OpenAI"].contract_id == "hq_premium"
    assert entries["OpenAI"].sort_order == 7

    default_entries = {
        item.category_name: item for item in repo.list_scenario_service_catalog_entries("scenario-default")
    }
    assert default_entries["OpenAI"].catalog_group == "AI 服务"
    assert default_entries["OpenAI"].contract_id == "hq_premium"

    pins = {item["category_name"]: item for item in repo.list_pinned_categories()}
    assert pins["OpenAI"]["pin_group"] == "AI 服务"
    assert pins["OpenAI"]["sort_order"] == 7
    assert "Notion" not in pins


def test_sqlite_repo_load_all_gorelay_cached_nodes_tolerates_bad_rows(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_gorelay_node_cache(
        "acc-a",
        "mac",
        "Mac",
        [
            NodeRecord(
                name="n1",
                host="a.example.com",
                port=443,
                protocol="http",
                quality_group="高质量-高倍率",
                source_id="acc-a",
            )
        ],
    )
    repo.save_gorelay_node_cache(
        "acc-b",
        "ipad",
        "iPad",
        [
            NodeRecord(
                name="n1-dup",
                host="a.example.com",
                port=443,
                protocol="http",
                quality_group="高质量-高倍率",
                source_id="acc-b",
            )
        ],
    )

    with repo._lock:
        repo._conn.execute(
            """
            INSERT OR REPLACE INTO gorelay_node_cache (source_id, device_key, nodes_json, device_name, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("acc-bad-1", "bad-1", "{invalid-json", "Bad 1", "2026-03-09T00:00:00Z"),
        )
        repo._conn.execute(
            """
            INSERT OR REPLACE INTO gorelay_node_cache (source_id, device_key, nodes_json, device_name, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "acc-bad-2",
                "bad-2",
                '[{"name":"bad","host":"b.example.com","port":443,"protocol":"http","extra":"x"}]',
                "Bad 2",
                "2026-03-09T00:00:00Z",
            ),
        )
        repo._conn.commit()

    nodes = repo.load_all_gorelay_cached_nodes()
    assert len(nodes) == 2
    assert {node.source_id for node in nodes} == {"acc-a", "acc-b"}
    assert all(node.host == "a.example.com" for node in nodes)


def test_sqlite_repo_list_pool_statuses_reads_active_snapshot_nodes(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_gorelay_account(
        GoRelayAccount(
            id="acc-a",
            name="主账号",
            login_url="https://relay.example.com",
            enabled=True,
        )
    )
    repo.save_gorelay_account(
        GoRelayAccount(
            id="acc-disabled",
            name="禁用账号",
            login_url="https://relay.example.com",
            enabled=False,
        )
    )
    repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="acc-a",
                snapshot_id="snap-a",
                created_at="2026-03-09T00:00:00Z",
                node_count=3,
                device_count=2,
                status="success",
            ),
            collected_rules=[],
            device_nodes={
                "mac": [
                    NodeRecord(
                        name="n1",
                        host="a.example.com",
                        port=443,
                        protocol="http",
                        quality_group="高质量-高倍率",
                        source_id="acc-a",
                    ),
                    NodeRecord(
                        name="n1-dup",
                        host="a.example.com",
                        port=443,
                        protocol="http",
                        quality_group="高质量-高倍率",
                        source_id="acc-a",
                    ),
                ],
                "ipad": [
                    NodeRecord(
                        name="n2",
                        host="b.example.com",
                        port=443,
                        protocol="http",
                        quality_group="高质量-低倍率",
                        source_id="acc-a",
                    ),
                    NodeRecord(
                        name="n3",
                        host="c.example.com",
                        port=443,
                        protocol="http",
                        quality_group="中等质量",
                        source_id="acc-a",
                    ),
                ],
            },
            device_names={"mac": "Mac", "ipad": "iPad"},
            pending_bindings=[],
            source_status={},
        )
    )
    repo.save_gorelay_active_snapshot_id("acc-a", "snap-a")
    repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="acc-disabled",
                snapshot_id="snap-disabled",
                created_at="2026-03-09T00:00:00Z",
                node_count=1,
                device_count=1,
                status="success",
            ),
            collected_rules=[],
            device_nodes={
                "mac": [
                    NodeRecord(
                        name="disabled",
                        host="z.example.com",
                        port=443,
                        protocol="http",
                        quality_group="高质量-高倍率",
                        source_id="acc-disabled",
                    ),
                ]
            },
            device_names={"mac": "Mac"},
            pending_bindings=[],
            source_status={},
        )
    )
    repo.save_gorelay_active_snapshot_id("acc-disabled", "snap-disabled")
    repo.save_standard_source(
        StandardSource(
            id="std-1",
            name="标准源",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            enabled=True,
        )
    )
    repo.save_standard_node_cache(
        "std-1",
        [
            NodeRecord(
                name="bulk",
                host="bulk.example.com",
                port=443,
                protocol="http",
                quality_group="低质量大流量",
                source_id="std-1",
            )
        ],
    )
    with repo._lock:
        repo._conn.execute(
            """
            INSERT OR REPLACE INTO gorelay_node_cache (source_id, device_key, nodes_json, device_name, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("acc-bad", "bad", "{invalid-json", "Bad", "2026-03-09T00:00:00Z"),
        )
        repo._conn.commit()

    pools = repo.list_pool_statuses()
    assert len(pools) == 6
    by_id = {item.id: item for item in pools}
    assert by_id["hq_premium"].node_count == 1
    assert by_id["hq_standard"].node_count == 1
    assert by_id["medium"].node_count == 1
    assert by_id["bulk"].node_count == 1
    assert by_id["chain_home"].node_count == 0


def test_sqlite_repo_seeds_safer_default_route_contracts_for_new_db(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))

    by_id = {item.id: item for item in repo.list_route_contracts()}
    assert by_id["hq_premium"].strategy_type == "failover"
    assert by_id["hq_premium"].failure_action == "interrupt"
    assert by_id["hq_premium"].fallback_pools == ["hq_standard", "chain_home"]
    assert by_id["hq_standard"].strategy_type == "failover"
    assert by_id["hq_standard"].failure_action == "interrupt"
    assert by_id["hq_standard"].fallback_pools == ["hq_premium", "chain_home"]
    assert by_id["medium"].strategy_type == "strict"
    assert by_id["medium"].failure_action == "interrupt"
    assert by_id["medium"].fallback_pools == []
    assert by_id["bulk"].strategy_type == "strict"
    assert by_id["bulk"].failure_action == "interrupt"
    assert by_id["bulk"].fallback_pools == []
    assert by_id["chain_home"].strategy_type == "strict"
    assert by_id["chain_home"].failure_action == "interrupt"
    assert by_id["chain_home"].fallback_pools == []


def test_sqlite_repo_preserves_editable_route_contract_metadata_across_reload(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_route_contract(
        RouteContract(
            id="hq_standard",
            display_name="高质量低延迟",
            description="适合 AI / 实时 API / 低延迟场景",
            strategy_type="failover",
            primary_pools=["hq_standard"],
            fallback_pools=["hq_premium", "chain_home"],
            failure_action="interrupt",
            enabled=True,
        )
    )

    repo_reloaded = SqliteRepo(settings)
    contract = repo_reloaded.get_route_contract("hq_standard")
    assert contract is not None
    assert contract.display_name == "高质量低延迟"
    assert contract.description == "适合 AI / 实时 API / 低延迟场景"
    assert contract.strategy_type == "failover"
    assert contract.failure_action == "interrupt"
    assert contract.primary_pools == ["hq_standard"]
    assert contract.fallback_pools == ["hq_premium", "chain_home"]


def test_sqlite_repo_preserves_scenario_default_contract_view_across_reload(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    medium = next(
        item for item in repo.list_scenario_route_contract_views("scenario-default") if item.contract_id == "medium"
    )
    medium.is_default = True
    repo.save_scenario_route_contract_view("scenario-default", medium)

    repo_reloaded = SqliteRepo(settings)
    by_id = {
        item.contract_id: item for item in repo_reloaded.list_scenario_route_contract_views("scenario-default")
    }
    assert by_id["medium"].is_default is True
    assert by_id["chain_home"].is_default is False


def test_sqlite_repo_backfills_contract_views_for_preexisting_scenarios(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work")
    )
    medium = next(
        item for item in repo.list_scenario_route_contract_views("scenario-default") if item.contract_id == "medium"
    )
    medium.display_name = "默认中转"
    repo.save_scenario_route_contract_view("scenario-default", medium)

    repo_reloaded = SqliteRepo(settings)
    default_views = {
        item.contract_id: item for item in repo_reloaded.list_scenario_route_contract_views("scenario-default")
    }
    work_views = repo_reloaded.list_scenario_route_contract_views("scenario-work")
    assert work_views == []
    inherited_medium = scenario_route_contract(repo_reloaded, "scenario-work", "medium")
    assert inherited_medium is not None
    assert inherited_medium.display_name == "默认中转"

    hq_standard = default_views["hq_standard"]
    hq_standard.display_name = "办公高质"
    hq_standard.scenario_id = "scenario-work"
    repo_reloaded.save_scenario_route_contract_view("scenario-work", hq_standard)

    updated_work_views = {
        item.contract_id: item for item in repo_reloaded.list_scenario_route_contract_views("scenario-work")
    }
    assert updated_work_views["hq_standard"].display_name == "办公高质"
    assert "medium" not in updated_work_views


def test_sqlite_repo_reload_does_not_seed_scenario_owned_contracts_into_default_views(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work")
    )
    repo.create_route_contract(
        RouteContract(
            id="scenario-work-bulk",
            display_name="工作下载",
            description="工作场景私有契约",
            strategy_type="strict",
            primary_pools=["bulk"],
            fallback_pools=[],
            failure_action="interrupt",
            editable=True,
            enabled=True,
            sort_order=21,
            owner_scenario_id="scenario-work",
            is_system=False,
        )
    )
    repo.save_scenario_route_contract_view(
        "scenario-work",
        RouteContractView(
            scenario_id="scenario-work",
            contract_id="scenario-work-bulk",
            display_name="工作下载",
            description="工作场景私有契约",
            enabled=True,
            sort_order=21,
            is_default=False,
        ),
    )

    repo_reloaded = SqliteRepo(settings)
    default_view_ids = {
        item.contract_id for item in repo_reloaded.list_scenario_route_contract_views("scenario-default")
    }
    work_view_ids = {
        item.contract_id for item in repo_reloaded.list_scenario_route_contract_views("scenario-work")
    }

    assert "scenario-work-bulk" not in default_view_ids
    assert "scenario-work-bulk" in work_view_ids


def test_sqlite_repo_allows_default_to_be_cleared_without_hidden_fallback(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    medium = next(
        item for item in repo.list_scenario_route_contract_views("scenario-default") if item.contract_id == "medium"
    )
    medium.is_default = True
    repo.save_scenario_route_contract_view("scenario-default", medium)

    chain_home = next(
        item for item in repo.list_scenario_route_contract_views("scenario-default") if item.contract_id == "chain_home"
    )
    chain_home.is_default = False
    chain_home.enabled = False
    repo.save_scenario_route_contract_view("scenario-default", chain_home)

    medium.enabled = False
    medium.is_default = False
    repo.save_scenario_route_contract_view("scenario-default", medium)

    by_id = {
        item.contract_id: item for item in repo.list_scenario_route_contract_views("scenario-default")
    }
    default_contracts = [item.contract_id for item in by_id.values() if item.is_default]
    assert default_contracts == []
    assert by_id["chain_home"].enabled is False
    assert by_id["medium"].enabled is False


def test_sqlite_repo_rejects_duplicate_route_contract_display_names(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    premium = repo.get_route_contract("hq_premium")
    medium = repo.get_route_contract("medium")
    assert premium is not None
    assert medium is not None

    repo.save_route_contract(
        RouteContract(
            id="hq_premium",
            display_name="通用组",
            description=premium.description,
            strategy_type=premium.strategy_type,
            primary_pools=premium.primary_pools,
            fallback_pools=premium.fallback_pools,
            failure_action=premium.failure_action,
            enabled=premium.enabled,
        )
    )

    with pytest.raises(ValueError, match="display_name already used by another contract"):
        repo.save_route_contract(
            RouteContract(
                id="medium",
                display_name="通用组",
                description=medium.description,
                strategy_type=medium.strategy_type,
                primary_pools=medium.primary_pools,
                fallback_pools=medium.fallback_pools,
                failure_action=medium.failure_action,
                enabled=medium.enabled,
            )
        )


def test_sqlite_repo_supports_global_and_scenario_custom_route_contracts(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_scenario(ScenarioProfile(id="scenario-work", slug="work", name="Work"))

    global_contract = repo.create_route_contract(
        RouteContract(
            id="custom-office",
            display_name="办公中转",
            description="全局办公契约",
            strategy_type="strict",
            primary_pools=["medium"],
            fallback_pools=[],
            failure_action="interrupt",
            editable=True,
            enabled=True,
            owner_scenario_id="",
            is_system=False,
        )
    )
    scenario_contract = repo.create_route_contract(
        RouteContract(
            id="scenario-work-focus",
            display_name="工作专用",
            description="场景私有契约",
            strategy_type="strict",
            primary_pools=["bulk"],
            fallback_pools=[],
            failure_action="interrupt",
            editable=True,
            enabled=True,
            owner_scenario_id="scenario-work",
            is_system=False,
        )
    )
    repo.save_scenario_route_contract_view(
        "scenario-default",
        RouteContractView(
            scenario_id="scenario-default",
            contract_id=global_contract.id,
            display_name=global_contract.display_name,
            description=global_contract.description,
            enabled=True,
            sort_order=7,
            is_default=False,
        ),
    )
    repo.save_scenario_route_contract_view(
        "scenario-work",
        RouteContractView(
            scenario_id="scenario-work",
            contract_id=scenario_contract.id,
            display_name=scenario_contract.display_name,
            description=scenario_contract.description,
            enabled=True,
            sort_order=8,
            is_default=False,
        ),
    )

    default_ids = {item.id for item in repo.list_route_contracts()}
    work_ids = {item.id for item in repo.list_route_contracts("scenario-work")}
    assert global_contract.id in default_ids
    assert scenario_contract.id not in default_ids
    assert global_contract.id in work_ids
    assert scenario_contract.id in work_ids

    work_contract = scenario_route_contract(repo, "scenario-work", scenario_contract.id)
    default_contract = scenario_route_contract(repo, "scenario-default", scenario_contract.id)
    assert work_contract is not None
    assert work_contract.scope() == "scenario"
    assert default_contract is None


def test_sqlite_repo_allows_same_custom_contract_display_name_in_different_scenarios(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_scenario(ScenarioProfile(id="scenario-work", slug="work", name="Work"))
    repo.save_scenario(ScenarioProfile(id="scenario-home", slug="home", name="Home"))

    work_contract = repo.create_route_contract(
        RouteContract(
            id="scenario-work-relay",
            display_name="共享名字",
            strategy_type="strict",
            primary_pools=["medium"],
            fallback_pools=[],
            failure_action="interrupt",
            editable=True,
            enabled=True,
            owner_scenario_id="scenario-work",
            is_system=False,
        )
    )
    home_contract = repo.create_route_contract(
        RouteContract(
            id="scenario-home-relay",
            display_name="共享名字",
            strategy_type="strict",
            primary_pools=["bulk"],
            fallback_pools=[],
            failure_action="interrupt",
            editable=True,
            enabled=True,
            owner_scenario_id="scenario-home",
            is_system=False,
        )
    )

    assert work_contract.display_name == "共享名字"
    assert home_contract.display_name == "共享名字"


def test_sqlite_repo_rejects_cross_quality_route_contract_policy(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))

    with pytest.raises(ValueError, match="proxy contract pools must stay within one quality family"):
        repo.save_route_contract(
            RouteContract(
                id="hq_standard",
                display_name="高质量-低倍率",
                strategy_type="failover",
                primary_pools=["hq_standard"],
                fallback_pools=["medium"],
                failure_action="interrupt",
                enabled=True,
            )
        )

    repurposed = repo.save_route_contract(
        RouteContract(
            id="medium",
            display_name="中等质量",
            strategy_type="strict",
            primary_pools=["hq_standard"],
            fallback_pools=[],
            failure_action="interrupt",
            enabled=True,
        )
    )
    assert repurposed.primary_pools == ["hq_standard"]


def test_sqlite_repo_pins_existing_mihomo_profiles_to_legacy_mainline_before_new_defaults(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    with repo._lock:
        repo._conn.execute(
            "UPDATE general_profiles SET settings_json=? WHERE id=?",
            ('{"clash_dns_enable":true}', "lazycat-default"),
        )
        repo._conn.execute(
            "UPDATE scenario_profiles SET settings_json=? WHERE id=?",
            ('{"clash_dns_enable":true}', "scenario-default"),
        )
        repo._conn.execute(
            "UPDATE lazycat_profile_settings SET settings_json=? WHERE id=1",
            ('{"clash_dns_enable":true}',),
        )
        repo._conn.commit()
        repo._conn.close()

    repo_reloaded = SqliteRepo(settings)
    general = repo_reloaded.get_default_general_profile()
    scenario = repo_reloaded.get_scenario("scenario-default")
    assert general is not None
    assert scenario is not None

    for item in (general.settings, scenario.settings):
        assert item["clash_dns_enhanced_mode"] == "fake-ip"
        assert item["clash_dns_use_hosts"] is False
        assert item["clash_dns_proxy_server_nameserver"] == []
        assert item["clash_tun_enable"] is True
        assert item["clash_tun_dns_hijack"] == ["any:53", "tcp://any:53"]
        assert item["clash_profile_store_fake_ip"] is True
        assert item["clash_dns_respect_rules"] is False
        assert item["clash_sniffer_force_dns_mapping"] is True


def test_sqlite_repo_keeps_explicit_redir_host_profiles_on_new_mainline_defaults(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    with repo._lock:
        repo._conn.execute(
            "UPDATE general_profiles SET settings_json=? WHERE id=?",
            ('{"clash_dns_enable":true,"clash_dns_enhanced_mode":"redir-host"}', "lazycat-default"),
        )
        repo._conn.execute(
            "UPDATE scenario_profiles SET settings_json=? WHERE id=?",
            ('{"clash_dns_enable":true,"clash_dns_enhanced_mode":"redir-host"}', "scenario-default"),
        )
        repo._conn.execute(
            "UPDATE lazycat_profile_settings SET settings_json=? WHERE id=1",
            ('{"clash_dns_enable":true,"clash_dns_enhanced_mode":"redir-host"}',),
        )
        repo._conn.commit()
        repo._conn.close()

    repo_reloaded = SqliteRepo(settings)
    general = repo_reloaded.get_default_general_profile()
    scenario = repo_reloaded.get_scenario("scenario-default")
    assert general is not None
    assert scenario is not None

    for item in (general.settings, scenario.settings):
        assert item["clash_dns_enhanced_mode"] == "redir-host"
        assert item["clash_dns_use_hosts"] is True
        assert item["clash_dns_proxy_server_nameserver"] == ["223.5.5.5", "119.29.29.29"]
        assert item["clash_tun_enable"] is False
        assert item["clash_profile_store_fake_ip"] is False
        assert item["clash_dns_respect_rules"] is True
        assert item["clash_sniffer_force_dns_mapping"] is False


def test_standard_source_persists_manual_ingest_fields(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_standard_source(
        StandardSource(
            id="manual-1",
            name="自建节点源",
            target_contract_id="medium",
            ingest_kind="manual_nodes",
            manual_nodes_text="trojan://secret@manual.example.com:443?sni=example.com#Manual",
            enabled=True,
        )
    )

    saved = repo.get_standard_source("manual-1")
    assert saved is not None
    assert saved.resolved_ingest_kind() == "manual_nodes"
    assert saved.manual_nodes_text.startswith("trojan://secret")
    assert saved.clash_url == ""
