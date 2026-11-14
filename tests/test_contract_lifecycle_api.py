import pytest

from app.models import CustomRule, DeviceSubscription, RuleCategory, RouteContractView, ScenarioProfile, ServiceCatalogEntry, StandardSource
from app.storage.sqlite_repo import SqliteRepo


def _create(client, name="用户契约", **fields):
    response = client.post("/api/contracts", json={"display_name": name, "primary_pools": ["medium"], **fields})
    assert response.status_code == 200, response.text
    return response.json()["item"]


def test_presets_are_editable_owned_records(client):
    items = client.get("/api/contracts").json()["items"]
    assert len(items) == 7
    assert all(item["editable"] and not item["is_system"] and item["scope"] == "global" for item in items)
    response = client.put("/api/contracts/direct", json={"display_name": "办公网络", "routing_action": "proxy", "primary_pools": ["medium"]})
    assert response.status_code == 200, response.text
    assert response.json()["item"]["routing_action"] == "proxy"
    assert response.json()["item"]["primary_pools"] == ["medium"]
    response = client.put("/api/contracts/ad_block", json={"display_name": "自定义拒绝"})
    assert response.status_code == 200


def test_deletion_persists_and_catalog_can_be_empty(client):
    repo = client.app.state.services.repo
    for contract in repo.list_route_contracts():
        if contract.id == "chain_home":
            continue
        response = client.delete(f"/api/contracts/{contract.id}")
        assert response.status_code == 200, response.text
    response = client.delete("/api/contracts/chain_home")
    assert response.status_code == 200, response.text
    assert repo.list_route_contracts() == []
    reloaded = SqliteRepo(repo.settings)
    assert reloaded.list_route_contracts() == []
    reloaded._conn.close()
    contract = _create(client)
    assert contract["is_default"] is False
    assert not any(item["is_default"] for item in client.get("/api/contracts").json()["items"])


def test_default_deletion_requires_explicit_replacement(client):
    response = client.delete("/api/contracts/chain_home")
    assert response.status_code == 409
    assert "explicit replacement" in response.json()["detail"]
    response = client.delete("/api/contracts/chain_home", params={"replacement_contract_id": "medium"})
    assert response.status_code == 200, response.text
    items = {item["id"]: item for item in client.get("/api/contracts").json()["items"]}
    assert "chain_home" not in items
    assert items["medium"]["is_default"]


def test_global_delete_migrates_sources_catalog_and_scenario_defaults(client):
    services = client.app.state.services
    repo = services.repo
    repo.save_standard_source(StandardSource(id="test-source", name="手动源", target_contract_id="medium"))
    repo.save_rule_categories([RuleCategory(name="业务", assigned_group="medium", rule_count=0, rule_source="test")])
    repo.save_service_catalog_entry(ServiceCatalogEntry(category_name="业务", contract_id="medium"))
    repo.save_scenario(ScenarioProfile(id="scenario-work", slug="work", name="工作"))
    repo.save_scenario_route_contract_view("scenario-work", RouteContractView(scenario_id="scenario-work", contract_id="medium", display_name="工作默认", is_default=True))
    references = client.get("/api/contracts/medium/references").json()
    assert references["is_default"]
    assert {item["kind"] for item in references["references"]} >= {"standard_sources", "service_catalog", "default"}
    assert client.delete("/api/contracts/medium").status_code == 409
    target = _create(client)
    response = client.delete("/api/contracts/medium", params={"replacement_contract_id": target["id"]})
    assert response.status_code == 200, response.text
    assert repo.list_standard_sources()[0].target_contract_id == target["id"]
    assert repo.get_service_catalog_entry("业务").contract_id == target["id"]
    work = client.get("/api/contracts", params={"scenario_id": "scenario-work"}).json()["items"]
    assert next(item for item in work if item["id"] == target["id"])["is_default"]


def test_invalid_replacement_does_not_mutate_any_reference(client):
    repo = client.app.state.services.repo
    repo.save_standard_source(StandardSource(id="test-source", name="手动源", target_contract_id="medium"))
    response = client.delete("/api/contracts/medium", params={"replacement_contract_id": "ad_block"})
    assert response.status_code == 409
    assert repo.get_route_contract("medium") is not None
    assert repo.list_standard_sources()[0].target_contract_id == "medium"


def test_mid_rebind_failure_rolls_back_catalog_and_source(client, monkeypatch):
    repo = client.app.state.services.repo
    repo.save_rule_categories([RuleCategory(name="业务", assigned_group="medium", rule_count=0, rule_source="test")])
    repo.save_service_catalog_entry(ServiceCatalogEntry(category_name="业务", contract_id="medium"))
    repo.save_standard_source(StandardSource(id="test-source", name="手动源", target_contract_id="medium"))
    target = _create(client)
    def fail(_source):
        raise ValueError("injected failure")
    monkeypatch.setattr(repo, "save_standard_source", fail)
    response = client.delete("/api/contracts/medium", params={"replacement_contract_id": target["id"]})
    assert response.status_code == 400
    assert repo.get_route_contract("medium") is not None
    assert repo.get_service_catalog_entry("业务").contract_id == "medium"
    assert repo.list_standard_sources()[0].target_contract_id == "medium"


def test_inherited_global_contract_cannot_be_deleted_from_child(client):
    repo = client.app.state.services.repo
    repo.save_scenario(ScenarioProfile(id="scenario-work", slug="work", name="工作"))
    response = client.delete("/api/contracts/bulk", params={"scenario_id": "scenario-work"})
    assert response.status_code == 409
    assert repo.get_route_contract("bulk") is not None


def test_explicit_action_contract_can_use_arbitrary_identity(client):
    contract = _create(client, "拒绝业务", routing_action="reject", primary_pools=[])
    assert contract["routing_action"] == "reject"
    response = client.put(f'/api/contracts/{contract["id"]}', json={"routing_action": "direct", "primary_pools": [], "fallback_pools": []})
    assert response.status_code == 200, response.text
    assert response.json()["item"]["routing_action"] == "direct"


def test_new_source_requires_explicit_contract(client):
    response = client.post("/api/sources/standard", json={"name": "源", "clash_url": "https://example.com/sub"})
    assert response.status_code == 400
    assert "target_contract_id" in response.json()["detail"]


def test_source_bound_topology_update_is_rejected_atomically(client):
    repo = client.app.state.services.repo
    repo.save_standard_source(StandardSource(id="source", name="源", target_contract_id="hq_premium"))
    before = repo.get_route_contract("hq_premium").to_dict()
    response = client.put("/api/contracts/hq_premium", json={"display_name": "不能保存", "primary_pools": ["chain_home"]})
    assert response.status_code == 409, response.text
    assert repo.get_route_contract("hq_premium").to_dict() == before
    assert repo.list_standard_sources()[0].target_contract_id == "hq_premium"


@pytest.mark.parametrize("target,suffix", [("clash", "clash.yaml"), ("surge", "surge.conf"), ("shadowrocket", "shadowrocket.conf")])
@pytest.mark.parametrize("problem", ["no-default", "missing-reference"])
def test_incomplete_policy_blocks_preview_and_subscription(client, monkeypatch, target, suffix, problem):
    services = client.app.state.services
    repo = services.repo
    repo.save_device_subscription(DeviceSubscription(id="device", device_key="test", device_name="测试设备", token="test-token"))
    repo.save_scenario_route_contract_view("scenario-default", RouteContractView(scenario_id="scenario-default", contract_id="direct", display_name="直连", is_default=True))
    if problem == "no-default":
        for contract in repo.list_route_contracts():
            repo.delete_route_contract(contract.id)
    else:
        repo.save_custom_rule(CustomRule(id="dangling", rule_type="DOMAIN", value="missing.example", target_contract_id="missing"))
    async def no_refresh(force=False):
        return services.hub_service.runtime
    monkeypatch.setattr(services.hub_service, "refresh", no_refresh)
    for path in [f"/api/devices/test-token/render-preview?target={target}", f"/sub/device/test-token/default/{suffix}"]:
        response = client.get(path)
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["code"] == f"{target}-build-blocked"
        expected = "default-contract-missing" if problem == "no-default" else "referenced-missing-contract"
        assert any(item["code"] == f"{target}-{expected}" for item in detail["blockers"])


def test_private_contract_deletion_migrates_source_in_owner_scope(client):
    repo = client.app.state.services.repo
    repo.save_scenario(ScenarioProfile(id="work", slug="work", name="工作"))
    created = client.post("/api/contracts?scenario_id=work", json={"display_name": "私有出口", "primary_pools": ["medium"]}).json()["item"]
    repo.save_standard_source(StandardSource(id="private-source", name="私有源", target_contract_id=created["id"]))
    refs = client.get(f'/api/contracts/{created["id"]}/references?scenario_id=work').json()["references"]
    assert any(item["kind"] == "standard_sources" for item in refs)
    assert client.delete(f'/api/contracts/{created["id"]}?scenario_id=work').status_code == 409
    response = client.delete(f'/api/contracts/{created["id"]}?scenario_id=work&replacement_contract_id=medium')
    assert response.status_code == 200, response.text
    assert repo.list_standard_sources()[0].target_contract_id == "medium"


def test_standalone_rebind_failure_rolls_back_earlier_stage(client, monkeypatch):
    import app.routes.management as management
    repo = client.app.state.services.repo
    repo.save_rule_categories([RuleCategory(name="业务", assigned_group="medium", rule_count=0)])
    repo.save_service_catalog_entry(ServiceCatalogEntry(category_name="业务", contract_id="medium"))
    def fail(*args):
        raise ValueError("injected later-stage failure")
    monkeypatch.setattr(management, "_rebind_custom_rules", fail)
    response = client.post("/api/contracts/medium/rebind", json={"to_contract_id": "bulk"})
    assert response.status_code == 400
    assert repo.get_service_catalog_entry("业务").contract_id == "medium"
