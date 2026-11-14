from __future__ import annotations

from app.models import (
    CustomRule,
    DeviceSubscription,
    NodeRecord,
    RuleCategory,
    ScenarioProfile,
    ServiceCatalogEntry,
    StandardSource,
)
from tests.api_helpers import _scenario_sub_path


def test_contract_endpoints_expose_route_contract_view_and_read_only_pool_fields(client, monkeypatch) -> None:
    services = client.app.state.services
    contracts = client.get("/api/contracts")
    assert contracts.status_code == 200
    contract_items = {item["id"]: item for item in contracts.json()["items"]}
    assert "ad_block" in contract_items
    assert contract_items["ad_block"]["editable"] is True
    assert contract_items["direct"]["editable"] is True
    assert contract_items["chain_home"]["primary_pools"] == ["chain_home"]
    assert contract_items["hq_standard"]["fallback_pools"] == ["hq_premium", "chain_home"]

    updated_contract = client.put(
        "/api/contracts/hq_standard",
        json={
            "description": "适合 AI / 实时 API / 低延迟场景",
            "strategy_type": "failover",
            "primary_pools": ["hq_standard"],
            "fallback_pools": ["hq_premium", "chain_home"],
            "failure_action": "interrupt",
            "enabled": True,
        },
    )
    assert updated_contract.status_code == 200
    assert updated_contract.json()["item"]["display_name"] == "高质量-低倍率"
    assert updated_contract.json()["item"]["description"] == "适合 AI / 实时 API / 低延迟场景"
    assert updated_contract.json()["item"]["strategy_type"] == "failover"
    assert updated_contract.json()["item"]["fallback_pools"] == ["hq_premium", "chain_home"]

    renamed_contract = client.put(
        "/api/contracts/hq_standard",
        json={"display_name": "高质量低延迟"},
    )
    assert renamed_contract.status_code == 200
    assert renamed_contract.json()["item"]["display_name"] == "高质量低延迟"

    recorded_calls: list[tuple[str, str, list[str], list[str]]] = []
    original_save_route_contract = services.repo.save_route_contract

    def _recording_save_route_contract(contract):
        recorded_calls.append(
            (
                contract.id,
                contract.strategy_type,
                list(contract.primary_pools),
                list(contract.fallback_pools),
            )
        )
        return original_save_route_contract(contract)

    monkeypatch.setattr(services.repo, "save_route_contract", _recording_save_route_contract)

    updated_hq_standard_contract = client.put(
        "/api/contracts/hq_standard",
        json={
            "strategy_type": "failover",
            "primary_pools": ["hq_standard"],
            "fallback_pools": ["hq_premium", "chain_home"],
            "failure_action": "interrupt",
            "enabled": True,
        },
    )
    assert updated_hq_standard_contract.status_code == 200
    assert updated_hq_standard_contract.json()["item"]["strategy_type"] == "failover"
    assert updated_hq_standard_contract.json()["item"]["primary_pools"] == ["hq_standard"]
    assert updated_hq_standard_contract.json()["item"]["fallback_pools"] == ["hq_premium", "chain_home"]
    assert updated_hq_standard_contract.json()["item"]["failure_action"] == "interrupt"
    assert recorded_calls == [
        ("hq_standard", "failover", ["hq_standard"], ["hq_premium", "chain_home"])
    ]

    listed_again = client.get("/api/contracts")
    assert listed_again.status_code == 200
    listed_items = {item["id"]: item for item in listed_again.json()["items"]}
    assert listed_items["hq_standard"]["display_name"] == "高质量低延迟"
    assert listed_items["hq_standard"]["description"] == "适合 AI / 实时 API / 低延迟场景"
    assert listed_items["hq_standard"]["fallback_pools"] == ["hq_premium", "chain_home"]


def test_contract_display_name_updates_flow_into_service_catalog_entries(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1)]
    )

    renamed_contract = client.put(
        "/api/contracts/hq_premium",
        json={"display_name": "高质量-核心实时"},
    )
    assert renamed_contract.status_code == 200

    service_catalog = client.put(
        "/api/service-catalog/OpenAI",
        json={"contract_id": "hq_premium", "catalog_group": "AI 服务", "sort_order": 2},
    )
    assert service_catalog.status_code == 200
    assert service_catalog.json()["item"]["contract_id"] == "hq_premium"
    assert service_catalog.json()["item"]["catalog_group"] == "AI 服务"

    listed_catalog = client.get("/api/service-catalog")
    assert listed_catalog.status_code == 200
    openai_entry = next(
        item for item in listed_catalog.json()["items"] if item["category_name"] == "OpenAI"
    )
    assert openai_entry["contract_display_name"] == "高质量-核心实时"

    global_entry = client.app.state.services.repo.get_service_catalog_entry("OpenAI")
    assert global_entry is not None
    assert global_entry.contract_id == "hq_premium"
    assert global_entry.catalog_group == "AI 服务"


def test_default_scenario_contract_view_updates_mirror_base_route_contract(client) -> None:
    services = client.app.state.services

    updated = client.put(
        "/api/contracts/medium",
        json={
            "display_name": "默认中转",
            "description": "默认场景下的中转组",
            "enabled": False,
            "sort_order": 42,
        },
    )
    assert updated.status_code == 200

    base_contract = services.repo.get_route_contract("medium")
    assert base_contract is not None
    assert base_contract.display_name == "默认中转"
    assert base_contract.description == "默认场景下的中转组"
    assert base_contract.enabled is False
    assert base_contract.sort_order == 42


def test_invalid_default_scenario_contract_edit_does_not_mutate_base_contract(client) -> None:
    services = client.app.state.services
    base_before = services.repo.get_route_contract("medium")
    assert base_before is not None

    rejected = client.put(
        "/api/contracts/medium",
        json={
            "enabled": False,
            "is_default": True,
        },
    )
    assert rejected.status_code == 400

    base_after = services.repo.get_route_contract("medium")
    assert base_after is not None
    assert base_after.enabled == base_before.enabled
    assert base_after.display_name == base_before.display_name
    assert base_after.description == base_before.description
    assert base_after.sort_order == base_before.sort_order


def test_preset_contracts_are_user_editable(client) -> None:
    direct = client.put(
        "/api/contracts/direct",
        json={"display_name": "自定义直连"},
    )
    assert direct.status_code == 200
    assert direct.json()["item"]["display_name"] == "自定义直连"

    ad_block = client.put(
        "/api/contracts/ad_block",
        json={"description": "自定义广告拦截说明"},
    )
    assert ad_block.status_code == 200
    assert ad_block.json()["item"]["description"] == "自定义广告拦截说明"


def test_create_global_custom_contract_can_be_used_by_standard_sources(client) -> None:
    created_contract = client.post(
        "/api/contracts",
        json={
            "display_name": "办公中转",
            "description": "办公场景共享契约",
            "llm_routing_intent": "优先走中转池",
            "strategy_type": "strict",
            "primary_pools": ["medium"],
            "fallback_pools": [],
            "failure_action": "interrupt",
            "enabled": True,
            "sort_order": 30,
        },
    )
    assert created_contract.status_code == 200
    item = created_contract.json()["item"]
    assert item["id"].startswith("custom-")
    assert item["scope"] == "global"
    assert item["owner_scenario_id"] == ""
    assert item["primary_pools"] == ["medium"]

    source = client.post(
        "/api/sources/standard",
        json={
            "name": "办公自建源",
            "ingest_kind": "manual_nodes",
            "manual_nodes_text": "trojan://secret@a.example.com:443?sni=example.com#A",
            "target_contract_id": item["id"],
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert source.status_code == 200
    assert source.json()["item"]["target_contract_id"] == item["id"]
    assert source.json()["item"]["target_contract_display_name"] == "办公中转"


def test_create_scenario_contract_is_owner_scoped_and_non_default_cannot_edit_global_topology(client) -> None:
    services = client.app.state.services
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work"),
    )

    created = client.post(
        "/api/contracts?scenario_id=scenario-work",
        json={
            "display_name": "办公直通",
            "description": "工作场景专用",
            "strategy_type": "strict",
            "primary_pools": ["bulk"],
            "fallback_pools": [],
            "failure_action": "interrupt",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    item = created.json()["item"]
    assert item["id"].startswith("scenario-work-")
    assert item["scope"] == "scenario"
    assert item["owner_scenario_id"] == "scenario-work"

    default_list = client.get("/api/contracts")
    assert default_list.status_code == 200
    assert item["id"] not in {entry["id"] for entry in default_list.json()["items"]}

    work_list = client.get("/api/contracts?scenario_id=scenario-work")
    assert work_list.status_code == 200
    assert item["id"] in {entry["id"] for entry in work_list.json()["items"]}

    forbidden = client.put(
        "/api/contracts/medium?scenario_id=scenario-work",
        json={"primary_pools": ["bulk"]},
    )
    assert forbidden.status_code == 409
    assert forbidden.json()["detail"] == "contract topology is managed by its owner scope"


def test_scenario_contract_cannot_be_bound_by_global_standard_source(client) -> None:
    services = client.app.state.services
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work"),
    )

    created = client.post(
        "/api/contracts?scenario_id=scenario-work",
        json={
            "display_name": "办公直通",
            "description": "工作场景专用",
            "strategy_type": "strict",
            "primary_pools": ["bulk"],
            "fallback_pools": [],
            "failure_action": "interrupt",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    contract_id = created.json()["item"]["id"]

    source = client.post(
        "/api/sources/standard?scenario_id=scenario-work",
        json={
            "name": "办公自建源",
            "ingest_kind": "manual_nodes",
            "manual_nodes_text": "trojan://secret@a.example.com:443?sni=example.com#A",
            "target_contract_id": contract_id,
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert source.status_code == 400
    assert "target_contract_id" in source.json()["detail"]

    deleted_contract = client.delete(f"/api/contracts/{contract_id}?scenario_id=scenario-work")
    assert deleted_contract.status_code == 200


def test_delete_contract_requires_rebind_before_removal(client) -> None:
    created_contract = client.post(
        "/api/contracts",
        json={
            "display_name": "下载专线",
            "strategy_type": "strict",
            "primary_pools": ["bulk"],
            "fallback_pools": [],
            "failure_action": "interrupt",
            "enabled": True,
        },
    )
    assert created_contract.status_code == 200
    contract_id = created_contract.json()["item"]["id"]

    created_source = client.post(
        "/api/sources/standard",
        json={
            "name": "下载自建源",
            "ingest_kind": "manual_nodes",
            "manual_nodes_text": "trojan://secret@bulk.example.com:443?sni=example.com#bulk",
            "target_contract_id": contract_id,
            "source_mode": "route_contract",
            "enabled": True,
        },
    )
    assert created_source.status_code == 200
    source_id = created_source.json()["item"]["id"]

    blocked_delete = client.delete(f"/api/contracts/{contract_id}")
    assert blocked_delete.status_code == 409
    assert blocked_delete.json()["detail"] == "contract is still referenced; rebind before deleting"

    deleted_source = client.delete(f"/api/sources/standard/{source_id}")
    assert deleted_source.status_code == 200

    deleted_contract = client.delete(f"/api/contracts/{contract_id}")
    assert deleted_contract.status_code == 200
    listed = client.get("/api/contracts")
    assert contract_id not in {item["id"] for item in listed.json()["items"]}


def test_category_assign_accepts_scenario_contract_display_name(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1)]
    )
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work"),
    )

    renamed_contract = client.put(
        "/api/contracts/medium?scenario_id=scenario-work",
        json={"display_name": "工作中转"},
    )
    assert renamed_contract.status_code == 200

    assigned = client.put(
        "/api/rules/categories/OpenAI?scenario_id=scenario-work",
        json={"assigned_group": "工作中转"},
    )
    assert assigned.status_code == 200

    listed = client.get("/api/rules/categories?scenario_id=scenario-work")
    assert listed.status_code == 200
    openai = next(item for item in listed.json()["items"] if item["name"] == "OpenAI")
    assert openai["assigned_group"] == "工作中转"
    assert openai["effective_contract_id"] == "medium"


def test_bulk_assign_accepts_scenario_contract_display_name(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1)]
    )
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-bulk", slug="bulk", name="Bulk"),
    )

    renamed_contract = client.put(
        "/api/contracts/medium?scenario_id=scenario-bulk",
        json={"display_name": "工作中转"},
    )
    assert renamed_contract.status_code == 200

    assigned = client.post(
        "/api/rules/categories/bulk-assign?scenario_id=scenario-bulk",
        json={"assignments": {"OpenAI": "工作中转"}},
    )
    assert assigned.status_code == 200
    assert assigned.json()["updated"] == 1

    listed = client.get("/api/rules/categories?scenario_id=scenario-bulk")
    assert listed.status_code == 200
    openai = next(item for item in listed.json()["items"] if item["name"] == "OpenAI")
    assert openai["assigned_group"] == "工作中转"
    assert openai["effective_contract_id"] == "medium"


def test_category_and_catalog_lists_read_scenario_contracts_once_per_request(client, monkeypatch) -> None:
    from app.storage import sqlite_repo

    services = client.app.state.services
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-many", slug="many", name="Many"),
    )
    renamed_contract = client.put(
        "/api/contracts/medium?scenario_id=scenario-many",
        json={"display_name": "工作中转"},
    )
    assert renamed_contract.status_code == 200

    executed: list[object] = []
    original_execute = sqlite_repo._TransactionConnection.execute

    def _counting_execute(self, *args, **kwargs):
        executed.append(args[0] if args else None)
        return original_execute(self, *args, **kwargs)

    monkeypatch.setattr(sqlite_repo._TransactionConnection, "execute", _counting_execute)

    def _list(path: str) -> tuple[list[dict[str, object]], int]:
        executed.clear()
        response = client.get(path)
        assert response.status_code == 200
        return response.json()["items"], len(executed)

    query_counts: dict[int, tuple[int, int]] = {}
    for size in (2, 40):
        names = [f"Service{index:02d}" for index in range(size)]
        services.repo.save_rule_categories(
            [RuleCategory(name=name, assigned_group="高质量-高倍率", rule_count=1) for name in names]
        )
        assigned = client.post(
            "/api/rules/categories/bulk-assign?scenario_id=scenario-many",
            json={"assignments": {name: "工作中转" for name in names}},
        )
        assert assigned.status_code == 200
        assert assigned.json()["updated"] == size

        categories, category_queries = _list("/api/rules/categories?scenario_id=scenario-many")
        listed = {item["name"]: item for item in categories if item["name"] in names}
        assert set(listed) == set(names)
        for item in listed.values():
            assert item["assigned_group"] == "工作中转"
            assert item["effective_state"]["group"] == "工作中转"
            assert item["effective_contract_id"] == "medium"
            assert item["effective_contract_display_name"] == "工作中转"

        catalog, catalog_queries = _list("/api/service-catalog?scenario_id=scenario-many")
        catalog_names = {item["category_name"]: item for item in catalog if item["category_name"] in names}
        assert set(catalog_names) == set(names)
        assert {item["contract_display_name"] for item in catalog_names.values()} == {"工作中转"}
        query_counts[size] = (category_queries, catalog_queries)

    # Display names come from one read of the scenario's contracts, so the
    # query count must not grow with the number of rows.
    assert query_counts[40] == query_counts[2]


def test_legacy_business_group_process_rule_requires_rebind_when_catalog_is_mixed(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-mixed",
            device_key="mac-mixed",
            device_name="Mac Mixed",
            token="tok-mixed",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s1",
        [
            NodeRecord(
                name="node-1",
                host="n1.example.com",
                port=443,
                protocol="http",
                quality_group="高质量-高倍率",
            )
        ],
    )
    services.repo.save_rule_categories(
        [
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1),
            RuleCategory(name="Reddit", assigned_group="中等质量", rule_count=1),
        ]
    )
    services.repo.save_rule_cache("OpenAI", ["DOMAIN-SUFFIX,openai.com,PLACEHOLDER"])
    services.repo.save_rule_cache("Reddit", ["DOMAIN-SUFFIX,reddit.com,PLACEHOLDER"])
    services.repo.pin_category("OpenAI", "混合组")
    services.repo.pin_category("Reddit", "混合组")

    saved = client.put(
        "/api/settings/surge/process-rules",
        json={
            "items": [
                {
                    "business_group": "混合组",
                    "match_type": "PROCESS-NAME",
                    "value": "MixedApp",
                    "enabled": True,
                }
            ]
        },
    )
    assert saved.status_code == 200

    listed = client.get("/api/settings/surge/process-rules")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["enabled"] is False
    assert listed.json()["items"][0]["needs_rebind"] is True

    devices = client.get("/api/devices")
    assert devices.status_code == 200
    overlay_status = next(
        item["overlay_status"] for item in devices.json()["items"] if item["device_name"] == "Mac Mixed"
    )
    assert overlay_status["available"] is False
    assert overlay_status["reason_code"] == "needs_rebind"

    overlay = client.get(_scenario_sub_path("tok-mixed", "surge-mac-overlay.conf"))
    assert overlay.status_code == 409
    assert overlay.json()["detail"] == "Overlay templates require contract rebinding before they can render. Open Advanced settings and fix the needs_rebind items."


def test_rebind_in_non_default_scenario_does_not_modify_global_custom_rules(client) -> None:
    services = client.app.state.services
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work"),
    )
    services.repo.save_custom_rule(
        CustomRule(
            id="global-rule",
            rule_type="DOMAIN-SUFFIX",
            value="global.example.com",
            target_contract_id="medium",
            created_at="2026-04-06T00:00:00Z",
        )
    )
    services.repo.save_scenario_custom_rule(
        "scenario-work",
        CustomRule(
            id="scenario-rule",
            rule_type="DOMAIN-SUFFIX",
            value="work.example.com",
            target_contract_id="medium",
            created_at="2026-04-06T00:00:00Z",
        )
    )

    resp = client.post(
        "/api/contracts/medium/rebind?scenario_id=scenario-work",
        json={"to_contract_id": "hq_standard"},
    )
    assert resp.status_code == 200
    assert resp.json()["counts"]["custom_rules"] == 1

    global_rules = {item.id: item for item in services.repo.list_custom_rules()}
    scenario_rules = {item.id: item for item in services.repo.list_explicit_scenario_custom_rules("scenario-work")}
    assert global_rules["global-rule"].resolved_target_contract_id() == "medium"
    assert scenario_rules["scenario-rule"].resolved_target_contract_id() == "hq_standard"


def test_custom_rule_rejects_unknown_contract_id(client) -> None:
    created = client.post(
        "/api/rules/custom",
        json={
            "rule_type": "DOMAIN-SUFFIX",
            "value": "example.com",
            "target_contract_id": "office",
        },
    )
    assert created.status_code == 400
    assert created.json()["detail"] == "invalid target_contract_id"


def test_default_scenario_contract_disable_counts_scenario_process_rule_references(client) -> None:
    services = client.app.state.services
    services.repo.set_scenario_process_rules(
        "scenario-default",
        [
            {
                "id": "proc-1",
                "contract_id": "medium",
                "business_group": "中等质量",
                "match_type": "PROCESS-NAME",
                "value": "curl",
                "sort_order": 0,
                "enabled": True,
            }
        ],
    )
    services.repo.set_runtime_setting("surge.process_rules", [])

    resp = client.put(
        "/api/contracts/medium",
        json={"enabled": False},
    )
    assert resp.status_code == 409
    assert "still referenced" in resp.json()["detail"]


def test_default_scenario_contract_disable_counts_inherited_non_default_scenario_references(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="中等质量", rule_count=1)]
    )
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work"),
    )
    services.repo.save_scenario_service_catalog_entry(
        "scenario-work",
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="办公",
            contract_id="medium",
            sort_order=1,
            source="manual",
        ),
    )

    resp = client.put(
        "/api/contracts/medium",
        json={"enabled": False},
    )
    assert resp.status_code == 409
    assert "still referenced" in resp.json()["detail"]


def test_default_scenario_rebind_updates_scenario_service_catalog_and_process_rules(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="中等质量", rule_count=1)]
    )
    services.repo.save_scenario_service_catalog_entry(
        "scenario-default",
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI",
            contract_id="medium",
            sort_order=1,
            source="manual",
        ),
    )
    services.repo.set_scenario_process_rules(
        "scenario-default",
        [
            {
                "id": "proc-1",
                "contract_id": "medium",
                "business_group": "中等质量",
                "match_type": "PROCESS-NAME",
                "value": "curl",
                "sort_order": 0,
                "enabled": True,
            }
        ],
    )
    services.repo.set_runtime_setting("surge.process_rules", [])

    resp = client.post(
        "/api/contracts/medium/rebind?scenario_id=scenario-default",
        json={"to_contract_id": "hq_standard"},
    )
    assert resp.status_code == 200
    counts = resp.json()["counts"]
    assert counts["service_catalog"] == 1
    assert counts["process_rules"] == 1

    catalog_entry = next(
        item
        for item in services.repo.list_scenario_service_catalog_entries("scenario-default")
        if item.category_name == "OpenAI"
    )
    process_rule = services.repo.list_scenario_process_rules("scenario-default")[0]
    assert catalog_entry.contract_id == "hq_standard"
    assert process_rule["contract_id"] == "hq_standard"


def test_contract_disable_blocks_referenced_subscription_rendering(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-blocked-contract",
            device_key="mac-blocked-contract",
            device_name="Mac Blocked Contract",
            token="tok-blocked-contract",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-blocked-contract",
            name="源BlockedContract",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="高质量-高倍率",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-blocked-contract",
        [
            NodeRecord(
                name="hq-premium-1",
                host="premium.example.com",
                port=443,
                protocol="http",
                quality_group="高质量-高倍率",
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="Streaming", assigned_group="高质量-低倍率", rule_count=2)]
    )
    services.repo.save_rule_cache(
        "Streaming",
        [
            "DOMAIN-SUFFIX,youtube.com,PLACEHOLDER",
            "DOMAIN-KEYWORD,netflix,PLACEHOLDER",
        ],
    )

    summary = client.get("/api/devices/tok-blocked-contract/preview-summary?target=surge")
    assert summary.status_code == 409
    assert summary.json()["detail"]["code"] == "surge-build-blocked"
