from __future__ import annotations

import sqlite3

import pytest

from app.config import Settings
from app.models import (
    CONTRACT_AD_BLOCK,
    CONTRACT_DIRECT,
    CONTRACT_MEDIUM,
    ROUTE_ACTION_DIRECT,
    ROUTE_ACTION_PROXY,
    ROUTE_ACTION_REJECT,
    ROUTE_DIRECT_ACTION,
    ROUTE_NATIVE_DIRECT_TARGET,
    ROUTE_NATIVE_REJECT_TARGET,
    ROUTE_REJECT_ACTION,
    CustomRule,
    PolicyRuleEntry,
    RouteContract,
    effective_contract_id,
    resolve_contract_id,
)
from app.services.route_contract_views import scenario_default_contract_id
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


def test_initial_contract_templates_are_editable_and_do_not_resurrect(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)

    direct = repo.get_route_contract(CONTRACT_DIRECT)
    reject = repo.get_route_contract(CONTRACT_AD_BLOCK)
    assert direct is not None and direct.editable and not direct.is_system
    assert direct.routing_action == ROUTE_ACTION_DIRECT
    assert reject is not None and reject.editable and not reject.is_system
    assert reject.routing_action == ROUTE_ACTION_REJECT

    assert repo.delete_route_contract(CONTRACT_DIRECT)
    assert repo.delete_route_contract(CONTRACT_AD_BLOCK)
    assert repo.get_route_contract(CONTRACT_DIRECT) is None
    assert repo.get_route_contract(CONTRACT_AD_BLOCK) is None

    reloaded = SqliteRepo(settings)
    assert reloaded.get_route_contract(CONTRACT_DIRECT) is None
    assert reloaded.get_route_contract(CONTRACT_AD_BLOCK) is None
    assert scenario_default_contract_id(reloaded, "scenario-default") == "chain_home"


def test_deleting_the_default_contract_leaves_an_empty_default_after_reload(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    assert repo.delete_route_contract("chain_home")
    assert scenario_default_contract_id(repo, "scenario-default") == ""

    reloaded = SqliteRepo(settings)
    assert reloaded.get_route_contract("chain_home") is None
    assert scenario_default_contract_id(reloaded, "scenario-default") == ""


def test_legacy_route_contracts_migrate_once_without_rewriting_user_data(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    db_path = data_dir / "subhub.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE route_contracts (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            strategy_type TEXT NOT NULL DEFAULT 'strict',
            failure_action TEXT NOT NULL DEFAULT 'interrupt',
            editable INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            owner_scenario_id TEXT NOT NULL DEFAULT '',
            is_system INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE route_contract_pool_bindings (
            contract_id TEXT NOT NULL,
            role TEXT NOT NULL,
            pool_name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (contract_id, role, sort_order)
        );
        INSERT INTO route_contracts
            (id, display_name, description, strategy_type, failure_action, editable, enabled,
             sort_order, owner_scenario_id, is_system, updated_at)
        VALUES
            ('direct', '用户直连名', '保留说明', 'strict', 'interrupt', 0, 1, 0, '', 1, '2026-01-01'),
            ('ad_block', '用户拦截名', '保留拦截说明', 'strict', 'interrupt', 0, 1, 1, '', 1, '2026-01-01'),
            ('custom', '用户自定义', '不应被模板覆盖', 'strict', 'interrupt', 1, 1, 2, '', 0, '2026-01-01');
        INSERT INTO route_contract_pool_bindings (contract_id, role, pool_name, sort_order)
        VALUES ('direct', 'primary', 'direct', 0);
        """
    )
    conn.commit()
    conn.close()

    repo = SqliteRepo(_settings(tmp_path))
    direct = repo.get_route_contract("direct")
    reject = repo.get_route_contract("ad_block")
    custom = repo.get_route_contract("custom")
    assert direct is not None
    assert direct.display_name == "用户直连名"
    assert direct.primary_pools == ["direct"]
    assert direct.routing_action == ROUTE_ACTION_DIRECT
    assert direct.editable and not direct.is_system
    assert reject is not None and reject.routing_action == ROUTE_ACTION_REJECT
    assert reject.display_name == "用户拦截名"
    assert custom is not None and custom.routing_action == ROUTE_ACTION_PROXY
    assert custom.display_name == "用户自定义"

    # A second open must not reapply the migration or recreate deleted rows.
    assert repo.delete_route_contract("direct")
    reloaded = SqliteRepo(_settings(tmp_path))
    assert reloaded.get_route_contract("direct") is None


def test_routing_actions_are_separate_from_deletable_contract_ids(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    direct = repo.get_route_contract("direct")
    assert direct is not None

    # The legacy record can be repurposed as a normal proxy contract.
    direct.display_name = "中等质量代理"
    direct.routing_action = ROUTE_ACTION_PROXY
    direct.primary_pools = ["medium"]
    direct.fallback_pools = []
    saved = repo.save_route_contract(direct)
    assert saved.id == "direct"
    assert saved.routing_action == ROUTE_ACTION_PROXY
    assert saved.primary_pools == ["medium"]

    assert effective_contract_id(current_directness="DIRECT") == ROUTE_DIRECT_ACTION
    assert effective_contract_id(catalog_group_mode="ad_block") == ROUTE_REJECT_ACTION
    assert resolve_contract_id("中等质量代理", display_name_map={"direct": "中等质量代理"}) == "direct"


def test_contract_id_resolution_prioritizes_native_targets_and_exact_ids(tmp_path) -> None:
    # A current label equal to an existing ID must not reinterpret the stored
    # ID, while explicit renderer targets remain primitive actions.
    display_names = {
        "direct": "用户直连记录",
        "custom": "direct",
    }
    assert resolve_contract_id("direct", display_name_map=display_names) == "direct"
    assert resolve_contract_id(ROUTE_NATIVE_DIRECT_TARGET, display_name_map=display_names) == ROUTE_DIRECT_ACTION
    assert resolve_contract_id(ROUTE_NATIVE_REJECT_TARGET, display_name_map={"ad_block": "REJECT"}) == ROUTE_REJECT_ACTION


def test_reserved_action_ids_and_renderer_helper_names_cannot_be_proxy_contract_names(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    with pytest.raises(ValueError, match="reserved route action id"):
        repo.create_route_contract(
            RouteContract(id=ROUTE_DIRECT_ACTION, display_name="动作", primary_pools=["medium"])
        )
    with pytest.raises(ValueError, match="reserved by the subscription renderer"):
        repo.create_route_contract(
            RouteContract(id="reserved-name", display_name=ROUTE_NATIVE_DIRECT_TARGET, primary_pools=["medium"])
        )
    with pytest.raises(ValueError, match="reserved by the subscription renderer"):
        repo.create_route_contract(
            RouteContract(id="reserved-helper", display_name="中等质量·自动", primary_pools=["medium"])
        )
    # Quality labels remain ordinary editable names after a preset is removed.
    repo.delete_route_contract(CONTRACT_MEDIUM)
    saved = repo.create_route_contract(
        RouteContract(id="replacement-medium", display_name="中等质量", primary_pools=["medium"])
    )
    assert saved.display_name == "中等质量"


def test_proxy_requires_explicit_primary_pool_and_direct_template_is_pool_free(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    assert repo.get_route_contract(CONTRACT_DIRECT).primary_pools == []
    with pytest.raises(ValueError, match="primary_pools is required"):
        repo.create_route_contract(
            RouteContract(id="empty-proxy", display_name="空代理", primary_pools=[])
        )


def test_preexisting_empty_contract_catalog_stays_empty(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    db_path = data_dir / "subhub.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE route_contracts (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            strategy_type TEXT NOT NULL DEFAULT 'strict',
            failure_action TEXT NOT NULL DEFAULT 'interrupt',
            editable INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            owner_scenario_id TEXT NOT NULL DEFAULT '',
            is_system INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    repo = SqliteRepo(_settings(tmp_path))
    assert repo.list_route_contracts() == []
    repo._conn.close()
    reloaded = SqliteRepo(_settings(tmp_path))
    assert reloaded.list_route_contracts() == []
    reloaded._conn.close()


def test_legacy_native_rule_targets_use_primitives_but_explicit_record_ids_survive(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_custom_rule(
        CustomRule(id="legacy-direct", rule_type="DOMAIN", value="direct.example", target_group="DIRECT")
    )
    repo.save_custom_rule(
        CustomRule(id="legacy-reject", rule_type="DOMAIN", value="reject.example", target_group="REJECT")
    )
    repo.save_custom_rule(
        CustomRule(
            id="record-direct",
            rule_type="DOMAIN",
            value="record.example",
            target_contract_id=CONTRACT_DIRECT,
            target_group="DIRECT",
        )
    )
    items = {item.id: item for item in repo.list_custom_rules()}
    assert items["legacy-direct"].resolved_target_contract_id() == ROUTE_DIRECT_ACTION
    assert items["legacy-direct"].display_target_group() == ROUTE_NATIVE_DIRECT_TARGET
    assert items["legacy-reject"].resolved_target_contract_id() == ROUTE_REJECT_ACTION
    assert items["record-direct"].resolved_target_contract_id() == CONTRACT_DIRECT
    assert items["record-direct"].display_target_group() == "直连"
    assert PolicyRuleEntry(CONTRACT_DIRECT, "DOMAIN", "record.example").target_display_name() == "直连"


def test_proxy_contracts_allow_one_quality_family_and_reject_mixing(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    allowed = repo.create_route_contract(
        RouteContract(
            id="hq-multi",
            display_name="高质量混合",
            routing_action=ROUTE_ACTION_PROXY,
            primary_pools=["hq_premium"],
            fallback_pools=["hq_standard", "chain_home"],
        )
    )
    assert allowed.primary_pools == ["hq_premium"]

    with pytest.raises(ValueError, match="quality family"):
        repo.create_route_contract(
            RouteContract(
                id="bad-mix",
                display_name="跨层级",
                routing_action=ROUTE_ACTION_PROXY,
                primary_pools=["medium"],
                fallback_pools=["bulk"],
            )
        )

    with pytest.raises(ValueError, match="quality family"):
        repo.create_route_contract(
            RouteContract(
                id="bad-direct-pool",
                display_name="代理直连池",
                routing_action=ROUTE_ACTION_PROXY,
                primary_pools=["direct"],
            )
        )


def test_policy_transaction_rolls_back_and_batches_notifications(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    reasons: list[str] = []
    repo.set_policy_backup_notifier(reasons.append)

    with pytest.raises(RuntimeError):
        with repo.policy_transaction():
            repo.create_route_contract(
                RouteContract(
                    id="rolled-back",
                    display_name="回滚契约",
                    primary_pools=["medium"],
                )
            )
            raise RuntimeError("abort")

    assert repo.get_route_contract("rolled-back") is None
    assert reasons == []

    with repo.policy_transaction():
        repo.create_route_contract(
            RouteContract(
                id="committed",
                display_name="提交契约",
                primary_pools=["medium"],
            )
        )
    assert repo.get_route_contract("committed") is not None
    assert reasons == ["route-contract-create"]


def test_clear_contract_backup_reset_does_not_reseed_templates(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.reset_policy_backup_owned_state(clear_contracts=True)
    assert repo.list_route_contracts() == []

    reloaded = SqliteRepo(settings)
    assert reloaded.list_route_contracts() == []
