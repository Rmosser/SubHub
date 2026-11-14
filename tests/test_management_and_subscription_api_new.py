from __future__ import annotations

import asyncio
import base64
import io
import json
import zipfile

import yaml

from app.models import (
    BUSINESS_GROUP_MODE_AD_BLOCK,
    BUSINESS_GROUP_MODE_STANDARD,
    CollectedRule,
    CustomRule,
    DeviceSubscription,
    GeneralProfile,
    GoRelayAccount,
    GoRelayAccountSnapshot,
    GoRelayAccountSnapshotPayload,
    GoRelayDeviceSubscription,
    GoRelayDomainBinding,
    HubRuntime,
    NodeRecord,
    RuleCategory,
    RuleCategoryDirectnessReview,
    RouteContract,
    ScenarioProfile,
    ServiceCatalogEntry,
    StandardSource,
    StandardSourceWarning,
)
from app.services.subscription_builder import (
    build_device_import_links_for_scenario,
    resolve_preferred_surge_base_url,
)
from app.services.subscription_contracts import CLASH_BUNDLE_FILES
from tests.api_helpers import (
    DEFAULT_SCENARIO_SLUG,
    _ProtocolProbeClient,
    _create_gorelay_source,
    _create_scenario,
    _create_standard_source,
    _find_capability_view,
    _scenario_sub_path,
    _stub_standard_refresh,
)


def test_management_api_crud_and_status(client) -> None:
    source_id = _create_gorelay_source(client)

    listed = client.get("/api/sources/gorelay")
    assert listed.status_code == 200
    item = next(item for item in listed.json()["items"] if item["id"] == source_id)
    assert item["last_refresh_at"] is None
    assert item["last_refresh_status"] == ""
    assert item["last_refresh_error"] == ""
    assert item["last_node_count"] == 0
    assert item["last_device_count"] == 0
    assert item["pending_domain_count"] == 0
    assert item["latest_snapshot_id"] == ""
    assert item["active_snapshot_id"] == ""
    assert item["active_snapshot_is_latest"] is True

    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["ok"] is True
    assert status.json()["features"]["directness_review"] is True
    assert "egress" in status.json()
    assert "proxy_bridge" in status.json()["egress"]

    manage = client.get("/manage")
    assert manage.status_code == 200
    assert "SubHub Console" in manage.text
    assert "/manage/assets/" in manage.text

    gorelay_console = client.get("/manage/gorelay")
    assert gorelay_console.status_code == 200
    assert "SubHub Console" in gorelay_console.text


def test_manage_routes_serve_spa_shell(client) -> None:
    manage = client.get("/manage", headers={"Accept-Language": "en-US"})
    assert manage.status_code == 200
    assert "SubHub Console" in manage.text
    assert "/manage/assets/" in manage.text
    assert "System Status" not in manage.text

    gorelay = client.get("/manage/gorelay", headers={"Accept-Language": "en-US"})
    assert gorelay.status_code == 200
    assert "SubHub Console" in gorelay.text
    assert "GoRelay Multi-account Console" not in gorelay.text


def test_status_and_diagnostics_localize_visible_egress_text(client, monkeypatch) -> None:
    services = client.app.state.services

    async def _fake_status(*, gorelay_source_count: int = 0, force: bool = False):
        return {
            "proxy_bridge": {
                "code": "proxy_bridge_unreachable",
                "severity": "warning",
                "summary": "盒子代理桥接入口不可达。",
                "meaning": "SubHub 无法连接 172.18.0.1:17890。",
                "repair_hint": "运行 check_mihomo_bridge.sh",
                "actions": ["运行自检脚本"],
                "required": gorelay_source_count > 0,
            }
        }

    def _fake_cached_status(*, gorelay_source_count: int = 0):
        return {
            "proxy_bridge": {
                "code": "proxy_bridge_unreachable",
                "severity": "warning",
                "summary": "盒子代理桥接入口不可达。",
                "meaning": "SubHub 无法连接 172.18.0.1:17890。",
                "repair_hint": "运行 check_mihomo_bridge.sh",
                "actions": ["运行自检脚本"],
                "required": gorelay_source_count > 0,
            }
        }

    monkeypatch.setattr(services.egress_diagnostics, "get_status", _fake_status)
    monkeypatch.setattr(services.egress_diagnostics, "get_cached_status", _fake_cached_status)

    status = client.get("/api/status", headers={"Accept-Language": "en-US"})
    assert status.status_code == 200
    assert status.json()["egress"]["proxy_bridge"]["summary"] == "The box proxy bridge endpoint is unreachable."

    diagnostics = client.get("/diagnostics", headers={"Accept-Language": "en-US"})
    assert diagnostics.status_code == 200
    assert diagnostics.json()["health"]["egress"]["proxy_bridge"]["repair_hint"].startswith("Run sudo bash")


def test_public_healthz_does_not_expose_or_probe_egress(client, monkeypatch) -> None:
    services = client.app.state.services

    def _fake_cached_status(*, gorelay_source_count: int = 0):
        return {
            "proxy_bridge": {
                "code": "proxy_bridge_unreachable",
                "severity": "warning",
                "summary": "盒子代理桥接入口不可达。",
                "meaning": "SubHub 无法连接 172.18.0.1:17890。",
                "repair_hint": "运行 check_mihomo_bridge.sh",
                "actions": ["运行自检脚本"],
                "required": gorelay_source_count > 0,
            }
        }

    async def _unexpected_probe(*, gorelay_source_count: int = 0, force: bool = False):
        raise AssertionError("healthz should not trigger realtime egress probing")

    monkeypatch.setattr(services.egress_diagnostics, "get_cached_status", _fake_cached_status)
    monkeypatch.setattr(services.egress_diagnostics, "get_status", _unexpected_probe)
    health = client.get("/healthz")

    assert health.status_code == 200
    assert "egress" not in health.json()
    assert "hub" not in health.json()
    assert health.json()["ok"] is True


def test_diagnostics_forces_fresh_egress_probe(client, monkeypatch) -> None:
    services = client.app.state.services

    def _cached_status(*, gorelay_source_count: int = 0):
        return {"proxy_bridge": {"code": "not_checked", "required": gorelay_source_count > 0}}

    async def _fresh_status(*, gorelay_source_count: int = 0, force: bool = False):
        assert force is True
        return {"proxy_bridge": {"code": "ok", "required": gorelay_source_count > 0}}

    monkeypatch.setattr(services.egress_diagnostics, "get_cached_status", _cached_status)
    monkeypatch.setattr(services.egress_diagnostics, "get_status", _fresh_status)

    diagnostics = client.get("/diagnostics")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["health"]["egress"]["proxy_bridge"]["code"] == "ok"


def test_diagnostics_keeps_unwritable_storage_readiness_as_json(client, monkeypatch) -> None:
    from app.routes import internal

    services = client.app.state.services
    monkeypatch.setattr(internal, "_is_storage_root_writable", lambda root: False)

    async def egress(*, gorelay_source_count=0, force=False):
        return {"proxy_bridge": {"code": "ok"}}

    monkeypatch.setattr(services.egress_diagnostics, "get_status", egress)
    ready = client.get("/readyz")
    assert ready.status_code == 503
    assert ready.json()["ok"] is False
    diagnostics = client.get("/diagnostics")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["ready"]["ok"] is False
    assert diagnostics.json()["ready"]["checks"]["storage_root_writable"]["ok"] is False


def test_diagnostics_and_status_include_standard_source_config_fingerprints(client, monkeypatch) -> None:
    services = client.app.state.services
    source_id = _create_standard_source(client)

    source = services.repo.get_standard_source(source_id)
    assert source is not None

    from app.services.source_fetcher import SourcePullResult

    async def _success_fetch(_source):
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
                    source_id=source_id,
                    source_type="standard",
                )
            ],
        )

    monkeypatch.setattr(services.hub_service.source_fetcher, "fetch_source", _success_fetch)
    asyncio.run(services.hub_service.refresh_one_standard_source(source_id, trigger="manual"))

    diagnostics = client.get("/diagnostics")
    assert diagnostics.status_code == 200
    health_item = diagnostics.json()["health"]["hub"]["source_status"]["standard"][source_id]
    assert health_item["config_fingerprint"]
    assert health_item["last_success_config_fingerprint"] == health_item["config_fingerprint"]

    status = client.get("/api/status")
    assert status.status_code == 200
    status_item = status.json()["runtime"]["source_status"]["standard"][source_id]
    assert status_item["config_fingerprint"]
    assert status_item["last_success_config_fingerprint"] == status_item["config_fingerprint"]


def test_anonymous_healthz_sanitizes_policy_backup_credentials(client) -> None:
    services = client.app.state.services
    credential_url = "https://embedded-user:embedded-token@example.test/policy.git"
    services.settings.policy_backup_enabled = True
    services.settings.policy_backup_repo_url = credential_url
    services.settings.policy_backup_github_token = "separate-token"

    response = client.get("/healthz")

    assert response.status_code == 200
    public_status = response.json()["policy_backup"]
    assert "repo_url" not in public_status
    serialized = json.dumps(public_status, sort_keys=True)
    assert credential_url not in serialized
    assert "embedded-user" not in serialized
    assert "embedded-token" not in serialized
    assert "separate-token" not in serialized


def test_anonymous_healthz_sanitizes_runtime_heartbeat_diagnostics(client) -> None:
    services = client.app.state.services
    private_url = "https://embedded-user:embedded-token@example.test/policy.git"
    services.repo.upsert_runtime_heartbeat(
        "policy_backup.worker",
        status="degraded",
        required=True,
        last_error=f"push failed for {private_url}",
        details={
            "phase": "sync_result",
            "error": f"remote {private_url} rejected the push",
            "error_detail": {
                "message": private_url,
                "stack": "private stack trace",
            },
        },
    )

    response = client.get("/healthz")

    assert response.status_code == 200
    task = next(
        item for item in response.json()["runtime_tasks"] if item["task_name"] == "policy_backup.worker"
    )
    assert task["has_error"] is True
    assert "last_error" not in task
    assert task["details"] == {"phase": "sync_result"}
    serialized = json.dumps(task, sort_keys=True)
    assert private_url not in serialized
    assert "private stack trace" not in serialized


def test_rules_refresh_mode_passthrough(client, monkeypatch) -> None:
    services = client.app.state.services
    captured: dict[str, object] = {}

    async def _fake_refresh_categories(force: bool = False, mode: str = "incremental"):
        captured["force"] = force
        captured["mode"] = mode
        return {
            "ok": True,
            "source": "github",
            "mode": mode,
            "downloaded_count": 3,
            "reused_count": 10,
            "cn_cache_source": "sqlite",
        }

    monkeypatch.setattr(services.rule_catalog, "refresh_categories", _fake_refresh_categories)
    resp = client.post("/api/rules/refresh", json={"mode": "full"})
    assert resp.status_code == 200
    assert captured == {"force": True, "mode": "full"}
    assert resp.json()["result"]["mode"] == "full"


def test_global_refresh_rule_catalog_mode_passthrough(client, monkeypatch) -> None:
    services = client.app.state.services
    captured: dict[str, object] = {}

    async def _fake_hub_refresh(
        force: bool = False,
        force_rule_catalog: bool = False,
        rule_catalog_mode: str = "incremental",
    ):
        captured["force"] = force
        captured["force_rule_catalog"] = force_rule_catalog
        captured["rule_catalog_mode"] = rule_catalog_mode
        return HubRuntime()

    monkeypatch.setattr(services.hub_service, "refresh", _fake_hub_refresh)
    resp = client.post("/api/refresh", json={"rule_catalog_mode": "full"})
    assert resp.status_code == 200
    assert captured == {
        "force": True,
        "force_rule_catalog": True,
        "rule_catalog_mode": "full",
    }
    assert resp.json()["ok"] is True


def test_refresh_policy_settings_api(client) -> None:
    current = client.get("/api/settings/refresh-policy")
    assert current.status_code == 200
    assert "rule_catalog_cache_hours" in current.json()["item"]
    assert "cn_cache_hours" in current.json()["item"]
    assert "standard_source_auto_pull_enabled" in current.json()["item"]
    assert "standard_source_auto_pull_interval_minutes" in current.json()["item"]

    updated = client.put(
        "/api/settings/refresh-policy",
        json={
            "rule_catalog_cache_hours": 12,
            "cn_cache_hours": 36,
            "standard_source_auto_pull_enabled": False,
            "standard_source_auto_pull_interval_minutes": 15,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["rule_catalog_cache_hours"] == 12
    assert updated.json()["item"]["cn_cache_hours"] == 36
    assert updated.json()["item"]["standard_source_auto_pull_enabled"] is False
    assert updated.json()["item"]["standard_source_auto_pull_interval_minutes"] == 15

    confirm = client.get("/api/settings/refresh-policy")
    assert confirm.status_code == 200
    assert confirm.json()["item"]["rule_catalog_cache_hours"] == 12
    assert confirm.json()["item"]["cn_cache_hours"] == 36
    assert confirm.json()["item"]["standard_source_auto_pull_enabled"] is False
    assert confirm.json()["item"]["standard_source_auto_pull_interval_minutes"] == 15


def test_llm_export_settings_api(client) -> None:
    current = client.get("/api/settings/llm-export")
    assert current.status_code == 200
    assert "rules_preferences" in current.json()["item"]
    assert "pins_preferences" in current.json()["item"]
    assert "directness_preferences" in current.json()["item"]

    updated = client.put(
        "/api/settings/llm-export",
        json={
            "rules_preferences": "Netflix 可以分配到中等质量组",
            "pins_preferences": "优先使用 AI 服务、流媒体 这样的中文分组名",
            "directness_preferences": "不确定时统一建议 PROXY",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["rules_preferences"] == "Netflix 可以分配到中等质量组"
    assert "流媒体" in updated.json()["item"]["pins_preferences"]
    assert "建议 PROXY" in updated.json()["item"]["directness_preferences"]

    reset = client.put(
        "/api/settings/llm-export",
        json={
            "rules_preferences": "   ",
            "pins_preferences": "",
            "directness_preferences": "",
        },
    )
    assert reset.status_code == 200
    assert "如果这里的指令与上方系统固定说明冲突，以这里为准。" in reset.json()["item"]["rules_preferences"]
    assert "当前可选目标组的名称、描述和已有分配样本" in reset.json()["item"]["rules_preferences"]
    assert "AI 服务" in reset.json()["item"]["pins_preferences"]
    assert "只在高度确定是中国大陆直连场景时建议 DIRECT" in reset.json()["item"]["directness_preferences"]


def test_llm_workflow_routing_endpoints(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=8),
                RuleCategory(
                    name="12306",
                    assigned_group="DIRECT",
                    rule_count=4,
                    locked=True,
                    lock_source="manual",
                    system_directness="DIRECT",
                ),
        ]
    )
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="hq_premium",
            sort_order=1,
            source="manual",
        )
    )

    workflows = client.get("/api/llm/workflows")
    assert workflows.status_code == 200
    assert [item["id"] for item in workflows.json()["items"]] == ["log-routing", "directness", "routing", "grouping"]

    exported = client.post(
        "/api/llm/workflows/routing/export",
        json={"intent_override": "OpenAI 更偏向中等质量", "sample_rule_limit": 2},
    )
    assert exported.status_code == 200
    data = exported.json()
    assert data["schema"] == "subhub.llm.routing.v1"
    assert data["intent_override"] == "OpenAI 更偏向中等质量"
    assert any(item["contract_id"] == "medium" for item in data["target_options"])
    openai = next(item for item in data["items"] if item["name"] == "OpenAI")
    assert openai["stored_contract_id"] == "hq_premium"
    assert openai["effective_contract_id"] == "hq_premium"

    preview = client.post(
        "/api/llm/workflows/routing/preview-import",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {
                "assignments": {
                    "OpenAI": "medium",
                    "12306": "medium",
                    "Unknown": "medium",
                    "Netflix": "direct",
                }
            },
        },
    )
    assert preview.status_code == 200
    preview_data = preview.json()
    assert [item["name"] for item in preview_data["changes"]] == ["OpenAI"]
    assert preview_data["changes"][0]["change_id"] == "routing:OpenAI"
    assert preview_data["skipped_locked"] == ["12306"]
    reasons = {(item["name"], item["reason"]) for item in preview_data["invalid_items"]}
    assert ("Unknown", "unknown_category") in reasons
    assert ("Netflix", "unknown_category") in reasons

    applied = client.post(
        "/api/llm/workflows/routing/apply",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {"OpenAI": "medium"},
        },
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] == 1

    categories = client.get("/api/rules/categories")
    assert categories.status_code == 200
    by_name = {item["name"]: item for item in categories.json()["items"]}
    assert by_name["OpenAI"]["assigned_group"] == "中等质量"
    assert by_name["OpenAI"]["stored_contract_id"] == "medium"
    assert by_name["OpenAI"]["effective_contract_id"] == "medium"


def test_llm_workflow_grouping_preserves_stored_contract_and_supports_description(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=8),
            RuleCategory(
                name="Ads",
                assigned_group="中等质量",
                rule_count=3,
                locked=True,
                lock_source="manual",
            ),
        ]
    )
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="",
            contract_id="hq_premium",
            sort_order=0,
            source="manual",
        )
    )

    exported = client.post("/api/llm/workflows/grouping/export", json={})
    assert exported.status_code == 200
    data = exported.json()
    assert data["schema"] == "subhub.llm.grouping.v1"

    preview = client.post(
        "/api/llm/workflows/grouping/preview-import",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {
                "groups": [
                    {
                        "name": "广告拦截",
                        "description": "需要路由到 REJECT 的分类",
                        "mode": BUSINESS_GROUP_MODE_AD_BLOCK,
                        "categories": ["OpenAI", "Ads"],
                    }
                ]
            },
        },
    )
    assert preview.status_code == 200
    preview_data = preview.json()
    assert preview_data["skipped_locked"] == ["Ads"]
    assert any(item["type"] == "create_group" and item["group_name"] == "广告拦截" for item in preview_data["changes"])
    assert any(item["type"] == "move_category" and item["name"] == "OpenAI" for item in preview_data["changes"])
    assert any(item["change_id"] == "grouping:create_group:广告拦截" for item in preview_data["changes"])

    applied = client.post(
        "/api/llm/workflows/grouping/apply",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {
                "groups": [
                    {
                        "name": "广告拦截",
                        "description": "需要路由到 REJECT 的分类",
                        "mode": BUSINESS_GROUP_MODE_AD_BLOCK,
                        "categories": ["OpenAI", "Ads"],
                    }
                ]
            },
        },
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] == 2

    groups = client.get("/api/rules/business-groups")
    assert groups.status_code == 200
    ad_group = next(item for item in groups.json()["items"] if item["name"] == "广告拦截")
    assert ad_group["description"] == "需要路由到 REJECT 的分类"
    assert ad_group["category_names"] == ["OpenAI"]

    categories = client.get("/api/rules/categories")
    assert categories.status_code == 200
    by_name = {item["name"]: item for item in categories.json()["items"]}
    assert by_name["OpenAI"]["catalog_group"] == "广告拦截"
    assert by_name["OpenAI"]["stored_contract_id"] == "hq_premium"
    assert by_name["OpenAI"]["effective_contract_id"] == "ad_block"
    assert by_name["OpenAI"]["effective_contract_source"] == "ad_block_group"
    assert by_name["Ads"]["catalog_group"] == ""


def test_llm_workflow_directness_preserves_stored_contract(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [
            RuleCategory(
                name="12306",
                assigned_group="DIRECT",
                rule_count=4,
                locked=True,
                lock_source="system",
                system_directness="DIRECT",
            ),
            RuleCategory(
                name="OpenAI",
                assigned_group="高质量-高倍率",
                rule_count=8,
                locked=True,
                lock_source="manual",
            ),
        ]
    )
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="12306",
            catalog_group="",
            contract_id="hq_standard",
            sort_order=0,
            source="manual",
        )
    )

    exported = client.post("/api/llm/workflows/directness/export", json={})
    assert exported.status_code == 200
    data = exported.json()
    assert data["schema"] == "subhub.llm.directness.v1"

    preview = client.post(
        "/api/llm/workflows/directness/preview-import",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {
                "12306": {"decision": "PROXY", "confidence": "high", "reason": "更适合走代理"},
                "OpenAI": {"decision": "DIRECT", "confidence": "low", "reason": "测试锁定"},
            },
        },
    )
    assert preview.status_code == 200
    preview_data = preview.json()
    assert [item["name"] for item in preview_data["changes"]] == ["12306"]
    assert preview_data["changes"][0]["change_id"] == "directness:12306"
    assert preview_data["skipped_locked"] == ["OpenAI"]

    applied = client.post(
        "/api/llm/workflows/directness/apply",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {
                "12306": {"decision": "PROXY", "confidence": "high", "reason": "更适合走代理"}
            },
        },
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] == 1

    categories = client.get("/api/rules/categories")
    assert categories.status_code == 200
    by_name = {item["name"]: item for item in categories.json()["items"]}
    assert by_name["12306"]["assigned_group"] == ""
    assert by_name["12306"]["directness_override"] == "PROXY"
    assert by_name["12306"]["stored_contract_id"] == "hq_standard"
    assert by_name["12306"]["effective_contract_id"] == "hq_standard"
    assert by_name["12306"]["locked"] is True
    assert by_name["12306"]["lock_source"] == "manual"

    reviews = services.repo.list_rule_category_directness_reviews(status="all")
    review = next(item for item in reviews if item.category_name == "12306")
    assert review.source == "llm-center"
    assert review.status == "applied"


def test_directness_review_endpoints(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [
            RuleCategory(
                name="12306",
                assigned_group="DIRECT",
                rule_count=10,
                rule_source="github",
                updated_at="",
                locked=True,
                system_directness="DIRECT",
                lock_source="system",
            ),
            RuleCategory(
                name="OpenAI",
                assigned_group="高质量-高倍率",
                rule_count=8,
                rule_source="github",
                updated_at="",
                locked=False,
                system_directness="PROXY",
            ),
        ]
    )
    services.repo.save_rule_cache("12306", ["DOMAIN-SUFFIX,12306.cn,PLACEHOLDER"])
    services.repo.save_rule_cache("OpenAI", ["DOMAIN-SUFFIX,openai.com,PLACEHOLDER"])

    exported = client.get("/api/rules/directness/export")
    assert exported.status_code == 200
    assert exported.json()["schema"] == "subhub.rules.directness.review.v1"
    assert exported.json()["scope"] == "all"
    assert exported.json()["candidates"] == ["12306", "OpenAI"]

    imported = client.post(
        "/api/rules/directness/import",
        json={
            "12306": {"decision": "PROXY", "confidence": "high", "reason": "跨境资源混合"},
            "OpenAI": {"decision": "PROXY", "confidence": "medium", "reason": "保持现状"},
            "Unknown": "DIRECT",
        },
    )
    assert imported.status_code == 200
    assert imported.json()["inserted"] == 1
    assert imported.json()["skipped_same"] == ["OpenAI"]
    assert len(imported.json()["invalid_items"]) == 1

    queue = client.get("/api/rules/directness/reviews?status=pending")
    assert queue.status_code == 200
    assert queue.json()["count"] == 1
    assert queue.json()["items"][0]["current_effective_directness"] == "DIRECT"
    review_id = queue.json()["items"][0]["id"]

    applied = client.post(
        "/api/rules/directness/reviews/apply",
        json={"review_ids": [review_id], "action": "accept"},
    )
    assert applied.status_code == 200
    assert applied.json()["updated"] == 1

    categories = client.get("/api/rules/categories")
    assert categories.status_code == 200
    by_name = {item["name"]: item for item in categories.json()["items"]}
    assert by_name["12306"]["assigned_group"] == ""
    assert by_name["12306"]["directness_override"] == "PROXY"
    assert by_name["12306"]["locked"] is True
    assert by_name["12306"]["lock_source"] == "manual"


def test_llm_workflow_routing_apply_supports_selected_change_ids(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=8),
            RuleCategory(name="GitHub", assigned_group="高质量", rule_count=6),
        ]
    )
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="",
            contract_id="hq_premium",
            sort_order=0,
            source="manual",
        )
    )
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="GitHub",
            catalog_group="",
            contract_id="hq_standard",
            sort_order=1,
            source="manual",
        )
    )

    exported = client.post("/api/llm/workflows/routing/export", json={})
    data = exported.json()
    preview = client.post(
        "/api/llm/workflows/routing/preview-import",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {"OpenAI": "medium", "GitHub": "medium"},
        },
    )
    assert preview.status_code == 200
    change_ids = [item["change_id"] for item in preview.json()["changes"]]
    assert change_ids == ["routing:GitHub", "routing:OpenAI"] or change_ids == ["routing:OpenAI", "routing:GitHub"]

    applied = client.post(
        "/api/llm/workflows/routing/apply",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {"OpenAI": "medium", "GitHub": "medium"},
            "selected_change_ids": ["routing:OpenAI"],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] == 1
    assert applied.json()["applied_change_ids"] == ["routing:OpenAI"]

    categories = client.get("/api/rules/categories")
    by_name = {item["name"]: item for item in categories.json()["items"]}
    assert by_name["OpenAI"]["stored_contract_id"] == "medium"
    assert by_name["GitHub"]["stored_contract_id"] == "hq_standard"


def test_llm_workflow_grouping_apply_supports_selected_change_ids(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories([RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=8)])

    exported = client.post("/api/llm/workflows/grouping/export", json={})
    data = exported.json()
    preview = client.post(
        "/api/llm/workflows/grouping/preview-import",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {
                "groups": [
                    {
                        "name": "AI 服务",
                        "description": "AI / LLM / 编程助手",
                        "mode": BUSINESS_GROUP_MODE_STANDARD,
                        "categories": ["OpenAI"],
                    }
                ]
            },
        },
    )
    assert preview.status_code == 200

    applied = client.post(
        "/api/llm/workflows/grouping/apply",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {
                "groups": [
                    {
                        "name": "AI 服务",
                        "description": "AI / LLM / 编程助手",
                        "mode": BUSINESS_GROUP_MODE_STANDARD,
                        "categories": ["OpenAI"],
                    }
                ]
            },
            "selected_change_ids": ["grouping:create_group:AI 服务"],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] == 1
    assert applied.json()["applied_change_ids"] == ["grouping:create_group:AI 服务"]

    groups = client.get("/api/rules/business-groups")
    assert groups.status_code == 200
    ai_group = next(item for item in groups.json()["items"] if item["name"] == "AI 服务")
    assert ai_group["category_names"] == []

    categories = client.get("/api/rules/categories")
    by_name = {item["name"]: item for item in categories.json()["items"]}
    assert by_name["OpenAI"]["catalog_group"] == ""


def test_rule_categories_fall_back_to_pin_group_when_service_catalog_group_is_empty(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories([RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=8)])
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="hq_premium",
            sort_order=0,
            source="manual",
        )
    )

    with services.repo._lock:
        services.repo._conn.execute(
            "UPDATE service_catalog_entries SET catalog_group='' WHERE category_name=?",
            ("OpenAI",),
        )
        services.repo._conn.commit()

    categories = client.get("/api/rules/categories")
    assert categories.status_code == 200
    by_name = {item["name"]: item for item in categories.json()["items"]}
    assert by_name["OpenAI"]["catalog_group"] == "AI 服务"
    assert by_name["OpenAI"]["pin_group"] == "AI 服务"


def test_llm_workflow_grouping_export_falls_back_to_pin_group_when_service_catalog_group_is_empty(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories([RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=8)])
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="hq_premium",
            sort_order=0,
            source="manual",
        )
    )

    with services.repo._lock:
        services.repo._conn.execute(
            "UPDATE service_catalog_entries SET catalog_group='' WHERE category_name=?",
            ("OpenAI",),
        )
        services.repo._conn.commit()

    exported = client.post("/api/llm/workflows/grouping/export", json={})
    assert exported.status_code == 200
    item = next(entry for entry in exported.json()["items"] if entry["name"] == "OpenAI")
    assert item["catalog_group"] == "AI 服务"


def test_llm_workflow_grouping_apply_persists_after_repo_restart(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories([RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=8)])

    exported = client.post("/api/llm/workflows/grouping/export", json={})
    assert exported.status_code == 200
    fingerprint = exported.json()["snapshot_fingerprint"]

    applied = client.post(
        "/api/llm/workflows/grouping/apply",
        json={
            "snapshot_fingerprint": fingerprint,
            "result": {
                "groups": [
                    {
                        "name": "AI 服务",
                        "description": "AI / LLM / 编程助手",
                        "mode": BUSINESS_GROUP_MODE_STANDARD,
                        "categories": ["OpenAI"],
                    }
                ]
            },
        },
    )
    assert applied.status_code == 200

    restarted_repo = type(services.repo)(services.settings, services.repo._cipher)
    category = restarted_repo.get_service_catalog_entry("OpenAI")
    assert category is not None
    assert category.catalog_group == "AI 服务"

    with restarted_repo._lock:
        row = restarted_repo._conn.execute(
            "SELECT pin_group FROM pinned_categories WHERE category_name=?",
            ("OpenAI",),
        ).fetchone()
    assert row is not None
    assert str(row["pin_group"] or "") == "AI 服务"


def test_llm_workflow_directness_apply_supports_selected_change_ids(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [
            RuleCategory(
                name="12306",
                assigned_group="DIRECT",
                rule_count=4,
                locked=True,
                lock_source="system",
                system_directness="DIRECT",
            ),
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=8),
        ]
    )
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="12306",
            catalog_group="",
            contract_id="hq_standard",
            sort_order=0,
            source="manual",
        )
    )

    exported = client.post("/api/llm/workflows/directness/export", json={})
    data = exported.json()
    preview = client.post(
        "/api/llm/workflows/directness/preview-import",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {
                "12306": {"decision": "PROXY", "confidence": "high", "reason": "更适合走代理"},
                "OpenAI": {"decision": "DIRECT", "confidence": "high", "reason": "需要兜底直连"},
            },
        },
    )
    assert preview.status_code == 200

    applied = client.post(
        "/api/llm/workflows/directness/apply",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {
                "12306": {"decision": "PROXY", "confidence": "high", "reason": "更适合走代理"},
                "OpenAI": {"decision": "DIRECT", "confidence": "high", "reason": "需要兜底直连"},
            },
            "selected_change_ids": ["directness:12306"],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] == 1
    assert applied.json()["applied_change_ids"] == ["directness:12306"]

    categories = client.get("/api/rules/categories")
    by_name = {item["name"]: item for item in categories.json()["items"]}
    assert by_name["12306"]["directness_override"] == "PROXY"
    assert by_name["12306"]["locked"] is True
    assert by_name["12306"]["lock_source"] == "manual"
    assert by_name["OpenAI"]["directness_override"] == ""
    assert by_name["OpenAI"]["locked"] is False


def test_llm_workflow_apply_rejects_invalid_selected_change_ids(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories([RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=8)])
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="",
            contract_id="hq_premium",
            sort_order=0,
            source="manual",
        )
    )

    exported = client.post("/api/llm/workflows/routing/export", json={})
    data = exported.json()
    applied = client.post(
        "/api/llm/workflows/routing/apply",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {"OpenAI": "medium"},
            "selected_change_ids": ["routing:not-exists"],
        },
    )
    assert applied.status_code == 400
    assert applied.json()["detail"] == "invalid selected_change_ids"


def test_log_routing_workflow_upload_export_preview_and_apply(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=8),
            RuleCategory(name="WeChat", assigned_group="DIRECT", rule_count=6, system_directness="DIRECT"),
        ]
    )
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="hq_premium",
            sort_order=0,
            source="manual",
        )
    )
    services.repo.save_rule_cache("OpenAI", ["DOMAIN-SUFFIX,openai.com,PLACEHOLDER"])
    services.repo.save_rule_cache("WeChat", ["DOMAIN-SUFFIX,weixin.qq.com,PLACEHOLDER"])

    created = client.post("/api/llm/log-routing/sessions")
    assert created.status_code == 200
    session_id = created.json()["item"]["session_id"]

    clash_log = "\n".join(
        [
            '[2026-03-31 23:33:25.803] time="2026-03-31T23:33:25.802243000+08:00" level=info msg="[TCP] 127.0.0.1:58474(Browser Helper) --> api.raindrop.io:443 match Match using 兜底代理[链式家宽 | 家宽1]"',
            '[2026-03-31 23:33:26.803] time="2026-03-31T23:33:26.802243000+08:00" level=info msg="[TCP] 127.0.0.1:58475(Browser Helper) --> openai.com:443 match RuleSet(catalog-rules-hq_premium) using 高质量-高倍率[节点A]"',
        ]
    )
    uploaded = client.post(
        f"/api/llm/log-routing/sessions/{session_id}/files",
        files={"file": ("service.log", clash_log.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["file"]["detected_client"] == "clash"

    candidates = client.get(f"/api/llm/log-routing/sessions/{session_id}/candidates")
    assert candidates.status_code == 200
    payload = candidates.json()
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["root_domain"] == "raindrop.io"
    assert payload["candidates"][0]["current_match_status"] == "fallback_only"

    exported = client.post(
        f"/api/llm/log-routing/sessions/{session_id}/export",
        json={"intent_override": "优先分到中等质量", "sample_evidence_limit": 2},
    )
    assert exported.status_code == 200
    export_data = exported.json()
    assert export_data["schema"] == "subhub.llm.log_routing.v1"
    assert "medium" in [item["id"] for item in export_data["available_routes"]]
    assert export_data["snapshot_id"]

    patch = {
        "schema": "subhub.patch.v1",
        "base_revision": export_data["snapshot_id"],
        "actions": [
            {
                "id": "raindrop-category",
                "type": "ensure_manual_category",
                "name": "Raindrop",
                "default_policy": "group",
                "default_group": "中等质量",
                "locked": False,
            },
            {
                "id": "raindrop-route",
                "type": "set_category_route",
                "category": "Raindrop",
                "contract_id": "medium",
            },
            {
                "id": "raindrop-rule",
                "type": "add_category_rule",
                "category": "Raindrop",
                "rule_type": "DOMAIN-SUFFIX",
                "value": "raindrop.io",
            },
        ],
    }

    preview = client.post(
        f"/api/llm/log-routing/sessions/{session_id}/preview",
        json={"snapshot_id": export_data["snapshot_id"], "patch": patch},
    )
    assert preview.status_code == 200
    assert preview.json()["ok"] is True
    assert [item["status"] for item in preview.json()["changes"]] == ["planned", "planned", "planned"]

    applied = client.post(
        f"/api/llm/log-routing/sessions/{session_id}/apply",
        json={
            "snapshot_id": export_data["snapshot_id"],
            "patch": patch,
            "selected_action_ids": ["raindrop-category", "raindrop-route", "raindrop-rule"],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["ok"] is True
    assert applied.json()["applied_count"] == 3

    categories = client.get("/api/rules/categories")
    by_name = {item["name"]: item for item in categories.json()["items"]}
    assert by_name["Raindrop"]["stored_contract_id"] == "medium"

    rules = client.get("/api/rules/categories/Raindrop/custom")
    assert rules.status_code == 200
    assert any(item["value"] == "raindrop.io" for item in rules.json()["items"])


def test_log_routing_workflow_parses_surge_and_shadowrocket_fallback_only(client) -> None:
    created = client.post("/api/llm/log-routing/sessions")
    assert created.status_code == 200
    session_id = created.json()["item"]["session_id"]

    surge_entries = [
        {
            "remoteHost": "api.segment.io",
            "policyName": "兜底代理",
            "processLocalizedName": "Safari",
            "clientInfo": {"displayName": "Mac"},
            "startDate": "2026-03-31T23:32:01Z",
            "notes": [
                "23:32:01.162301 [Rule] Rule matched: FINAL",
                "23:32:01.162340 [Rule] Policy decision path: 兜底代理 -> 链式家宽·自动",
            ],
        },
        {
            "remoteHost": "weixin.qq.com",
            "policyName": "DIRECT",
            "processLocalizedName": "Safari",
            "clientInfo": {"displayName": "Mac"},
            "startDate": "2026-03-31T23:33:01Z",
            "notes": [
                "23:33:01.162301 [Rule] Rule matched: DOMAIN-SUFFIX,weixin.qq.com",
            ],
        },
    ]
    surge_uploaded = client.post(
        f"/api/llm/log-routing/sessions/{session_id}/files",
        files={"file": ("index.json", json.dumps(surge_entries).encode("utf-8"), "application/json")},
    )
    assert surge_uploaded.status_code == 200
    assert surge_uploaded.json()["file"]["detected_client"] == "surge"

    sr_db = io.BytesIO()
    db_path = client.app.state.services.repo.data_dir / "shadowrocket-test.db"
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE logging_content(docid INTEGER PRIMARY KEY, c0url TEXT, c1ua TEXT, c2result TEXT, c3type TEXT, c4created TEXT)"
        )
        conn.execute(
            "INSERT INTO logging_content(docid, c0url, c1ua, c2result, c3type, c4created) VALUES (1, ?, ?, ?, ?, ?)",
            ("walmart.com:443", "TCP Stream", "FINAL,PROXY # 兜底代理", "PROXY", "2026-03-31 23:20:12"),
        )
        conn.execute(
            "INSERT INTO logging_content(docid, c0url, c1ua, c2result, c3type, c4created) VALUES (2, ?, ?, ?, ?, ?)",
            ("szextshort.weixin.qq.com:80", "TCP Stream", "GEOIP,CN,DIRECT", "DIRECT", "2026-03-31 23:20:13"),
        )
        conn.commit()
    finally:
        conn.close()
    try:
        content = db_path.read_bytes()
    finally:
        db_path.unlink(missing_ok=True)
    shadowrocket_uploaded = client.post(
        f"/api/llm/log-routing/sessions/{session_id}/files",
        files={"file": ("proxy.db", content, "application/octet-stream")},
    )
    assert shadowrocket_uploaded.status_code == 200
    assert shadowrocket_uploaded.json()["file"]["detected_client"] == "shadowrocket"

    candidates = client.get(f"/api/llm/log-routing/sessions/{session_id}/candidates")
    assert candidates.status_code == 200
    roots = [item["root_domain"] for item in candidates.json()["candidates"]]
    assert "segment.io" in roots
    assert "walmart.com" in roots
    assert "weixin.qq.com" not in roots


def test_log_routing_workflow_rejects_disallowed_action_and_unknown_route(client) -> None:
    created = client.post("/api/llm/log-routing/sessions")
    session_id = created.json()["item"]["session_id"]

    exported = client.post(f"/api/llm/log-routing/sessions/{session_id}/export", json={})
    snapshot_id = exported.json()["snapshot_id"]

    bad_action = client.post(
        f"/api/llm/log-routing/sessions/{session_id}/preview",
        json={
            "snapshot_id": snapshot_id,
            "patch": {
                "schema": "subhub.patch.v1",
                "base_revision": snapshot_id,
                "actions": [
                    {
                        "id": "lock",
                        "type": "set_category_lock",
                        "category": "X",
                        "locked": True,
                    }
                ],
            },
        },
    )
    assert bad_action.status_code == 400
    assert "unsupported action type" in bad_action.json()["detail"]

    bad_route = client.post(
        f"/api/llm/log-routing/sessions/{session_id}/preview",
        json={
            "snapshot_id": snapshot_id,
            "patch": {
                "schema": "subhub.patch.v1",
                "base_revision": snapshot_id,
                "actions": [
                    {
                        "id": "route",
                        "type": "set_category_route",
                        "category": "X",
                        "contract_id": "not_real",
                    }
                ],
            },
        },
    )
    assert bad_route.status_code == 400
    assert "unknown route contract" in bad_route.json()["detail"]


def test_subscription_endpoints_return_config(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_standard_source(
        StandardSource(
            id="s1",
            name="机场B",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d1",
            device_key="mac",
            device_name="Mac",
            token="tok1",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s1",
            name="源A",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="高质量-高倍率",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s1",
        [
            NodeRecord(
                name="[机场B] n1",
                host="n1.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
                source_id="s1",
                source_type="standard",
            )
        ],
    )

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    clash = client.get(_scenario_sub_path("tok1", "clash.yaml"))
    assert clash.status_code == 200
    assert clash.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert clash.headers["content-disposition"] == 'attachment; filename="SubHub-for-Mac-default.yaml"'
    assert clash.headers["expires"] == "0"
    assert clash.headers["pragma"] == "no-cache"
    assert "中等质量" in clash.text
    assert "proxy-providers:" in clash.text
    assert "enable: true" in clash.text
    assert "listen: 127.0.0.1:1053" in clash.text
    assert "enhanced-mode: redir-host" in clash.text
    assert "use-hosts: true" in clash.text
    assert "respect-rules: true" in clash.text
    assert "mixed-port: 7890" in clash.text
    assert "dns-hijack:" not in clash.text
    assert "fake-ip-filter" not in clash.text
    assert "always-real-ip" not in (yaml.safe_load(clash.text).get("dns") or {})
    assert "route-exclude-address" not in clash.text
    clash_payload = yaml.safe_load(clash.text)
    premium_group = next(
        item for item in clash_payload["proxy-groups"] if item["name"] == "高质量-高倍率"
    )
    medium_provider_url = str(clash_payload["proxy-providers"]["medium"]["url"])
    assert premium_group["type"] == "fallback"
    assert premium_group["proxies"][-1] == "REJECT"
    assert "DIRECT" not in premium_group["proxies"]
    assert "/clash/providers/medium.yaml" in medium_provider_url
    assert "rev=" in medium_provider_url
    assert "exp=" in medium_provider_url
    assert "sig=" in medium_provider_url

    clash_provider = client.get(_scenario_sub_path("tok1", "clash/providers/medium.yaml"))
    assert clash_provider.status_code == 200
    assert clash_provider.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert clash_provider.headers["content-type"].startswith("application/x-yaml")
    assert clash_provider.headers["expires"] == "0"
    assert clash_provider.headers["pragma"] == "no-cache"
    assert "proxies:" in clash_provider.text
    assert "[机场B] n1" in clash_provider.text
    assert "proxy-groups:" not in clash_provider.text
    signed_clash_provider = client.get(medium_provider_url.replace("http://testserver", ""))
    assert signed_clash_provider.status_code == 200
    invalid_signed_clash_provider = client.get(
        medium_provider_url.replace("sig=", "sig=broken", 1).replace("http://testserver", "")
    )
    assert invalid_signed_clash_provider.status_code == 403

    sr = client.get(_scenario_sub_path("tok1", "shadowrocket.conf"))
    assert sr.status_code == 200
    assert "[Proxy]" in sr.text
    assert "[Proxy Group]" in sr.text
    assert "tun-excluded-routes = 6.6.6.6/32,2000::6666/128" in sr.text
    assert "always-real-ip = *.heiyu.space,*.lazycat.cloud,*.lazycatmicroserver.com" in sr.text

    sr_nodes = client.get(_scenario_sub_path("tok1", "shadowrocket-nodes.txt"))
    assert sr_nodes.status_code == 200
    assert sr_nodes.headers["content-type"].startswith("text/plain")
    assert sr_nodes.headers["content-disposition"] == 'attachment; filename="SubHub-for-Mac-leaf-nodes.txt"'
    assert sr_nodes.headers["profile-update-interval"] == "1800"
    assert "subscription-userinfo" not in sr_nodes.headers
    decoded_sr_nodes = base64.b64decode(sr_nodes.text.encode("ascii")).decode("utf-8")
    assert "http://n1.example.com:443#" in decoded_sr_nodes
    assert "%E4%B8%AD%E7%AD%89%E8%B4%A8%E9%87%8F%20%7C%20%5B%E6%9C%BA%E5%9C%BAB%5D%20n1" in decoded_sr_nodes

    sr_legacy = client.get(
        _scenario_sub_path("tok1", "shadowrocket-legacy.conf"),
        follow_redirects=False,
    )
    assert sr_legacy.status_code == 308
    assert sr_legacy.headers["location"] == _scenario_sub_path("tok1", "shadowrocket.conf")
    default_sr_legacy = client.get(
        "/sub/device/tok1/shadowrocket-legacy.conf",
        follow_redirects=False,
    )
    assert default_sr_legacy.status_code == 308
    assert default_sr_legacy.headers["location"] == "/sub/device/tok1/shadowrocket.conf"

    surge = client.get(_scenario_sub_path("tok1", "surge.conf"))
    assert surge.status_code == 200
    assert "[Proxy Group]" in surge.text
    assert "tun-excluded-routes = 6.6.6.6/32,2000::6666/128" in surge.text
    assert "always-real-ip = *.heiyu.space,*.lazycat.cloud,*.lazycatmicroserver.com" in surge.text
    assert "# Render warnings" not in surge.text
    assert "# Build blockers" not in surge.text

    clash_subscription = client.get(_scenario_sub_path("tok1", "clash.yaml"))
    assert clash_subscription.status_code == 200
    assert "proxy-providers:" in clash_subscription.text
    assert "fake-ip-filter" not in clash_subscription.text
    assert "always-real-ip" not in (yaml.safe_load(clash_subscription.text).get("dns") or {})
    assert "mixed-port: 7890" in clash_subscription.text
    assert "route-exclude-address" not in clash_subscription.text
    assert "use-hosts: true" in clash_subscription.text

    shadowrocket_subscription = client.get(_scenario_sub_path("tok1", "shadowrocket.conf"))
    assert shadowrocket_subscription.status_code == 200
    assert "[Proxy]" in shadowrocket_subscription.text
    assert "tun-excluded-routes = 6.6.6.6/32,2000::6666/128" in shadowrocket_subscription.text
    assert "always-real-ip = *.heiyu.space,*.lazycat.cloud,*.lazycatmicroserver.com" in shadowrocket_subscription.text

    shadowrocket_legacy_subscription = client.get(
        _scenario_sub_path("tok1", "shadowrocket-legacy.conf"),
        follow_redirects=False,
    )
    assert shadowrocket_legacy_subscription.status_code == 308
    assert shadowrocket_legacy_subscription.headers["location"] == _scenario_sub_path(
        "tok1", "shadowrocket.conf"
    )

    removed_profile = client.get(f"{_scenario_sub_path('tok1', 'clash.yaml')}?profile=raw")
    assert removed_profile.status_code == 400
    assert removed_profile.json()["detail"] == "profile/flavor query parameters are no longer supported"
    removed_flavor = client.get(f"{_scenario_sub_path('tok1', 'surge.conf')}?flavor=raw")
    assert removed_flavor.status_code == 400
    assert removed_flavor.json()["detail"] == "profile/flavor query parameters are no longer supported"
    invalid_provider = client.get(_scenario_sub_path("tok1", "clash/providers/not-found.yaml"))
    assert invalid_provider.status_code == 404

    devices = client.get("/api/devices")
    assert devices.status_code == 200
    device = next(item for item in devices.json()["items"] if item.get("device_name") == "Mac")
    subscription_id = device["subscription_id"]
    links = device["links"]
    overlay_status = device["overlay_status"]
    assert device["scenario_slug"] == DEFAULT_SCENARIO_SLUG
    assert links["surge_url"].endswith(f"/sub/device/{subscription_id}/{DEFAULT_SCENARIO_SLUG}/surge.conf")
    assert links["shadowrocket_url"].startswith(f"http://testserver/sub/device/{subscription_id}/{DEFAULT_SCENARIO_SLUG}/shadowrocket-")
    assert links["shadowrocket_url"].endswith(".conf")
    assert links["shadowrocket_nodes_url"].endswith(f"/sub/device/{subscription_id}/{DEFAULT_SCENARIO_SLUG}/shadowrocket-nodes.txt")
    assert "shadowrocket_legacy_url" not in links
    assert "shadowrocket://config/add" in links["shadowrocket_scheme"]
    assert "surge:///install-config" in links["surge_scheme"]
    assert "profile%3D" not in links["clash_scheme"]
    assert "flavor%3D" not in links["clash_scheme"]
    assert "profile%3D" not in links["shadowrocket_scheme"]
    assert "flavor%3D" not in links["shadowrocket_scheme"]
    assert "profile%3D" not in links["surge_scheme"]
    assert "flavor%3D" not in links["surge_scheme"]
    assert links["surge_mac_overlay_url"].endswith(f"/sub/device/{subscription_id}/{DEFAULT_SCENARIO_SLUG}/surge-mac-overlay.conf")
    assert "surge:///install-config" in links["surge_mac_overlay_scheme"]
    assert overlay_status["available"] is False
    assert overlay_status["reason_code"] == "missing_templates"
    assert overlay_status["renderable_process_rule_count"] == 0
    assert overlay_status["renderable_external_proxy_program_count"] == 0


def test_devices_list_falls_back_to_first_enabled_scenario_when_default_is_disabled(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-fallback",
            device_key="mac-fallback",
            device_name="Mac Fallback",
            token="tok-fallback",
            enabled=True,
        )
    )
    default_scenario = services.repo.get_scenario("scenario-default")
    assert default_scenario is not None
    services.repo.save_scenario(
        ScenarioProfile(
            id=default_scenario.id,
            slug=default_scenario.slug,
            name=default_scenario.name,
            description=default_scenario.description,
            enabled=False,
            sort_order=default_scenario.sort_order,
            settings=default_scenario.settings,
            editor_state=default_scenario.editor_state,
        )
    )
    services.repo.save_scenario(
        ScenarioProfile(
            id="scenario-work",
            slug="work",
            name="Work",
            enabled=True,
            sort_order=-1,
        )
    )

    devices = client.get("/api/devices")
    assert devices.status_code == 200
    device = next(item for item in devices.json()["items"] if item["device_name"] == "Mac Fallback")
    subscription_id = device["subscription_id"]
    assert device["scenario_id"] == "scenario-work"
    assert device["scenario_slug"] == "work"
    assert device["links"]["surge_url"].endswith(f"/sub/device/{subscription_id}/work/surge.conf")


def test_shadowrocket_nodes_subscription_includes_userinfo_for_single_gorelay_source(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_gorelay_account(
        GoRelayAccount(
            id="acc-1",
            name="家宽A",
            login_url="https://relay.example.com",
            rules_url="https://relay.example.com/rules",
            gorelay_username="u",
            gorelay_password="p",
            enabled=True,
        )
    )
    services.repo.upsert_gorelay_device_subscription(
        GoRelayDeviceSubscription(
            id="gsub-1",
            account_id="acc-1",
            device_key="mac",
            device_name="Mac",
            token="tok-gorelay",
            enabled=True,
        )
    )
    services.repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="acc-1",
                snapshot_id="snap-1",
                created_at="2026-01-01T00:00:00Z",
                node_count=1,
                device_count=1,
                status="success",
            ),
            collected_rules=[],
            device_nodes={
                "mac": [
                    NodeRecord(
                        name="电信 · 3x · IPLC",
                        host="relay.example.com",
                        port=443,
                        protocol="socks5",
                        quality_group="高质量-高倍率",
                        source_id="acc-1",
                        source_type="gorelay",
                        account_id="acc-1",
                        device_key="mac",
                        device_name="Mac",
                    )
                ]
            },
            device_names={"mac": "Mac"},
            pending_bindings=[],
            source_status={
                "quota": {
                    "traffic_used": 123,
                    "traffic_enable": 456,
                    "expire": 1700000000,
                }
            },
        )
    )
    services.repo.save_gorelay_active_snapshot_id("acc-1", "snap-1")

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    sr_nodes = client.get(_scenario_sub_path("tok-gorelay", "shadowrocket-nodes.txt"))
    assert sr_nodes.status_code == 200
    assert sr_nodes.headers["subscription-userinfo"] == (
        "upload=123; download=0; total=456; expire=1700000000"
    )


def test_clash_subscription_sanitizes_legacy_cidr_rules(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d1",
            device_key="mac",
            device_name="Mac",
            token="tok1",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-cidr6",
            name="源CIDR6",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-cidr6",
        [
            NodeRecord(
                name="medium-1",
                host="medium.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
            )
        ],
    )
    services.repo.save_rule_categories(
        [
            RuleCategory(name="STUN", assigned_group="中等质量", rule_count=3),
        ]
    )
    services.repo.save_rule_cache(
        "STUN",
        [
            "IP-CIDR6,2001:db8::1,PLACEHOLDER",
            "IP-CIDR6,invalid-ipv6,PLACEHOLDER",
            "DOMAIN-SUFFIX,stun.example.com,PLACEHOLDER",
        ],
    )
    services.repo.save_custom_rule(
        CustomRule(
            id="global-ipv6",
            rule_type="IP-CIDR6",
            value="2001:db8::2",
            target_group="DIRECT",
            category_name="",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    services.repo.save_custom_rule(
        CustomRule(
            id="global-invalid-ipv6",
            rule_type="IP-CIDR6",
            value="invalid-ipv6",
            target_group="DIRECT",
            category_name="",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    clash = client.get(_scenario_sub_path("tok1", "clash.yaml"))
    assert clash.status_code == 200
    clash_payload = yaml.safe_load(clash.text)
    assert "RULE-SET,catalog-rules-medium,中等质量" in clash_payload["rules"]
    assert "RULE-SET,manual-rules-direct,DIRECT" in clash_payload["rules"]
    assert "invalid-ipv6" not in clash.text
    medium_rules = client.get(_scenario_sub_path("tok1", "clash/rules/catalog-rules-medium.list"))
    assert medium_rules.status_code == 200
    assert medium_rules.text == (
        "DOMAIN-SUFFIX,stun.example.com\n"
        "IP-CIDR6,2001:db8::1/128,no-resolve\n"
    )
    direct_rules = client.get(_scenario_sub_path("tok1", "clash/rules/manual-rules-direct.list"))
    assert direct_rules.status_code == 200
    assert direct_rules.text == "IP-CIDR6,2001:db8::2/128,no-resolve\n"


def test_clash_preview_summary_includes_render_warnings(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-domain-ip",
            device_key="mac",
            device_name="Mac",
            token="tok-domain-ip",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-domain-ip",
            name="源DomainIP",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="低质量大流量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-domain-ip",
        [
            NodeRecord(
                name="bulk-1",
                host="bulk.example.com",
                port=443,
                protocol="http",
                quality_group="低质量大流量",
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="LegacyIPDomains", assigned_group="低质量大流量", rule_count=2)]
    )
    services.repo.save_rule_cache(
        "LegacyIPDomains",
        [
            "DOMAIN,103.224.182.210,PLACEHOLDER",
            "DOMAIN,2001:db8::1,PLACEHOLDER",
        ],
    )

    summary = client.get("/api/devices/tok-domain-ip/preview-summary?target=clash")
    assert summary.status_code == 200
    warning_codes = [item["code"] for item in summary.json()["summary"]["warnings"]]
    assert warning_codes.count("clash-domain-ip-autofixed") == 2

    preview = client.get("/api/devices/tok-domain-ip/render-preview?target=clash")
    assert preview.status_code == 200
    preview_payload = yaml.safe_load(preview.json()["content"])
    assert "RULE-SET,catalog-rules-bulk,低质量大流量" in preview_payload["rules"]
    bulk_rules = client.get(_scenario_sub_path("tok-domain-ip", "clash/rules/catalog-rules-bulk.list"))
    assert bulk_rules.status_code == 200
    assert bulk_rules.text == (
        "IP-CIDR,103.224.182.210/32,no-resolve\n"
        "IP-CIDR6,2001:db8::1/128,no-resolve\n"
    )


def test_preview_summary_surfaces_shared_rule_precedence_warnings(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-precedence",
            device_key="ipad",
            device_name="iPad",
            token="tok-precedence-preview",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-precedence",
            name="源Precedence",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-precedence",
        [
            NodeRecord(
                name="medium-1",
                host="medium.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
            )
        ],
    )
    services.repo.save_custom_rule(
        CustomRule(
            id="global-custom-medium",
            rule_type="DOMAIN",
            value="custom.example.com",
            target_group="中等质量",
            category_name="",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    services.repo.save_rule_categories(
        [
            RuleCategory(name="PremiumWins", assigned_group="高质量-高倍率", rule_count=1),
            RuleCategory(name="DirectLoses", assigned_group="DIRECT", rule_count=1),
        ]
    )
    services.repo.save_rule_cache("PremiumWins", ["DOMAIN,custom.example.com,PLACEHOLDER"])
    services.repo.save_rule_cache("DirectLoses", ["DOMAIN,custom.example.com,PLACEHOLDER"])

    summary = client.get("/api/devices/tok-precedence-preview/preview-summary?target=surge")
    assert summary.status_code == 200
    warning_codes = [item["code"] for item in summary.json()["summary"]["warnings"]]
    assert "conflicting-rule-target" in warning_codes

    messages = [item["message"] for item in summary.json()["summary"]["warnings"]]
    assert any("kept 中等质量" in message and "dropped DIRECT" in message for message in messages)


def test_preview_summary_reports_protocol_diagnostics_buckets(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-diag",
            device_key="diag",
            device_name="Diag",
            token="tok-diag",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-diag",
            name="源A",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-diag",
        [
            NodeRecord(
                name="vless-ext",
                host="vless.example.com",
                port=443,
                protocol="vless",
                quality_group="中等质量",
                username="uuid-vless",
                raw={
                    "uuid": "uuid-vless",
                    "flow": "xtls-rprx-vision",
                    "packet_encoding": "packetaddr",
                    "reality_opts": {"public-key": "pub-key"},
                },
            ),
            NodeRecord(
                name="tuic-v4",
                host="tuic.example.com",
                port=9443,
                protocol="tuic",
                quality_group="中等质量",
                raw={"token": "token-v4", "tuic_version": 4},
            ),
        ],
    )

    surge_summary = client.get("/api/devices/tok-diag/preview-summary?target=surge")
    assert surge_summary.status_code == 200
    surge_diags = surge_summary.json()["summary"]["diagnostics"]
    assert any(item["code"] == "surge-vless-refused" for item in surge_diags["refused"])

    shadowrocket_summary = client.get("/api/devices/tok-diag/preview-summary?target=shadowrocket")
    assert shadowrocket_summary.status_code == 200
    shadowrocket_diags = shadowrocket_summary.json()["summary"]["diagnostics"]
    pending_codes = [item["code"] for item in shadowrocket_diags["pending_validation"]]
    assert "shadowrocket-tuic-v4-pending-validation" in pending_codes
    assert "shadowrocket-vless-extension-pending-validation" in pending_codes


def test_lazycat_profile_settings_api_and_subscription_override(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d1",
            device_key="mac",
            device_name="Mac",
            token="tok1",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s1",
            name="源A",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="高质量-高倍率",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s1",
        [
            NodeRecord(
                name="[机场B] n1",
                host="n1.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
                source_id="s1",
                source_type="standard",
            )
        ],
    )

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    got = client.get("/api/general-profile")
    assert got.status_code == 200
    assert got.json()["item"]["settings"]["clash_fake_ip_filter"]
    assert got.json()["item"]["settings"]["clash_dns_use_hosts"] is True
    assert got.json()["item"]["settings"]["clash_mixed_port"] == 7890
    assert got.json()["item"]["settings"]["clash_udp_default_enabled"] is True
    assert got.json()["item"]["settings"]["shadowrocket_tun_excluded_routes"]
    assert got.json()["item"]["settings"]["surge_tun_excluded_routes"]

    updated = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {
                "clash_fake_ip_filter": ["+.custom.heiyu.space"],
                "clash_always_real_ip": ["*.custom.heiyu.space"],
                "clash_dns_enable": False,
                "clash_dns_listen": "0.0.0.0:5353",
                "clash_dns_enhanced_mode": "redir-host",
                "clash_mixed_port": 17890,
                "clash_udp_default_enabled": False,
                "clash_dns_default_nameserver": ["1.1.1.1"],
                "clash_dns_nameserver": ["https://dns.google/dns-query"],
                "clash_dns_fallback": ["tls://9.9.9.9"],
                "clash_tun_enable": False,
                "clash_tun_stack": "system",
                "clash_tun_auto_route": False,
                "clash_tun_auto_detect_interface": False,
                "clash_tun_dns_hijack": ["any:5353"],
                "clash_tun_strict_route": False,
                "tun_excluded_routes": ["10.0.0.0/8"],
                "shadowrocket_always_real_ip": ["*.custom.shadowrocket.test"],
                "shadowrocket_tun_excluded_routes": ["172.16.0.0/12"],
                "surge_always_real_ip": ["*.custom.surge.test"],
                "surge_tun_excluded_routes": ["198.18.0.0/15"],
            },
        },
    )
    assert updated.status_code == 200
    item = updated.json()["item"]["settings"]
    assert item["clash_fake_ip_filter"] == ["+.custom.heiyu.space"]
    assert item["clash_dns_use_hosts"] is True
    assert item["clash_dns_enable"] is False
    assert item["clash_dns_listen"] == "0.0.0.0:5353"
    assert item["clash_mixed_port"] == 17890
    assert item["clash_udp_default_enabled"] is False
    assert item["clash_dns_nameserver"] == ["https://dns.google/dns-query"]
    assert item["clash_tun_enable"] is False
    assert item["clash_tun_dns_hijack"] == ["any:5353"]
    assert item["shadowrocket_tun_excluded_routes"] == ["172.16.0.0/12"]
    assert item["surge_tun_excluded_routes"] == ["198.18.0.0/15"]

    clash = client.get(_scenario_sub_path("tok1", "clash.yaml"))
    assert clash.status_code == 200
    assert "enable: false" in clash.text
    assert "listen: 0.0.0.0:5353" in clash.text
    assert "enhanced-mode: redir-host" in clash.text
    assert "use-hosts: true" in clash.text
    assert "mixed-port: 17890" in clash.text
    assert "- 1.1.1.1" in clash.text
    assert "- https://dns.google/dns-query" in clash.text
    assert "- tls://9.9.9.9" in clash.text
    assert "DOMAIN-SUFFIX,custom.heiyu.space,real-ip" not in clash.text
    assert "*.custom.heiyu.space" not in clash.text
    assert "stack: system" not in clash.text
    assert "- any:5353" not in clash.text
    clash_payload = yaml.safe_load(clash.text)
    assert "tun" not in clash_payload
    assert "render-warnings" not in clash_payload
    preview = client.get("/api/devices/tok1/preview-summary?target=clash")
    assert preview.status_code == 200
    warning_codes = [item["code"] for item in preview.json()["summary"]["warnings"]]
    assert "clash-always-real-ip-pending-validation" in warning_codes

    sr = client.get(_scenario_sub_path("tok1", "shadowrocket.conf"))
    assert sr.status_code == 200
    assert "always-real-ip = *.custom.shadowrocket.test" in sr.text
    assert "tun-excluded-routes = 172.16.0.0/12" in sr.text

    surge = client.get(_scenario_sub_path("tok1", "surge.conf"))
    assert surge.status_code == 200
    assert "always-real-ip = *.custom.surge.test" in surge.text
    assert "tun-excluded-routes = 198.18.0.0/15" in surge.text


def test_scenario_slug_conflicts_and_default_delete_are_rejected(client) -> None:
    first = client.post(
        "/api/scenarios",
        json={"slug": "work", "name": "Work", "description": "", "enabled": True},
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/api/scenarios",
        json={"slug": "work", "name": "Work 2", "description": "", "enabled": True},
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "scenario slug already exists"

    delete_default = client.delete("/api/scenarios/scenario-default")
    assert delete_default.status_code == 400
    assert delete_default.json()["detail"] == "cannot delete the default scenario"


def test_clash_provider_endpoint_applies_udp_defaults_and_explicit_override(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-udp",
            device_key="mac-udp",
            device_name="Mac UDP",
            token="tok-udp",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-udp",
            name="UDP Source",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-udp",
        [
            NodeRecord(
                name="ss-auto",
                host="ss.example.com",
                port=443,
                protocol="ss",
                quality_group="中等质量",
                password="p1",
                raw={"cipher": "aes-128-gcm", "password": "p1"},
            ),
            NodeRecord(
                name="anytls-explicit",
                host="anytls.example.com",
                port=443,
                protocol="anytls",
                quality_group="中等质量",
                password="p2",
                raw={"password": "p2", "udp": True},
            ),
        ],
    )

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    default_provider = client.get(_scenario_sub_path("tok-udp", "clash/providers/medium.yaml"))
    assert default_provider.status_code == 200
    default_payload = yaml.safe_load(default_provider.text)
    by_name = {item["name"]: item for item in default_payload["proxies"]}
    assert by_name["ss-auto"]["udp"] is True
    assert by_name["anytls-explicit"]["udp"] is True

    updated = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {
                "clash_fake_ip_filter": ["+.heiyu.space"],
                "clash_always_real_ip": ["*.heiyu.space"],
                "clash_dns_enable": True,
                "clash_dns_listen": "127.0.0.1:1053",
                "clash_dns_enhanced_mode": "fake-ip",
                "clash_mixed_port": 7890,
                "clash_udp_default_enabled": False,
                "clash_dns_default_nameserver": ["223.5.5.5"],
                "clash_dns_nameserver": ["https://doh.pub/dns-query"],
                "clash_dns_fallback": ["tls://1.1.1.1"],
                "clash_tun_enable": True,
                "clash_tun_stack": "mixed",
                "clash_tun_auto_route": True,
                "clash_tun_auto_detect_interface": True,
                "clash_tun_dns_hijack": ["any:53"],
                "clash_tun_strict_route": True,
                "tun_excluded_routes": ["6.6.6.6/32"],
                "shadowrocket_always_real_ip": ["*.heiyu.space"],
                "shadowrocket_tun_excluded_routes": ["6.6.6.6/32"],
                "surge_always_real_ip": ["*.heiyu.space"],
                "surge_tun_excluded_routes": ["6.6.6.6/32"],
            },
        },
    )
    assert updated.status_code == 200

    provider = client.get(_scenario_sub_path("tok-udp", "clash/providers/medium.yaml"))
    assert provider.status_code == 200
    payload = yaml.safe_load(provider.text)
    by_name = {item["name"]: item for item in payload["proxies"]}
    assert by_name["ss-auto"]["udp"] is False
    assert by_name["anytls-explicit"]["udp"] is True


def test_legacy_subscription_urls_continue_to_use_default_scenario(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-legacy-sub",
            device_key="legacy-sub",
            device_name="Legacy Device",
            token="tok-legacy-sub",
            enabled=True,
        )
    )

    legacy = client.get("/sub/device/tok-legacy-sub/surge.conf")
    assert legacy.status_code == 200
    assert "#!MANAGED-CONFIG" in legacy.text

    scenario = client.get("/sub/device/tok-legacy-sub/default/surge.conf")
    assert scenario.status_code == 200
    assert legacy.text == scenario.text


def test_devices_preview_summary_and_content_endpoints(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-disabled",
            device_key="default",
            device_name="Default",
            token="tok-disabled",
            enabled=False,
        )
    )
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d1",
            device_key="mac",
            device_name="Mac",
            token="tok1",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s1",
            name="源A",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="高质量-高倍率",
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
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1)]
    )
    services.repo.save_rule_cache("OpenAI", ["DOMAIN-SUFFIX,openai.com,PLACEHOLDER"])

    devices = client.get("/api/devices")
    assert devices.status_code == 200
    assert [item["device_name"] for item in devices.json()["items"]] == ["Mac", "Default"]

    summary = client.get("/api/devices/tok1/preview-summary?target=surge")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["ok"] is True
    assert payload["target"] == "surge"
    assert payload["revision"]
    assert payload["metadata"]["base_url"] == "http://testserver"
    assert payload["metadata"]["managed_url"].startswith("http://testserver/sub/device/")
    assert payload["metadata"]["managed_url"].endswith("/default/surge.conf")
    assert "content" not in payload
    assert "policy_ir" not in payload
    assert payload["summary"]["node_count"] == 1
    assert payload["summary"]["rule_line_count"] > 0
    assert payload["summary"]["general_profile_name"] == "默认场景"
    assert payload["summary"]["contracts"]
    assert payload["summary"]["catalog_bindings"]
    assert isinstance(payload["summary"]["warnings"], list)
    assert payload["summary"]["asset_counts"]["domain_sets"] >= 1
    assert payload["summary"]["asset_counts"]["rule_sets"] >= 0
    assert payload["summary"]["subscription_metadata"]["revision"] == payload["revision"]
    assert payload["summary"]["subscription_metadata"]["base_url"] == "http://testserver"

    content = client.get("/api/devices/tok1/preview-content?target=surge")
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("text/plain")
    assert int(content.headers["X-Preview-Lines"]) > 0
    assert int(content.headers["X-Preview-Chars"]) == len(content.text)
    assert content.headers["X-Preview-Revision"] == payload["revision"]
    assert content.headers["X-Preview-Base-Url"] == "http://testserver"
    assert content.headers["X-Preview-Managed-Url"].startswith("http://testserver/sub/device/")
    assert content.headers["X-Preview-Managed-Url"].endswith("/default/surge.conf")
    assert "FINAL,兜底代理,dns-failed" in content.text
    assert "/surge/domain-set/catalog-domains-hq_premium.txt" in content.text
    assert "# SubHub base-url: http://testserver" in content.text
    assert f"# SubHub artifact-revision: {payload['revision']}" in content.text


def test_preview_endpoints_reject_removed_profile_query(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-profile-raw",
            device_key="iphone",
            device_name="iPhone",
            token="tok-profile-raw",
            enabled=True,
        )
    )

    summary = client.get("/api/devices/tok-profile-raw/preview-summary?target=surge&profile=raw")
    assert summary.status_code == 400
    assert summary.json()["detail"] == "profile/flavor query parameters are no longer supported"

    render = client.get("/api/devices/tok-profile-raw/render-preview?target=surge&profile=raw")
    assert render.status_code == 400
    assert render.json()["detail"] == "profile/flavor query parameters are no longer supported"


def test_preview_summary_reuses_cached_artifact(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-summary",
            device_key="mac-summary",
            device_name="Mac Summary",
            token="tok-summary",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-summary",
            name="源Summary",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-summary",
        [
            NodeRecord(
                name="summary-node",
                host="summary.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="Summary", assigned_group="中等质量", rule_count=1)]
    )
    services.repo.save_rule_cache("Summary", ["DOMAIN-SUFFIX,summary.example,PLACEHOLDER"])

    import app.routes.management as management_routes

    original = management_routes.build_surge_profile_artifacts
    calls = {"count": 0}

    def _wrapped(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(management_routes, "build_surge_profile_artifacts", _wrapped)

    first = client.get("/api/devices/tok-summary/preview-summary?target=surge")
    second = client.get("/api/devices/tok-summary/preview-summary?target=surge")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["summary"] == second.json()["summary"]
    assert calls["count"] == 1


def test_clash_subscription_and_provider_cache_headers(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-cache",
            device_key="mac-cache",
            device_name="Mac Cache",
            token="tok-cache",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-cache",
            name="源Cache",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-cache",
        [
            NodeRecord(
                name="cache-node",
                host="cache.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="Cache", assigned_group="中等质量", rule_count=1)]
    )
    services.repo.save_rule_cache("Cache", ["DOMAIN-SUFFIX,cache.example,PLACEHOLDER"])

    import app.routes.subscription as subscription_routes

    original_clash = subscription_routes.build_clash_config
    original_provider = subscription_routes.build_clash_provider_config
    clash_calls = {"count": 0}
    provider_calls = {"count": 0}

    def _wrapped_clash(*args, **kwargs):
        clash_calls["count"] += 1
        return original_clash(*args, **kwargs)

    def _wrapped_provider(*args, **kwargs):
        provider_calls["count"] += 1
        return original_provider(*args, **kwargs)

    monkeypatch.setattr(subscription_routes, "build_clash_config", _wrapped_clash)
    monkeypatch.setattr(subscription_routes, "build_clash_provider_config", _wrapped_provider)

    first = client.get(_scenario_sub_path("tok-cache", "clash.yaml", flavor="lazycat"))
    second = client.get(_scenario_sub_path("tok-cache", "clash.yaml", flavor="lazycat"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.text == second.text
    assert first.headers["X-Artifact-Cache"] == "miss"
    assert second.headers["X-Artifact-Cache"] == "hit"
    assert first.headers["ETag"] == second.headers["ETag"]
    assert first.headers["X-Artifact-Revision"] == second.headers["X-Artifact-Revision"]
    assert clash_calls["count"] == 1

    provider_first = client.get(_scenario_sub_path("tok-cache", "clash/providers/medium.yaml"))
    provider_second = client.get(_scenario_sub_path("tok-cache", "clash/providers/medium.yaml"))
    assert provider_first.status_code == 200
    assert provider_second.status_code == 200
    assert provider_first.headers["X-Artifact-Cache"] == "miss"
    assert provider_second.headers["X-Artifact-Cache"] == "hit"
    assert provider_calls["count"] == 1


def test_clash_subscription_cache_revision_changes_after_profile_update(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-revision",
            device_key="mac-revision",
            device_name="Mac Revision",
            token="tok-revision",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-revision",
            name="源Revision",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-revision",
        [
            NodeRecord(
                name="revision-node",
                host="revision.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="Revision", assigned_group="中等质量", rule_count=1)]
    )
    services.repo.save_rule_cache("Revision", ["DOMAIN-SUFFIX,revision.example,PLACEHOLDER"])

    first = client.get(_scenario_sub_path("tok-revision", "clash.yaml", flavor="lazycat"))
    assert first.status_code == 200
    first_revision = first.headers["X-Artifact-Revision"]

    current_profile = services.repo.get_default_general_profile()
    assert current_profile is not None
    services.repo.save_general_profile(
        GeneralProfile(
            id=current_profile.id,
            name="LazyCat Default Updated",
            settings=current_profile.settings,
            is_system_default=True,
        )
    )

    second = client.get(_scenario_sub_path("tok-revision", "clash.yaml", flavor="lazycat"))
    assert second.status_code == 200
    assert second.headers["X-Artifact-Cache"] == "miss"
    assert second.headers["X-Artifact-Revision"] != first_revision


def test_clash_subscription_supports_gzip(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-gzip",
            device_key="mac-gzip",
            device_name="Mac Gzip",
            token="tok-gzip",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-gzip",
            name="源Gzip",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-gzip",
        [
            NodeRecord(
                name="gzip-node",
                host="gzip.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="Gzip", assigned_group="中等质量", rule_count=1)]
    )
    services.repo.save_rule_cache("Gzip", ["DOMAIN-SUFFIX,gzip.example,PLACEHOLDER"])

    response = client.get(
        _scenario_sub_path("tok-gzip", "clash.yaml", flavor="lazycat"),
        headers={"Accept-Encoding": "gzip"},
    )
    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"


def test_disabled_device_preview_endpoints_return_409(client) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-disabled",
            device_key="default",
            device_name="Default",
            token="tok-disabled",
            enabled=False,
        )
    )

    summary = client.get("/api/devices/tok-disabled/preview-summary?target=surge")
    assert summary.status_code == 409
    assert summary.json()["detail"] == "device subscription disabled"

    content = client.get("/api/devices/tok-disabled/preview-content?target=surge")
    assert content.status_code == 409
    assert content.json()["detail"] == "device subscription disabled"

    render = client.get("/api/devices/tok-disabled/render-preview?target=surge")
    assert render.status_code == 409
    assert render.json()["detail"] == "device subscription disabled"


def test_device_clash_bundle_export_returns_zip_with_audit(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-export",
            device_key="mac-export",
            device_name="Mac Export",
            token="tok-export",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-export",
            name="源Export",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-export",
        [
            NodeRecord(
                name="ss-export",
                host="export.example.com",
                port=443,
                protocol="ss",
                quality_group="中等质量",
                password="p1",
                raw={"cipher": "aes-128-gcm", "password": "p1"},
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="中等质量", rule_count=1)]
    )
    services.repo.save_rule_cache("OpenAI", ["DOMAIN-SUFFIX,openai.com,PLACEHOLDER"])

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    exported = client.get("/api/devices/tok-export/export/clash-bundle.zip")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/zip")
    assert "Mac-Export-default-clash-bundle.zip" in exported.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        names = sorted(archive.namelist())
        assert names == sorted(CLASH_BUNDLE_FILES)
        clash_payload = yaml.safe_load(archive.read("clash.yaml").decode("utf-8"))
        assert "render-warnings" not in clash_payload
        assert clash_payload["mixed-port"] == 7890
        assert clash_payload["proxy-providers"]["medium"]["proxy"] == "DIRECT"
        assert "health-check" not in clash_payload["proxy-providers"]["medium"]
        medium_provider = yaml.safe_load(archive.read("providers/medium.yaml").decode("utf-8"))
        assert medium_provider["proxies"][0]["udp"] is True
        audit_md = archive.read("AUDIT.md").decode("utf-8")
        assert "render-warnings stripped: yes" in audit_md
        assert "UDP explicit on supported proxies: yes" in audit_md
        assert "group health-check coverage present: yes" in audit_md
        assert "use-groups covered by group or provider health-check: yes" in audit_md
        assert "mixed-port present: yes" in audit_md


def test_surge_blocked_endpoints_return_structured_409_when_referenced_contract_is_empty(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-blocked",
            device_key="mac-blocked",
            device_name="Mac Blocked",
            token="tok-blocked",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-blocked",
            name="源Blocked",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="高质量-高倍率",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-blocked",
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

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    summary = client.get("/api/devices/tok-blocked/preview-summary?target=surge")
    assert summary.status_code == 409
    detail = summary.json()["detail"]
    assert detail["code"] == "surge-build-blocked"
    assert any(item["code"] == "surge-referenced-empty-contract" for item in detail["blockers"])
    assert any(item["code"] == "empty-pool" for item in detail["warnings"])
    assert detail["referenced_contracts"][0]["id"] == "hq_standard"
    assert detail["referenced_contracts"][0]["rule_entry_count"] == 2

    content = client.get("/api/devices/tok-blocked/preview-content?target=surge")
    assert content.status_code == 409
    assert content.json()["detail"]["code"] == "surge-build-blocked"

    render = client.get("/api/devices/tok-blocked/render-preview?target=surge")
    assert render.status_code == 409
    assert render.json()["detail"]["code"] == "surge-build-blocked"

    surge_sub = client.get(_scenario_sub_path("tok-blocked", "surge.conf"))
    assert surge_sub.status_code == 409
    assert surge_sub.json()["detail"]["code"] == "surge-build-blocked"

    domain_asset = client.get(_scenario_sub_path("tok-blocked", "surge/domain-set/catalog-domains-hq_standard.txt"))
    assert domain_asset.status_code == 409
    assert domain_asset.json()["detail"]["code"] == "surge-build-blocked"

    rule_asset = client.get(_scenario_sub_path("tok-blocked", "surge/rule-set/catalog-rules-hq_standard.list"))
    assert rule_asset.status_code == 409
    assert rule_asset.json()["detail"]["code"] == "surge-build-blocked"

    clash_summary = client.get("/api/devices/tok-blocked/preview-summary?target=clash")
    assert clash_summary.status_code == 409
    assert clash_summary.json()["detail"]["code"] == "clash-build-blocked"

    clash_sub = client.get(_scenario_sub_path("tok-blocked", "clash.yaml"))
    assert clash_sub.status_code == 409
    assert clash_sub.json()["detail"]["code"] == "clash-build-blocked"

    clash_bundle = client.get("/api/devices/tok-blocked/export/clash-bundle.zip")
    assert clash_bundle.status_code == 409
    assert clash_bundle.json()["detail"]["code"] == "clash-build-blocked"


def test_surge_rule_asset_endpoints_return_expected_formats(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-assets",
            device_key="mac-assets",
            device_name="Mac Assets",
            token="tok-assets",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-assets",
            name="源Assets",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="低质量大流量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-assets",
        [
            NodeRecord(
                name="bulk-1",
                host="bulk.example.com",
                port=443,
                protocol="http",
                quality_group="低质量大流量",
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="Telemetry", assigned_group="低质量大流量", rule_count=2)]
    )
    services.repo.save_rule_cache(
        "Telemetry",
        [
            "DOMAIN-SUFFIX,cloudflare.net,PLACEHOLDER",
            "DOMAIN-KEYWORD,microsoft,PLACEHOLDER",
        ],
    )

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    domain_asset = client.get(_scenario_sub_path("tok-assets", "surge/domain-set/catalog-domains-bulk.txt"))
    assert domain_asset.status_code == 200
    assert domain_asset.headers["content-type"].startswith("text/plain")
    assert domain_asset.headers["X-Subscription-Base-Url"] == "http://testserver"
    assert domain_asset.headers["X-Artifact-Revision"]
    assert domain_asset.text == ".cloudflare.net\n"

    rule_asset = client.get(_scenario_sub_path("tok-assets", "surge/rule-set/catalog-rules-bulk.list"))
    assert rule_asset.status_code == 200
    assert rule_asset.headers["content-type"].startswith("text/plain")
    assert rule_asset.headers["X-Subscription-Base-Url"] == "http://testserver"
    assert rule_asset.headers["X-Artifact-Revision"] == domain_asset.headers["X-Artifact-Revision"]
    assert rule_asset.text == "DOMAIN-KEYWORD,microsoft\n"


def test_surge_subscription_metadata_and_assets_stay_in_sync(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-surge-meta",
            device_key="mac-surge-meta",
            device_name="Mac Surge Meta",
            token="tok-surge-meta",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-surge-meta",
            name="源SurgeMeta",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="高质量-高倍率",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-surge-meta",
        [
            NodeRecord(
                name="premium-meta-1",
                host="premium-meta.example.com",
                port=443,
                protocol="http",
                quality_group="高质量-高倍率",
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=2)]
    )
    services.repo.save_rule_cache(
        "OpenAI",
        [
            "DOMAIN-SUFFIX,chatgpt.com,PLACEHOLDER",
            "DOMAIN-SUFFIX,openai.com,PLACEHOLDER",
        ],
    )

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    preview = client.get("/api/devices/tok-surge-meta/render-preview?target=surge")
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["metadata"]["base_url"] == "http://testserver"
    assert preview_payload["metadata"]["managed_url"].startswith("http://testserver/sub/device/")
    assert preview_payload["metadata"]["managed_url"].endswith("/default/surge.conf")
    assert preview_payload["metadata"]["domain_set_count"] >= 1
    assert "# SubHub base-url: http://testserver" in preview_payload["content"]
    assert f"# SubHub artifact-revision: {preview_payload['revision']}" in preview_payload["content"]

    surge_sub = client.get(_scenario_sub_path("tok-surge-meta", "surge.conf"))
    assert surge_sub.status_code == 200
    assert surge_sub.headers["X-Subscription-Base-Url"] == "http://testserver"
    assert surge_sub.headers["X-Surge-Managed-Url"].startswith("http://testserver/sub/device/")
    assert surge_sub.headers["X-Surge-Managed-Url"].endswith("/default/surge.conf")
    assert surge_sub.headers["X-Artifact-Revision"] == preview_payload["revision"]
    assert "# SubHub base-url: http://testserver" in surge_sub.text
    assert f"# SubHub artifact-revision: {preview_payload['revision']}" in surge_sub.text
    assert "/surge/domain-set/catalog-domains-hq_premium.txt" in surge_sub.text
    signed_domain_set_line = next(
        line for line in surge_sub.text.splitlines() if "/surge/domain-set/catalog-domains-hq_premium.txt" in line
    )
    signed_domain_set_url = signed_domain_set_line.split(",", 2)[1]
    assert "rev=" in signed_domain_set_url
    assert "exp=" in signed_domain_set_url
    assert "sig=" in signed_domain_set_url

    domain_asset = client.get(_scenario_sub_path("tok-surge-meta", "surge/domain-set/catalog-domains-hq_premium.txt"))
    assert domain_asset.status_code == 200
    assert domain_asset.headers["X-Artifact-Revision"] == preview_payload["revision"]
    assert domain_asset.headers["X-Subscription-Base-Url"] == "http://testserver"
    assert ".chatgpt.com\n" in domain_asset.text
    signed_domain_asset = client.get(signed_domain_set_url.replace("http://testserver", ""))
    assert signed_domain_asset.status_code == 200
    invalid_signed_domain_asset = client.get(signed_domain_set_url.replace("sig=", "sig=broken", 1).replace("http://testserver", ""))
    assert invalid_signed_domain_asset.status_code == 200
    assert ".chatgpt.com\n" in invalid_signed_domain_asset.text


def test_surge_signed_asset_url_survives_revision_change(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-surge-stale-sig",
            device_key="mac-surge-stale-sig",
            device_name="Mac Surge Stale Sig",
            token="tok-surge-stale-sig",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-surge-stale-sig",
            name="源SurgeStaleSig",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="高质量-高倍率",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-surge-stale-sig",
        [
            NodeRecord(
                name="premium-stale-sig-1",
                host="premium-stale-sig.example.com",
                port=443,
                protocol="http",
                quality_group="高质量-高倍率",
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="StableSig", assigned_group="高质量-高倍率", rule_count=1)]
    )
    services.repo.save_rule_cache(
        "StableSig",
        [
            "DOMAIN-SUFFIX,stale-sig.example,PLACEHOLDER",
        ],
    )

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    initial_sub = client.get(_scenario_sub_path("tok-surge-stale-sig", "surge.conf"))
    assert initial_sub.status_code == 200
    initial_revision = initial_sub.headers["X-Artifact-Revision"]
    initial_signed_line = next(
        line for line in initial_sub.text.splitlines() if "/surge/domain-set/catalog-domains-hq_premium.txt" in line
    )
    initial_signed_url = initial_signed_line.split(",", 2)[1].replace("http://testserver", "")

    initial_signed_asset = client.get(initial_signed_url)
    assert initial_signed_asset.status_code == 200
    assert ".stale-sig.example\n" in initial_signed_asset.text

    services.repo.save_rule_categories(
        [RuleCategory(name="StableSig", assigned_group="高质量-高倍率", rule_count=2)]
    )
    services.repo.save_rule_cache(
        "StableSig",
        [
            "DOMAIN-SUFFIX,stale-sig.example,PLACEHOLDER",
            "DOMAIN-SUFFIX,stale-sig-2.example,PLACEHOLDER",
        ],
    )

    updated_sub = client.get(_scenario_sub_path("tok-surge-stale-sig", "surge.conf"))
    assert updated_sub.status_code == 200
    updated_revision = updated_sub.headers["X-Artifact-Revision"]
    assert updated_revision != initial_revision

    stale_signed_asset = client.get(initial_signed_url)
    assert stale_signed_asset.status_code == 200
    assert ".stale-sig.example\n" in stale_signed_asset.text
    assert ".stale-sig-2.example\n" in stale_signed_asset.text


def test_surge_subscription_and_assets_reuse_cached_artifacts(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-surge-cache",
            device_key="mac-surge-cache",
            device_name="Mac Surge Cache",
            token="tok-surge-cache",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-surge-cache",
            name="源SurgeCache",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="高质量-高倍率",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-surge-cache",
        [
            NodeRecord(
                name="premium-cache-1",
                host="premium-cache.example.com",
                port=443,
                protocol="http",
                quality_group="高质量-高倍率",
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="CacheSurge", assigned_group="高质量-高倍率", rule_count=2)]
    )
    services.repo.save_rule_cache(
        "CacheSurge",
        [
            "DOMAIN-SUFFIX,cache-surge.example,PLACEHOLDER",
            "DOMAIN-KEYWORD,cache-surge,PLACEHOLDER",
        ],
    )

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    import app.routes.subscription as subscription_routes

    original = subscription_routes.build_surge_profile_artifacts
    calls = {"count": 0}

    def _wrapped(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(subscription_routes, "build_surge_profile_artifacts", _wrapped)

    surge_sub = client.get(_scenario_sub_path("tok-surge-cache", "surge.conf"))
    assert surge_sub.status_code == 200
    assert "/surge/domain-set/catalog-domains-hq_premium.txt" in surge_sub.text

    domain_asset = client.get(_scenario_sub_path("tok-surge-cache", "surge/domain-set/catalog-domains-hq_premium.txt"))
    assert domain_asset.status_code == 200
    assert ".cache-surge.example\n" in domain_asset.text

    rule_asset = client.get(_scenario_sub_path("tok-surge-cache", "surge/rule-set/catalog-rules-hq_premium.list"))
    assert rule_asset.status_code == 200
    assert "DOMAIN-KEYWORD,cache-surge\n" in rule_asset.text

    assert calls["count"] == 1


def test_standard_source_pull_and_subscription_export_supports_anytls_hy2_tuic(
    client,
    monkeypatch,
) -> None:
    services = client.app.state.services
    probe_client = _ProtocolProbeClient(
        {
            "ClashforWindows/0.20.39": (
                "proxies:\n"
                "  - name: bad-unknown\n"
                "    server: bad.example.com\n"
                "    port: 443\n"
                "    type: unknown-proto\n"
            ),
            "clash-verge/2.0": (
                "proxies:\n"
                "  - name: anytls-1\n"
                "    server: anytls.example.com\n"
                "    port: 443\n"
                "    type: anytls\n"
                "    password: p1\n"
                "    sni: anytls.example.com\n"
                "  - name: hy2-1\n"
                "    server: hy2.example.com\n"
                "    port: 8443\n"
                "    type: hy2\n"
                "    password: p2\n"
                "    sni: hy2.example.com\n"
                "    obfs: salamander\n"
                "  - name: tuic-1\n"
                "    server: tuic.example.com\n"
                "    port: 9443\n"
                "    type: tuic\n"
                "    uuid: uuid-1\n"
                "    password: p3\n"
                "    congestion-controller: bbr\n"
                "    udp-relay-mode: native\n"
            ),
            "mihomo/1.19.0": "proxies: []\n",
        }
    )
    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: probe_client,
    )

    created = client.post(
        "/api/sources/standard",
        json={
            "name": "山海样式源",
            "clash_url": "https://example.com/clash.yaml?token=masked",
            "shadowrocket_url": "https://example.com/sr.conf?token=masked",
            "surge_url": "https://example.com/surge.conf?token=masked",
            "quality_group": "中等质量",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    pull = created.json()["pull_result"]
    assert pull["ok"] is True
    assert int(pull["node_count"]) >= 3
    assert int(pull["cached_node_count"]) >= 3
    assert pull["method"] == "clash"
    assert int(created.json()["item"]["cached_node_count"]) >= 3
    attempts = pull["attempts"]
    assert any(item.get("request_variant") == "ua:clash-verge/2.0" for item in attempts)
    assert any(
        isinstance(item.get("parsed_protocol_counts"), dict)
        and item["parsed_protocol_counts"].get("anytls") == 1
        and item["parsed_protocol_counts"].get("hysteria2") == 1
        and item["parsed_protocol_counts"].get("tuic") == 1
        for item in attempts
    )
    assert any(item.get("skip_reasons") for item in attempts)

    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-new-proto",
            device_key="mac-proto",
            device_name="Mac Proto",
            token="tok-new-proto",
            enabled=True,
        )
    )

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    clash = client.get(_scenario_sub_path("tok-new-proto", "clash.yaml"))
    assert clash.status_code == 200
    assert "proxy-providers:" in clash.text

    clash_provider = client.get(_scenario_sub_path("tok-new-proto", "clash/providers/medium.yaml"))
    assert clash_provider.status_code == 200
    assert "type: anytls" in clash_provider.text
    assert "type: hysteria2" in clash_provider.text
    assert "type: tuic" in clash_provider.text

    sr = client.get(_scenario_sub_path("tok-new-proto", "shadowrocket.conf"))
    assert sr.status_code == 200
    assert "[Proxy]" in sr.text

    sr_nodes = client.get(_scenario_sub_path("tok-new-proto", "shadowrocket-nodes.txt"))
    assert sr_nodes.status_code == 200
    decoded_sr_nodes = base64.b64decode(sr_nodes.text.encode("ascii")).decode("utf-8")
    assert "anytls://p1@anytls.example.com:443" in decoded_sr_nodes
    assert "hysteria2://p2@hy2.example.com:8443" in decoded_sr_nodes
    assert "tuic://uuid-1:p3@tuic.example.com:9443" in decoded_sr_nodes

    surge = client.get(_scenario_sub_path("tok-new-proto", "surge.conf"))
    assert surge.status_code == 200
    assert "anytls, anytls.example.com, 443" in surge.text
    assert "hysteria2, hy2.example.com, 8443" in surge.text
    assert "tuic-v5, tuic.example.com, 9443" in surge.text


def test_mixed_manual_source_reports_rejected_entries_on_api_readback(client) -> None:
    response = client.post("/api/sources/standard", json={
        "name": "Mixed import", "ingest_kind": "manual_nodes", "enabled": True,
        "target_contract_id": "medium",
        "manual_nodes_text": "trojan://secret-good@good.example:443#Good\ntrojan://secret-bad@bad.example:bad#Bad",
    })
    assert response.status_code == 200
    created = response.json()
    assert created["pull_result"]["ok"] is True
    assert created["pull_result"]["node_count"] == 1
    source_id = created["item"]["id"]
    listed = client.get("/api/sources/standard").json()["items"]
    item = next(item for item in listed if item["id"] == source_id)
    assert item["pull_warning_count"] > 0
    assert item["pull_warnings"][0]["code"] == "source-parse-rejected"
    assert "invalid uri field" in item["pull_warnings"][0]["message"]
    assert "secret-bad" not in str(item["pull_warnings"])


def test_list_standard_sources_reports_cached_node_count(client) -> None:
    services = client.app.state.services
    source_id = "s-cache"
    services.repo.save_standard_source(
        StandardSource(
            id=source_id,
            name="缓存可见性",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        source_id,
        [
            NodeRecord(
                name="[缓存可见性] n1",
                host="n1.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
                source_id=source_id,
                source_type="standard",
            ),
            NodeRecord(
                name="[缓存可见性] n2",
                host="n2.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
                source_id=source_id,
                source_type="standard",
            ),
        ],
    )

    listed = client.get("/api/sources/standard")
    assert listed.status_code == 200
    item = next(entry for entry in listed.json()["items"] if entry["id"] == source_id)
    assert int(item["cached_node_count"]) == 2


def test_custom_rules_accept_direct_target_group(client) -> None:
    created = client.post(
        "/api/rules/custom",
        json={
            "rule_type": "DOMAIN-SUFFIX",
            "value": "heiyu.space",
            "target_group": "DIRECT",
        },
    )
    assert created.status_code == 200
    payload = created.json()["item"]
    assert payload["target_group"] == "DIRECT"


def test_custom_rules_accept_reject_target_group(client) -> None:
    created = client.post(
        "/api/rules/custom",
        json={
            "rule_type": "DOMAIN-SUFFIX",
            "value": "ads.example.com",
            "target_group": "REJECT",
        },
    )
    assert created.status_code == 200
    payload = created.json()["item"]
    assert payload["target_group"] == "REJECT"
    assert payload["target_contract_id"] == "action-reject"


def test_gorelay_api_accounts_and_subscription_disable(client) -> None:
    created = client.post(
        "/api/gorelay/accounts",
        json={
            "name": "GoRelay-A",
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "gorelay_password": "p",
            "selectors_json": "{}",
            "mcp_url": "https://mcp.example.com",
            "auth_header": "Bearer x",
            "login_tool": "auth_login",
            "nodes_tool": "list_nodes",
            "login_args_json": "{}",
            "nodes_args_json": "{}",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    account_id = created.json()["item"]["id"]

    listed = client.get("/api/gorelay/accounts")
    assert listed.status_code == 200
    account = next(item for item in listed.json()["items"] if item["id"] == account_id)
    assert account["mcp_url"] == "https://mcp.example.com"
    assert account["login_tool"] == "auth_login"
    assert account["nodes_tool"] == "list_nodes"
    assert account["has_auth_header"] is True

    client.app.state.services.repo.upsert_gorelay_device_subscription(
        GoRelayDeviceSubscription(
            id="gs1",
            account_id=account_id,
            device_key="mac",
            device_name="Mac",
            token="tok-gorelay",
            enabled=True,
        )
    )

    subs = client.get(f"/api/gorelay/subscriptions?account_id={account_id}")
    assert subs.status_code == 200
    assert any(item["id"] == "gs1" for item in subs.json()["items"])

    disabled = client.post("/api/gorelay/subscriptions/gs1/disable")
    assert disabled.status_code == 200

    pending = client.get(f"/api/gorelay/accounts/{account_id}/domain-bindings/pending")
    assert pending.status_code == 200
    assert "pending" in pending.json()
    assert "bindings" in pending.json()

    entries = client.get(f"/api/gorelay/accounts/{account_id}/entries")
    assert entries.status_code == 200
    assert entries.json()["ok"] is True

    status = client.get(f"/api/gorelay/accounts/{account_id}/status")
    assert status.status_code == 200
    assert status.json()["ok"] is True
    assert "snapshot_id" in status.json()
    assert "created_at" in status.json()

    forbidden = client.get(_scenario_sub_path("tok-gorelay", "clash.yaml"))
    assert forbidden.status_code == 403


def test_gorelay_account_device_links_stay_on_default_subscription_path(client) -> None:
    services = client.app.state.services
    services.settings.app_base_url = "http://192.168.0.108:8080"
    default_scenario = services.repo.get_scenario("scenario-default")
    assert default_scenario is not None
    services.repo.save_scenario(
        ScenarioProfile(
            id=default_scenario.id,
            slug=default_scenario.slug,
            name=default_scenario.name,
            description=default_scenario.description,
            enabled=default_scenario.enabled,
            sort_order=default_scenario.sort_order,
            settings={
                "surge_host_records": {
                    "subhub.default.heiyu.space": "192.168.0.108",
                }
            },
            editor_state=default_scenario.editor_state,
        )
    )
    services.repo.save_scenario(
        ScenarioProfile(
            id="scenario-work",
            slug="work",
            name="Work",
            sort_order=-1,
            settings={
                "surge_host_records": {
                    "subhub.work.heiyu.space": "192.168.0.108",
                }
            },
        ),
    )
    created = client.post(
        "/api/gorelay/accounts",
        json={
            "name": "GoRelay-Default",
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "gorelay_password": "p",
            "selectors_json": "{}",
            "mcp_url": "https://mcp.example.com",
            "auth_header": "Bearer x",
            "login_tool": "auth_login",
            "nodes_tool": "list_nodes",
            "login_args_json": "{}",
            "nodes_args_json": "{}",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    account_id = created.json()["item"]["id"]
    services.repo.upsert_gorelay_device_subscription(
        GoRelayDeviceSubscription(
            id="gs-default",
            account_id=account_id,
            device_key="mac-mini",
            device_name="Mac Mini",
            token="tok-default",
            public_id="pub-default",
            enabled=True,
        )
    )

    listed = client.get(f"/api/gorelay/accounts/{account_id}/devices")
    assert listed.status_code == 200
    device = next(item for item in listed.json()["items"] if item["device_key"] == "mac-mini")

    assert "/sub/device/pub-default/clash.yaml" in device["links"]["clash_url"]
    assert "/sub/device/pub-default/work/clash.yaml" not in device["links"]["clash_url"]
    assert device["links"]["surge_url"].startswith("https://subhub.default.heiyu.space/")
    assert "subhub.work.heiyu.space" not in device["links"]["surge_url"]

    subscriptions = client.get(f"/api/gorelay/subscriptions?account_id={account_id}")
    assert subscriptions.status_code == 200
    item = next(entry for entry in subscriptions.json()["items"] if entry["id"] == "gs-default")
    assert item["links"]["surge_url"].startswith("https://subhub.default.heiyu.space/")
    assert "subhub.work.heiyu.space" not in item["links"]["surge_url"]
    assert "/sub/device/pub-default/work/surge.conf" not in item["links"]["surge_url"]


def test_gorelay_update_binding_triggers_rebuild(client, monkeypatch) -> None:
    created = client.post(
        "/api/gorelay/accounts",
        json={
            "name": "GoRelay-B",
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "gorelay_password": "p",
            "selectors_json": "{}",
            "enabled": True,
        },
    )
    account_id = created.json()["item"]["id"]
    client.app.state.services.repo.save_gorelay_domain_bindings(
        [
            GoRelayDomainBinding(
                id="b1",
                account_id=account_id,
                entry_name="入口A",
                isp="ct",
                ip_version="ipv4",
                host_value="1.1.1.1",
                source="manual_import",
                status="approved",
                updated_at="2026-01-01T00:00:00Z",
            )
        ]
    )

    def _fake_rebuild(_: str):
        return {"ok": True, "snapshot_id": "s1"}

    monkeypatch.setattr(
        client.app.state.services.gorelay_service,
        "rebuild_account_from_latest_rules",
        _fake_rebuild,
    )

    resp = client.put(
        f"/api/gorelay/accounts/{account_id}/domain-bindings/b1",
        json={"host_value": "2.2.2.2", "status": "approved"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["item"]["host_value"] == "2.2.2.2"
    assert body["rebuild"]["snapshot_id"] == "s1"


def test_gorelay_pending_and_entries_split_other_usage_to_specific_bindings(client) -> None:
    services = client.app.state.services
    account = GoRelayAccount(
        id="acc-split",
        name="GoRelay-Split",
        login_url="https://relay.example.com",
        rules_url="https://relay.example.com",
        gorelay_username="u",
        gorelay_password="p",
        selectors_json="{}",
        enabled=True,
        updated_at="2026-01-01T00:00:00Z",
    )
    services.gorelay_service.save_account(account)
    services.repo.save_gorelay_domain_bindings(
        [
            GoRelayDomainBinding(
                id="bind-ct",
                account_id=account.id,
                entry_name="「Lv1」广东隧道「电信联通」",
                isp="ct",
                ip_version="ipv4",
                host_value="119.147.22.121",
                source="manual_import",
                status="approved",
                updated_at="2026-01-01T00:00:00Z",
            )
        ]
    )
    services.repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id=account.id,
                snapshot_id="snap-split",
                created_at="2026-01-01T00:00:00Z",
                node_count=0,
                device_count=0,
                status="success",
            ),
            collected_rules=[
                CollectedRule(
                    account_id=account.id,
                    rule_id="r-split",
                    device_name="Mac",
                    line_name="Mac",
                    entry_name="「Lv1」广东隧道「电信联通」",
                    isp="other",
                    ip_version="ipv4",
                    port=38658,
                    host="",
                    status="pending_domain",
                    raw={"line": "联系客服申请，已申请可忽略。"},
                )
            ],
            device_nodes={},
            device_names={"mac": "Mac"},
            pending_bindings=[],
            source_status={},
        )
    )
    services.repo.save_gorelay_active_snapshot_id(account.id, "snap-split")

    pending = client.get(f"/api/gorelay/accounts/{account.id}/domain-bindings/pending")
    assert pending.status_code == 200
    bindings = pending.json()["bindings"]
    assert len(bindings) == 1
    assert bindings[0]["isp"] == "ct"
    assert bindings[0]["ports"] == [38658]
    assert bindings[0]["devices"][0]["device_name"] == "Mac"

    entries = client.get(f"/api/gorelay/accounts/{account.id}/entries")
    assert entries.status_code == 200
    items = entries.json()["items"]
    assert len(items) == 1
    assert items[0]["isp"] == "ct"
    assert items[0]["host_value"] == "119.147.22.121"
    assert items[0]["resolved"] is True
    assert items[0]["devices"][0]["device_name"] == "Mac"


def test_delete_gorelay_source_deletes_fallback_account(client) -> None:
    created = client.post(
        "/api/gorelay/accounts",
        json={
            "name": "Compat-Delete",
            "login_url": "https://relay.example.com",
            "gorelay_username": "u",
            "gorelay_password": "p",
            "selectors_json": "{}",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    account_id = created.json()["item"]["id"]

    sources = client.get("/api/sources/gorelay")
    assert sources.status_code == 200
    assert any(item["id"] == account_id for item in sources.json()["items"])

    deleted = client.delete(f"/api/sources/gorelay/{account_id}")
    assert deleted.status_code == 200

    sources_after = client.get("/api/sources/gorelay")
    assert sources_after.status_code == 200
    assert not any(item["id"] == account_id for item in sources_after.json()["items"])

    accounts_after = client.get("/api/gorelay/accounts")
    assert accounts_after.status_code == 200
    assert not any(item["id"] == account_id for item in accounts_after.json()["items"])


def test_category_custom_rules_api_and_global_view_separation(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=10),
            RuleCategory(name="YouTube", assigned_group="", rule_count=20),
        ]
    )
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="medium",
            sort_order=0,
            source="manual",
        )
    )
    services.repo.save_custom_rule(
        CustomRule(
            id="global-1",
            rule_type="DOMAIN-SUFFIX",
            value="global.example.com",
            target_group="中等质量",
            category_name="",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    created = client.post(
        "/api/rules/categories/OpenAI/custom",
        json={"rule_type": "DOMAIN-SUFFIX", "value": "api.openai.com"},
    )
    assert created.status_code == 200
    item = created.json()["item"]
    assert item["category_name"] == "OpenAI"
    assert item["effective_contract_id"] == "medium"
    assert item["effective_contract_display_name"] == "中等质量"
    assert item["effective_contract_source"] == "stored_contract"
    assert item["active"] is True

    pending = client.post(
        "/api/rules/categories/YouTube/custom",
        json={"rule_type": "DOMAIN-SUFFIX", "value": "m.youtube.com"},
    )
    assert pending.status_code == 409
    assert pending.json()["detail"] == "category route contract required before adding category rules"

    category_rules = client.get("/api/rules/categories/OpenAI/custom")
    assert category_rules.status_code == 200
    assert len(category_rules.json()["items"]) == 1
    assert category_rules.json()["items"][0]["value"] == "api.openai.com"
    assert category_rules.json()["items"][0]["effective_contract_id"] == "medium"

    pending_rules = client.get("/api/rules/categories/YouTube/custom")
    assert pending_rules.status_code == 200
    assert pending_rules.json()["category"]["active"] is False
    assert pending_rules.json()["category"]["effective_contract_id"] == ""

    global_rules = client.get("/api/rules/custom")
    assert global_rules.status_code == 200
    values = [item["value"] for item in global_rules.json()["items"]]
    assert values == ["global.example.com"]

    categories = client.get("/api/rules/categories")
    assert categories.status_code == 200
    by_name = {item["name"]: item for item in categories.json()["items"]}
    assert by_name["OpenAI"]["custom_rule_count"] == 1
    assert by_name["YouTube"]["custom_rule_count"] == 0

    unknown = client.post(
        "/api/rules/categories/Unknown/custom",
        json={"rule_type": "DOMAIN-SUFFIX", "value": "x.example.com"},
    )
    assert unknown.status_code == 404


def test_category_rule_preview_returns_paginated_raw_catalog_rules(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=5)]
    )
    services.repo.save_rule_cache(
        "OpenAI",
        [
            "DOMAIN,one.example.com,PLACEHOLDER",
            "DOMAIN,two.example.com,PLACEHOLDER",
            "DOMAIN,three.example.com,PLACEHOLDER",
            "DOMAIN,four.example.com,PLACEHOLDER",
            "DOMAIN,five.example.com,PLACEHOLDER",
        ],
    )

    preview = client.get("/api/rules/categories/OpenAI/preview?offset=1&limit=2")
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["ok"] is True
    assert payload["category"]["name"] == "OpenAI"
    assert payload["total"] == 5
    assert payload["offset"] == 1
    assert payload["limit"] == 2
    assert payload["has_more"] is True
    assert payload["items"] == [
        "DOMAIN,two.example.com,PLACEHOLDER",
        "DOMAIN,three.example.com,PLACEHOLDER",
    ]


def test_category_rule_preview_clamps_limit_and_offset_past_end(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1200)]
    )
    services.repo.save_rule_cache(
        "OpenAI",
        [f"DOMAIN,item-{index}.example.com,PLACEHOLDER" for index in range(1200)],
    )

    capped = client.get("/api/rules/categories/OpenAI/preview?offset=100&limit=5000")
    assert capped.status_code == 200
    body = capped.json()
    assert body["limit"] == 1000
    assert len(body["items"]) == 1000
    assert body["has_more"] is True

    out_of_range = client.get("/api/rules/categories/OpenAI/preview?offset=1500&limit=200")
    assert out_of_range.status_code == 200
    out = out_of_range.json()
    assert out["items"] == []
    assert out["has_more"] is False


def test_category_rule_preview_returns_empty_for_manual_category(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="SubHub", assigned_group="DIRECT", category_type="manual")]
    )

    preview = client.get("/api/rules/categories/SubHub/preview")
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["category"]["name"] == "SubHub"
    assert payload["total"] == 0
    assert payload["items"] == []
    assert payload["has_more"] is False


def test_category_rule_preview_returns_404_for_unknown_category(client) -> None:
    resp = client.get("/api/rules/categories/Unknown/preview")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "category not found"


def test_category_rule_preview_fetches_and_backfills_cache_when_missing(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=2, rule_source="yaml")]
    )

    async def _fake_fetch_category_rules(category_name, entry=None, *, client=None):
        assert category_name == "OpenAI"
        return 2, "yaml", [
            "DOMAIN,api.openai.com,PLACEHOLDER",
            "DOMAIN,chat.openai.com,PLACEHOLDER",
        ]

    monkeypatch.setattr(services.rule_catalog, "_fetch_category_rules", _fake_fetch_category_rules)

    preview = client.get("/api/rules/categories/OpenAI/preview")
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["total"] == 2
    assert payload["items"] == [
        "DOMAIN,api.openai.com,PLACEHOLDER",
        "DOMAIN,chat.openai.com,PLACEHOLDER",
    ]
    assert services.repo.load_rule_cache("OpenAI") == [
        "DOMAIN,api.openai.com,PLACEHOLDER",
        "DOMAIN,chat.openai.com,PLACEHOLDER",
    ]


def test_rule_metadata_lists_supported_category_rule_types(client) -> None:
    resp = client.get("/api/rules/metadata")
    assert resp.status_code == 200
    assert resp.json()["category_rule_types"] == [
        "DOMAIN",
        "DOMAIN-SUFFIX",
        "DOMAIN-KEYWORD",
        "IP-CIDR",
        "IP-CIDR6",
        "SRC-IP-CIDR",
        "GEOIP",
        "GEOSITE",
        "DST-PORT",
        "SRC-PORT",
        "PROCESS-NAME",
        "PROCESS-PATH",
        "USER-AGENT",
    ]


def test_bulk_create_custom_rules_for_category_dedupes_existing_and_payload_duplicates(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=10)]
    )
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="medium",
            sort_order=0,
            source="manual",
        )
    )
    services.repo.save_custom_rule(
        CustomRule(
            id="existing-1",
            rule_type="PROCESS-NAME",
            value="Claude",
            target_group="",
            category_name="OpenAI",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    created = client.post(
        "/api/rules/categories/OpenAI/custom/bulk",
        json={
            "items": [
                {"rule_type": "PROCESS-NAME", "value": "Claude"},
                {"rule_type": "PROCESS-NAME", "value": "claude"},
                {"rule_type": "PROCESS-NAME", "value": "claude"},
                {"rule_type": "DOMAIN-SUFFIX", "value": "api.openai.com"},
            ],
            "dedupe": True,
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["created_count"] == 2
    assert payload["skipped_count"] == 2
    assert [item["value"] for item in payload["items"]] == ["claude", "api.openai.com"]
    assert all(item["effective_contract_id"] == "medium" for item in payload["items"])

    category_rules = client.get("/api/rules/categories/OpenAI/custom")
    assert category_rules.status_code == 200
    values = [item["value"] for item in category_rules.json()["items"]]
    assert values == ["api.openai.com", "claude", "Claude"]


def test_bulk_create_custom_rules_for_category_rejects_invalid_items(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=10)]
    )
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="medium",
            sort_order=0,
            source="manual",
        )
    )

    missing_value = client.post(
        "/api/rules/categories/OpenAI/custom/bulk",
        json={"items": [{"rule_type": "DOMAIN-SUFFIX", "value": ""}]},
    )
    assert missing_value.status_code == 400
    assert missing_value.json()["detail"] == "rule_type and value are required"

    invalid_type = client.post(
        "/api/rules/categories/OpenAI/custom/bulk",
        json={"items": [{"rule_type": "MATCH", "value": "final"}]},
    )
    assert invalid_type.status_code == 400
    assert "rule_type must be one of:" in invalid_type.json()["detail"]


def test_manual_category_create_and_assign_direct_scope(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=10)]
    )

    created = client.post(
        "/api/rules/categories/manual",
        json={"name": "SubHub", "assigned_group": "DIRECT"},
    )
    assert created.status_code == 200
    assert created.json()["item"]["name"] == "SubHub"
    assert created.json()["item"]["category_type"] == "manual"
    assert created.json()["item"]["assigned_group"] == "直连"

    listed = client.get("/api/rules/categories")
    assert listed.status_code == 200
    by_name = {item["name"]: item for item in listed.json()["items"]}
    assert by_name["SubHub"]["category_type"] == "manual"

    auto_direct = client.put(
        "/api/rules/categories/OpenAI",
        json={"assigned_group": "DIRECT"},
    )
    assert auto_direct.status_code == 400

    manual_direct = client.put(
        "/api/rules/categories/SubHub",
        json={"assigned_group": "DIRECT"},
    )
    assert manual_direct.status_code == 200


def test_manual_category_create_with_direct_rules_succeeds(client) -> None:
    created = client.post(
        "/api/rules/categories/manual",
        json={
            "name": "SubHub",
            "assigned_group": "DIRECT",
            "rules": [
                {"rule_type": "DOMAIN-SUFFIX", "value": "subhub.example.com"},
                {"rule_type": "DOMAIN", "value": "api.subhub.example.com"},
            ],
        },
    )
    assert created.status_code == 200

    category_rules = client.get("/api/rules/categories/SubHub/custom")
    assert category_rules.status_code == 200
    values = [entry["value"] for entry in category_rules.json()["items"]]
    assert set(values) == {"subhub.example.com", "api.subhub.example.com"}
    assert category_rules.json()["category"]["effective_contract_id"] == "action-direct"
    assert category_rules.json()["category"]["active"] is True


def test_manual_category_create_with_policy_rules_requires_contract(client) -> None:
    created = client.post(
        "/api/rules/categories/manual",
        json={
            "name": "SubHub",
            "default_policy": "group",
            "default_group": "中等质量",
            "locked": True,
            "rules": [
                {"rule_type": "DOMAIN-SUFFIX", "value": "subhub.example.com"},
                {"rule_type": "DOMAIN", "value": "api.subhub.example.com"},
            ],
        },
    )
    assert created.status_code == 409
    assert created.json()["detail"] == "category route contract required before adding category rules"


def test_category_custom_rules_use_scenario_direct_state(client) -> None:
    services = client.app.state.services
    services.repo.create_manual_rule_category("SubHub", "", locked=False)
    scenario = _create_scenario(client, scenario_id="custom-direct", slug="custom-direct", name="Custom Direct")

    assign = client.put(
        f"/api/rules/categories/SubHub?scenario_id={scenario.id}",
        json={"assigned_group": "DIRECT"},
    )
    assert assign.status_code == 200

    listed = client.get(f"/api/rules/categories/SubHub/custom?scenario_id={scenario.id}")
    assert listed.status_code == 200
    assert listed.json()["category"]["effective_contract_id"] == "action-direct"
    assert listed.json()["category"]["active"] is True

    created = client.post(
        f"/api/rules/categories/SubHub/custom?scenario_id={scenario.id}",
        json={"rule_type": "DOMAIN-SUFFIX", "value": "subhub.example.com"},
    )
    assert created.status_code == 200
    assert created.json()["item"]["effective_contract_id"] == "action-direct"
    assert created.json()["item"]["active"] is True

    default_listed = client.get("/api/rules/categories/SubHub/custom")
    assert default_listed.status_code == 200
    assert default_listed.json()["category"]["active"] is False


def test_category_assignment_updates_scenario_contract_id(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=10)]
    )
    scenario = _create_scenario(client, scenario_id="custom-medium", slug="custom-medium", name="Custom Medium")

    changed = client.put(
        f"/api/rules/categories/OpenAI?scenario_id={scenario.id}",
        json={"assigned_group": "中等质量"},
    )
    assert changed.status_code == 200

    listed = client.get(f"/api/rules/categories/OpenAI/custom?scenario_id={scenario.id}")
    assert listed.status_code == 200
    assert listed.json()["category"]["effective_contract_id"] == "medium"
    assert listed.json()["category"]["effective_contract_display_name"] == "中等质量"
    assert listed.json()["category"]["active"] is True

    scenario_catalog = client.get(f"/api/service-catalog?scenario_id={scenario.id}")
    assert scenario_catalog.status_code == 200
    openai = next(item for item in scenario_catalog.json()["items"] if item["category_name"] == "OpenAI")
    assert openai["contract_id"] == "medium"
    assert openai["contract_display_name"] == "中等质量"


def test_default_category_assignment_updates_export_contract(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1)]
    )
    services.repo.save_rule_cache("OpenAI", ["DOMAIN-SUFFIX,openai.com,PLACEHOLDER"])

    changed = client.put(
        "/api/rules/categories/OpenAI",
        json={"assigned_group": "中等质量"},
    )
    assert changed.status_code == 200

    listed = client.get("/api/rules/categories")
    assert listed.status_code == 200
    openai = next(item for item in listed.json()["items"] if item["name"] == "OpenAI")
    assert openai["assigned_group"] == "中等质量"
    assert openai["effective_contract_id"] == "medium"

    lines = asyncio.run(services.hub_service.get_rule_lines())
    assert "DOMAIN-SUFFIX,openai.com,中等质量" in lines


def test_restore_system_default_for_auto_category(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [
            RuleCategory(
                name="12306",
                assigned_group="中等质量",
                rule_count=6,
                system_directness="DIRECT",
                system_default_group="DIRECT",
                system_default_locked=True,
                override_group="中等质量",
                override_active=True,
                directness_override="PROXY",
                locked=False,
                lock_source="",
            )
        ]
    )

    listed = client.get("/api/rules/categories")
    assert listed.status_code == 200
    by_name = {item["name"]: item for item in listed.json()["items"]}
    assert by_name["12306"]["can_restore_system_default"] is True
    assert by_name["12306"]["effective_state"]["group"] == "中等质量"

    restored = client.post("/api/rules/categories/12306/restore-system-default")
    assert restored.status_code == 200

    listed_after = client.get("/api/rules/categories")
    assert listed_after.status_code == 200
    by_name_after = {item["name"]: item for item in listed_after.json()["items"]}
    assert by_name_after["12306"]["override_state"]["active"] is False
    assert by_name_after["12306"]["assigned_group"] == "直连"
    assert by_name_after["12306"]["locked"] is True
    assert by_name_after["12306"]["lock_source"] == "system"
    assert by_name_after["12306"]["can_restore_system_default"] is False


def test_assign_locked_category_requires_explicit_unlock(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [
            RuleCategory(
                name="OpenAI",
                assigned_group="中等质量",
                rule_count=6,
                locked=True,
                lock_source="manual",
                override_group="中等质量",
                override_active=True,
            )
        ]
    )

    blocked = client.put(
        "/api/rules/categories/OpenAI",
        json={"assigned_group": "高质量-低倍率"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "category locked"

    unlocked = client.put(
        "/api/rules/categories/OpenAI/lock",
        json={"locked": False},
    )
    assert unlocked.status_code == 200

    changed = client.put(
        "/api/rules/categories/OpenAI",
        json={"assigned_group": "高质量-低倍率"},
    )
    assert changed.status_code == 200

    listed = client.get("/api/rules/categories")
    assert listed.status_code == 200
    by_name = {item["name"]: item for item in listed.json()["items"]}
    assert by_name["OpenAI"]["assigned_group"] == "高质量-低倍率"


def test_manual_category_survives_refresh_and_exports_custom_rules(client, monkeypatch) -> None:
    services = client.app.state.services

    created = client.post(
        "/api/rules/categories/manual",
        json={"name": "SubHub", "assigned_group": "DIRECT"},
    )
    assert created.status_code == 200
    source_name = created.json()["item"]["name"]

    custom = client.post(
        f"/api/rules/categories/{source_name}/custom",
        json={"rule_type": "DOMAIN-SUFFIX", "value": "subhub.example.com"},
    )
    assert custom.status_code == 200

    async def _fake_fetch_catalog(*, use_etag: bool = True):
        return {}, False

    async def _fake_cn_judge(mode: str = "incremental"):
        return None, "none"

    monkeypatch.setattr(services.rule_catalog, "_fetch_category_catalog", _fake_fetch_catalog)
    monkeypatch.setattr(services.rule_catalog, "_load_cn_judge", _fake_cn_judge)

    refreshed = client.post("/api/rules/refresh", json={"mode": "incremental"})
    assert refreshed.status_code == 200

    listed = client.get("/api/rules/categories")
    assert listed.status_code == 200
    assert any(
        item["name"] == source_name and item["category_type"] == "manual"
        for item in listed.json()["items"]
    )

    lines = asyncio.run(services.hub_service.get_rule_lines())
    assert "DOMAIN-SUFFIX,subhub.example.com,直连" in lines


def test_manual_category_rename_updates_related_records(client) -> None:
    services = client.app.state.services

    created = client.post(
        "/api/rules/categories/manual",
        json={"name": "SubHub", "assigned_group": "中等质量"},
    )
    assert created.status_code == 200
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="SubHub",
            catalog_group="手动组",
            contract_id="medium",
            sort_order=0,
            source="manual",
        )
    )

    custom = client.post(
        "/api/rules/categories/SubHub/custom",
        json={"rule_type": "DOMAIN-SUFFIX", "value": "subhub.example.com"},
    )
    assert custom.status_code == 200

    pinned = client.put(
        "/api/rules/categories/SubHub/pin",
        json={"pin_group": "手动组"},
    )
    assert pinned.status_code == 200

    services.repo.save_rule_cache("SubHub", ["DOMAIN-SUFFIX,cache.example.com,PLACEHOLDER"])
    services.repo.replace_pending_rule_category_directness_reviews(
        [
            RuleCategoryDirectnessReview(
                id="manual-review-1",
                category_name="SubHub",
                proposed_decision="DIRECT",
                status="pending",
                created_at="2026-01-01T00:00:00Z",
            )
        ]
    )

    renamed = client.put(
        "/api/rules/categories/manual/SubHub/rename",
        json={"new_name": "SubHubDirect"},
    )
    assert renamed.status_code == 200

    listed = client.get("/api/rules/categories")
    assert listed.status_code == 200
    names = {item["name"] for item in listed.json()["items"]}
    assert "SubHub" not in names
    assert "SubHubDirect" in names

    category_rules = client.get("/api/rules/categories/SubHubDirect/custom")
    assert category_rules.status_code == 200
    assert category_rules.json()["items"][0]["value"] == "subhub.example.com"

    pins = client.get("/api/rules/pins")
    assert pins.status_code == 200
    assert any(item["category_name"] == "SubHubDirect" for item in pins.json()["pinned"])
    assert not any(item["category_name"] == "SubHub" for item in pins.json()["pinned"])

    assert services.repo.load_rule_cache("SubHub") is None
    assert services.repo.load_rule_cache("SubHubDirect") is not None
    pending = services.repo.list_rule_category_directness_reviews(status="pending")
    assert any(item.category_name == "SubHubDirect" for item in pending)
    assert not any(item.category_name == "SubHub" for item in pending)


def test_manual_category_delete_cleans_related_records(client) -> None:
    services = client.app.state.services

    created = client.post(
        "/api/rules/categories/manual",
        json={"name": "SubHub", "assigned_group": "DIRECT"},
    )
    assert created.status_code == 200

    custom = client.post(
        "/api/rules/categories/SubHub/custom",
        json={"rule_type": "DOMAIN-SUFFIX", "value": "delete.example.com"},
    )
    assert custom.status_code == 200

    pinned = client.put(
        "/api/rules/categories/SubHub/pin",
        json={"pin_group": "手动组"},
    )
    assert pinned.status_code == 200

    services.repo.save_rule_cache("SubHub", ["DOMAIN-SUFFIX,cache.example.com,PLACEHOLDER"])
    services.repo.replace_pending_rule_category_directness_reviews(
        [
            RuleCategoryDirectnessReview(
                id="manual-review-2",
                category_name="SubHub",
                proposed_decision="DIRECT",
                status="pending",
                created_at="2026-01-01T00:00:00Z",
            )
        ]
    )

    deleted = client.delete("/api/rules/categories/manual/SubHub")
    assert deleted.status_code == 200

    listed = client.get("/api/rules/categories")
    assert listed.status_code == 200
    assert not any(item["name"] == "SubHub" for item in listed.json()["items"])

    category_rules = services.repo.list_custom_rules(category_name="SubHub")
    assert category_rules == []
    pins = client.get("/api/rules/pins")
    assert pins.status_code == 200
    assert not any(item["category_name"] == "SubHub" for item in pins.json()["pinned"])
    assert services.repo.load_rule_cache("SubHub") is None
    pending = services.repo.list_rule_category_directness_reviews(status="pending")
    assert not any(item.category_name == "SubHub" for item in pending)


def _seed_categories(client):
    """Ensure some rule categories exist for pin tests."""
    repo = client.app.state.services.repo
    repo.save_rule_categories([
        RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=10, rule_source="github", updated_at="", locked=False),
        RuleCategory(name="Claude", assigned_group="高质量-高倍率", rule_count=5, rule_source="github", updated_at="", locked=False),
        RuleCategory(name="YouTube", assigned_group="低质量大流量", rule_count=20, rule_source="github", updated_at="", locked=False),
        RuleCategory(name="Netflix", assigned_group="中等质量", rule_count=8, rule_source="github", updated_at="", locked=False),
    ])


def test_create_pin_group(client) -> None:
    _seed_categories(client)

    # Create a new empty group
    resp = client.post(
        "/api/rules/pin-groups",
        json={"group_name": "AI 服务", "mode": BUSINESS_GROUP_MODE_AD_BLOCK},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["group_name"] == "AI 服务"
    assert resp.json()["mode"] == BUSINESS_GROUP_MODE_AD_BLOCK

    # Verify group exists
    pins = client.get("/api/rules/pins")
    assert any(
        g["group_name"] == "AI 服务" and g["mode"] == BUSINESS_GROUP_MODE_AD_BLOCK
        for g in pins.json()["groups"]
    )

    # Duplicate returns 409
    resp = client.post("/api/rules/pin-groups", json={"group_name": "AI 服务"})
    assert resp.status_code == 409

    # Empty name returns 400
    resp = client.post("/api/rules/pin-groups", json={"group_name": "  "})
    assert resp.status_code == 400

    # Clean up
    client.delete("/api/rules/pin-groups/AI 服务")


def test_pin_unpin_category(client) -> None:
    _seed_categories(client)

    # Pin OpenAI
    resp = client.put(
        "/api/rules/categories/OpenAI/pin",
        json={"pin_group": "AI 服务"},
    )
    assert resp.status_code == 200

    # List pins
    pins = client.get("/api/rules/pins")
    assert pins.status_code == 200
    assert len(pins.json()["pinned"]) == 1
    assert pins.json()["pinned"][0]["category_name"] == "OpenAI"
    assert pins.json()["pinned"][0]["pin_group"] == "AI 服务"
    assert len(pins.json()["groups"]) == 1
    assert pins.json()["groups"][0]["group_name"] == "AI 服务"

    # Categories include pin info
    cats = client.get("/api/rules/categories")
    assert cats.status_code == 200
    openai_cat = next(c for c in cats.json()["items"] if c["name"] == "OpenAI")
    assert openai_cat["pinned"] is True
    assert openai_cat["pin_group"] == "AI 服务"
    youtube_cat = next(c for c in cats.json()["items"] if c["name"] == "YouTube")
    assert youtube_cat["pinned"] is False

    # Unpin
    resp = client.delete("/api/rules/categories/OpenAI/pin")
    assert resp.status_code == 200

    pins = client.get("/api/rules/pins")
    assert len(pins.json()["pinned"]) == 0

    # Unpin non-existent
    resp = client.delete("/api/rules/categories/OpenAI/pin")
    assert resp.status_code == 404


def test_pin_nonexistent_category(client) -> None:
    resp = client.put(
        "/api/rules/categories/NonExistent/pin",
        json={"pin_group": "test"},
    )
    assert resp.status_code == 404


def test_pin_group_rename(client) -> None:
    _seed_categories(client)

    client.put("/api/rules/categories/OpenAI/pin", json={"pin_group": "AI"})
    client.put("/api/rules/categories/Claude/pin", json={"pin_group": "AI"})

    # Rename
    resp = client.put(
        "/api/rules/pin-groups/AI/rename",
        json={"new_name": "AI 服务", "mode": BUSINESS_GROUP_MODE_AD_BLOCK},
    )
    assert resp.status_code == 200

    pins = client.get("/api/rules/pins")
    for p in pins.json()["pinned"]:
        assert p["pin_group"] == "AI 服务"
    assert any(
        g["group_name"] == "AI 服务" and g["mode"] == BUSINESS_GROUP_MODE_AD_BLOCK
        for g in pins.json()["groups"]
    )
    assert not any(g["group_name"] == "AI" for g in pins.json()["groups"])

    # Rename non-existent
    resp = client.put(
        "/api/rules/pin-groups/NoSuchGroup/rename",
        json={"new_name": "X"},
    )
    assert resp.status_code == 404


def test_pin_group_delete(client) -> None:
    _seed_categories(client)

    client.put("/api/rules/categories/YouTube/pin", json={"pin_group": "流媒体"})
    client.put("/api/rules/categories/Netflix/pin", json={"pin_group": "流媒体"})

    resp = client.delete("/api/rules/pin-groups/流媒体")
    assert resp.status_code == 200

    pins = client.get("/api/rules/pins")
    assert len(pins.json()["pinned"]) == 0
    assert len(pins.json()["groups"]) == 0

    # Delete non-existent
    resp = client.delete("/api/rules/pin-groups/流媒体")
    assert resp.status_code == 404


def test_pin_reorder(client) -> None:
    _seed_categories(client)

    client.put("/api/rules/categories/OpenAI/pin", json={"pin_group": "AI", "sort_order": 0})
    client.put("/api/rules/categories/Claude/pin", json={"pin_group": "AI", "sort_order": 1})

    resp = client.put("/api/rules/pins/reorder", json={
        "items": [
            {"category_name": "Claude", "sort_order": 0, "pin_group": "AI"},
            {"category_name": "OpenAI", "sort_order": 1, "pin_group": "AI"},
        ]
    })
    assert resp.status_code == 200

    pins = client.get("/api/rules/pins")
    names = [p["category_name"] for p in pins.json()["pinned"]]
    assert names == ["Claude", "OpenAI"]


def test_pin_group_reorder(client) -> None:
    _seed_categories(client)

    client.put("/api/rules/categories/OpenAI/pin", json={"pin_group": "AI"})
    client.put("/api/rules/categories/YouTube/pin", json={"pin_group": "流媒体"})

    resp = client.put("/api/rules/pin-groups/reorder", json={
        "items": [
            {"group_name": "流媒体", "sort_order": 0},
            {"group_name": "AI", "sort_order": 1},
        ]
    })
    assert resp.status_code == 200

    pins = client.get("/api/rules/pins")
    group_names = [g["group_name"] for g in pins.json()["groups"]]
    assert group_names == ["流媒体", "AI"]


def test_legacy_pin_endpoints_respect_scenario_id(client) -> None:
    _seed_categories(client)
    scenario = _create_scenario(client, scenario_id="pin-s1", slug="pin-s1", name="Pin Scenario")

    created = client.post(
        f"/api/rules/pin-groups?scenario_id={scenario.id}",
        json={"group_name": "AI 服务"},
    )
    assert created.status_code == 200

    pinned = client.put(
        f"/api/rules/categories/OpenAI/pin?scenario_id={scenario.id}",
        json={"pin_group": "AI 服务", "sort_order": 3},
    )
    assert pinned.status_code == 200

    scenario_pins = client.get(f"/api/rules/pins?scenario_id={scenario.id}")
    assert scenario_pins.status_code == 200
    assert any(item["group_name"] == "AI 服务" for item in scenario_pins.json()["groups"])
    assert any(item["category_name"] == "OpenAI" and item["pin_group"] == "AI 服务" for item in scenario_pins.json()["pinned"])

    default_pins = client.get("/api/rules/pins")
    assert default_pins.status_code == 200
    assert not any(item["group_name"] == "AI 服务" for item in default_pins.json()["groups"])
    assert not any(item["category_name"] == "OpenAI" for item in default_pins.json()["pinned"])

    renamed = client.put(
        f"/api/rules/pin-groups/AI 服务/rename?scenario_id={scenario.id}",
        json={"new_name": "AI 工作流"},
    )
    assert renamed.status_code == 200

    renamed_pins = client.get(f"/api/rules/pins?scenario_id={scenario.id}")
    assert any(item["group_name"] == "AI 工作流" for item in renamed_pins.json()["groups"])
    assert any(item["category_name"] == "OpenAI" and item["pin_group"] == "AI 工作流" for item in renamed_pins.json()["pinned"])

    unpinned = client.delete(f"/api/rules/categories/OpenAI/pin?scenario_id={scenario.id}")
    assert unpinned.status_code == 200
    deleted = client.delete(f"/api/rules/pin-groups/AI 工作流?scenario_id={scenario.id}")
    assert deleted.status_code == 200

    final_default_pins = client.get("/api/rules/pins")
    assert final_default_pins.status_code == 200
    assert not any(item["group_name"] == "AI 工作流" for item in final_default_pins.json()["groups"])


def test_bulk_assign_rule_categories_respects_scenario_id(client) -> None:
    _seed_categories(client)
    scenario = _create_scenario(client, scenario_id="bulk-s1", slug="bulk-s1", name="Bulk Scenario")

    resp = client.post(
        f"/api/rules/categories/bulk-assign?scenario_id={scenario.id}",
        json={"assignments": {"OpenAI": "中等质量"}},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1

    scenario_categories = client.get(f"/api/rules/categories?scenario_id={scenario.id}")
    assert scenario_categories.status_code == 200
    scenario_openai = next(item for item in scenario_categories.json()["items"] if item["name"] == "OpenAI")
    assert scenario_openai["assigned_group"] == "中等质量"

    default_categories = client.get("/api/rules/categories")
    assert default_categories.status_code == 200
    default_openai = next(item for item in default_categories.json()["items"] if item["name"] == "OpenAI")
    assert default_openai["assigned_group"] == "高质量-高倍率"


def test_bulk_update_service_catalog_groups_respects_scenario_id_and_preserves_contract(client) -> None:
    _seed_categories(client)
    scenario = _create_scenario(client, scenario_id="catalog-bulk-s1", slug="catalog-bulk-s1", name="Catalog Bulk Scenario")
    services = client.app.state.services
    services.repo.save_scenario_service_catalog_entry(
        scenario.id,
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="旧分组",
            contract_id="hq_premium",
            sort_order=5,
            source="manual",
        ),
    )

    resp = client.put(
        f"/api/service-catalog/bulk-groups?scenario_id={scenario.id}",
        json={"assignments": {"OpenAI": "AI 服务", "Unknown": "AI 服务"}},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1
    assert resp.json()["invalid"] == ["Unknown"]

    scenario_catalog = client.get(f"/api/service-catalog?scenario_id={scenario.id}")
    assert scenario_catalog.status_code == 200
    scenario_openai = next(item for item in scenario_catalog.json()["items"] if item["category_name"] == "OpenAI")
    assert scenario_openai["catalog_group"] == "AI 服务"
    assert scenario_openai["contract_id"] == "hq_premium"
    assert scenario_openai["sort_order"] == 5

    default_catalog = client.get("/api/service-catalog")
    assert default_catalog.status_code == 200
    default_openai = next(item for item in default_catalog.json()["items"] if item["category_name"] == "OpenAI")
    assert default_openai["catalog_group"] == ""


def test_update_service_catalog_entry_preserves_inherited_scenario_group_when_only_contract_changes(client) -> None:
    _seed_categories(client)
    services = client.app.state.services
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="hq_premium",
            sort_order=5,
            source="manual",
        )
    )
    scenario = _create_scenario(client, scenario_id="catalog-inherit-s1", slug="catalog-inherit-s1", name="Catalog Inherit Scenario")

    updated = client.put(
        f"/api/service-catalog/OpenAI?scenario_id={scenario.id}",
        json={"contract_id": "medium"},
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["catalog_group"] == "AI 服务"
    assert updated.json()["item"]["contract_id"] == "medium"
    assert updated.json()["item"]["sort_order"] == 5

    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="开发工具",
            contract_id="hq_premium",
            sort_order=5,
            source="manual",
        )
    )

    scenario_catalog = client.get(f"/api/service-catalog?scenario_id={scenario.id}")
    assert scenario_catalog.status_code == 200
    scenario_openai = next(item for item in scenario_catalog.json()["items"] if item["category_name"] == "OpenAI")
    assert scenario_openai["catalog_group"] == "开发工具"
    assert scenario_openai["contract_id"] == "medium"
    assert scenario_openai["sort_order"] == 5


def test_update_service_catalog_entry_preserves_explicitly_cleared_scenario_group_when_only_contract_changes(client) -> None:
    _seed_categories(client)
    services = client.app.state.services
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="hq_premium",
            sort_order=5,
            source="manual",
        )
    )
    scenario = _create_scenario(client, scenario_id="catalog-clear-s1", slug="catalog-clear-s1", name="Catalog Clear Scenario")

    cleared = client.put(
        f"/api/service-catalog/OpenAI?scenario_id={scenario.id}",
        json={"contract_id": "hq_premium", "catalog_group": "", "sort_order": 0},
    )
    assert cleared.status_code == 200
    assert cleared.json()["item"]["catalog_group"] == ""

    updated = client.put(
        f"/api/service-catalog/OpenAI?scenario_id={scenario.id}",
        json={"contract_id": "medium"},
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["catalog_group"] == ""
    assert updated.json()["item"]["contract_id"] == "medium"

    scenario_catalog = client.get(f"/api/service-catalog?scenario_id={scenario.id}")
    assert scenario_catalog.status_code == 200
    scenario_openai = next(item for item in scenario_catalog.json()["items"] if item["category_name"] == "OpenAI")
    assert scenario_openai["catalog_group"] == ""
    assert scenario_openai["contract_id"] == "medium"

    override = services.repo.get_scenario_service_catalog_override(scenario.id, "OpenAI")
    assert override is not None
    assert override.catalog_group == ""


def test_bulk_update_service_catalog_groups_updates_default_catalog_and_pins(client) -> None:
    _seed_categories(client)
    services = client.app.state.services
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="旧分组",
            contract_id="hq_premium",
            sort_order=5,
            source="manual",
        )
    )

    resp = client.put(
        "/api/service-catalog/bulk-groups",
        json={"assignments": {"OpenAI": "AI 服务", "Unknown": "AI 服务"}},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1
    assert resp.json()["invalid"] == ["Unknown"]

    listed_catalog = client.get("/api/service-catalog")
    assert listed_catalog.status_code == 200
    openai = next(item for item in listed_catalog.json()["items"] if item["category_name"] == "OpenAI")
    assert openai["catalog_group"] == "AI 服务"
    assert openai["contract_id"] == "hq_premium"
    assert openai["sort_order"] == 5

    global_entry = services.repo.get_service_catalog_entry("OpenAI")
    assert global_entry is not None
    assert global_entry.catalog_group == "AI 服务"
    assert global_entry.contract_id == "hq_premium"
    assert global_entry.sort_order == 5

    pins = client.get("/api/rules/pins")
    assert pins.status_code == 200
    assert any(item["group_name"] == "AI 服务" for item in pins.json()["groups"])
    assert any(
        item["category_name"] == "OpenAI" and item["pin_group"] == "AI 服务"
        for item in pins.json()["pinned"]
    )


def test_bulk_update_service_catalog_groups_clears_default_group_but_keeps_contract(client) -> None:
    _seed_categories(client)
    services = client.app.state.services
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="hq_premium",
            sort_order=2,
            source="manual",
        )
    )

    resp = client.put(
        "/api/service-catalog/bulk-groups",
        json={"assignments": {"OpenAI": ""}},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1
    assert resp.json()["invalid"] == []

    listed_catalog = client.get("/api/service-catalog")
    assert listed_catalog.status_code == 200
    openai = next(item for item in listed_catalog.json()["items"] if item["category_name"] == "OpenAI")
    assert openai["catalog_group"] == ""
    assert openai["contract_id"] == "hq_premium"

    global_entry = services.repo.get_service_catalog_entry("OpenAI")
    assert global_entry is not None
    assert global_entry.catalog_group == ""
    assert global_entry.contract_id == "hq_premium"

    pins = client.get("/api/rules/pins")
    assert pins.status_code == 200
    assert not any(item["category_name"] == "OpenAI" for item in pins.json()["pinned"])


def test_bulk_update_service_catalog_groups_allows_contractless_default_categories(client) -> None:
    _seed_categories(client)
    client.app.state.services.repo.save_rule_categories(
        [RuleCategory(name="Notion", assigned_group="", rule_count=1)]
    )

    resp = client.put(
        "/api/service-catalog/bulk-groups",
        json={"assignments": {"Notion": "AI 服务"}},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1
    assert resp.json()["invalid"] == []

    listed_catalog = client.get("/api/service-catalog")
    assert listed_catalog.status_code == 200
    notion = next(item for item in listed_catalog.json()["items"] if item["category_name"] == "Notion")
    assert notion["catalog_group"] == "AI 服务"
    assert notion["contract_id"] == ""

    global_entry = client.app.state.services.repo.get_service_catalog_entry("Notion")
    assert global_entry is not None
    assert global_entry.catalog_group == "AI 服务"
    assert global_entry.contract_id == ""

    pins = client.get("/api/rules/pins")
    assert pins.status_code == 200
    assert any(
        item["category_name"] == "Notion" and item["pin_group"] == "AI 服务"
        for item in pins.json()["pinned"]
    )


def test_bulk_update_service_catalog_groups_allows_clearing_and_contractless_categories(client) -> None:
    _seed_categories(client)
    client.app.state.services.repo.save_rule_categories(
        [RuleCategory(name="Notion", assigned_group="", rule_count=1)]
    )
    scenario = _create_scenario(client, scenario_id="catalog-bulk-s2", slug="catalog-bulk-s2", name="Catalog Bulk Scenario 2")
    services = client.app.state.services
    services.repo.save_scenario_service_catalog_entry(
        scenario.id,
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="hq_premium",
            sort_order=2,
            source="manual",
        ),
    )

    resp = client.put(
        f"/api/service-catalog/bulk-groups?scenario_id={scenario.id}",
        json={"assignments": {"OpenAI": "", "Notion": "AI 服务"}},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 2
    assert resp.json()["invalid"] == []

    catalog = client.get(f"/api/service-catalog?scenario_id={scenario.id}")
    assert catalog.status_code == 200
    items = {item["category_name"]: item for item in catalog.json()["items"]}
    assert items["OpenAI"]["catalog_group"] == ""
    assert items["OpenAI"]["contract_id"] == "hq_premium"
    assert items["Notion"]["catalog_group"] == "AI 服务"
    assert items["Notion"]["contract_id"] == ""


def test_pin_export_returns_prompt(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories([
        RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=10, rule_source="github", updated_at="", locked=False),
        RuleCategory(name="YouTube", assigned_group="低质量大流量", rule_count=20, rule_source="github", updated_at="", locked=False),
    ])
    client.put("/api/rules/categories/OpenAI/pin", json={"pin_group": "AI 服务"})

    resp = client.get("/api/rules/pins/export")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "prompt" in data
    assert "OpenAI" in data["prompt"]
    assert "YouTube" in data["prompt"]
    assert data["pinned_count"] == 1
    assert "candidates" in data
    assert len(data["candidates"]) >= 2


def test_rule_and_pin_export_include_custom_preferences(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories([
        RuleCategory(name="Netflix", assigned_group="", rule_count=10, rule_source="github", updated_at="", locked=False),
        RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=20, rule_source="github", updated_at="", locked=False),
    ])
    services.repo.pin_category("OpenAI", "AI 服务")
    services.rule_catalog.update_llm_export_preferences(
        rules_preferences="Netflix 可以分配到中等质量组",
        pins_preferences="优先把 OpenAI 放到 AI 服务",
    )

    rules_resp = client.get("/api/rules/export")
    assert rules_resp.status_code == 200
    assert "# 我的分组偏好" in rules_resp.json()["prompt"]
    assert "Netflix 可以分配到中等质量组" in rules_resp.json()["prompt"]
    assert '"分类名": "contract_id"' in rules_resp.json()["prompt"]

    pins_resp = client.get("/api/rules/pins/export")
    assert pins_resp.status_code == 200
    assert "# 你的置顶偏好" in pins_resp.json()["prompt"]
    assert "优先把 OpenAI 放到 AI 服务" in pins_resp.json()["prompt"]
    assert '"分类名": "置顶分组名"' in pins_resp.json()["prompt"]


def test_pin_import_replaces_all(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories([
        RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=10, rule_source="github", updated_at="", locked=False),
        RuleCategory(name="YouTube", assigned_group="低质量大流量", rule_count=20, rule_source="github", updated_at="", locked=False),
        RuleCategory(name="Telegram", assigned_group="中等质量", rule_count=5, rule_source="github", updated_at="", locked=False),
    ])
    # Pre-existing pin
    client.put("/api/rules/categories/OpenAI/pin", json={"pin_group": "旧分组"})
    pins_before = client.get("/api/rules/pins").json()
    assert len(pins_before["pinned"]) == 1

    # Import replaces all
    resp = client.post("/api/rules/pins/import", json={
        "OpenAI": "AI 服务",
        "YouTube": "流媒体",
        "NonExistent": "不存在",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["pinned"] == 2
    assert "NonExistent" in data["invalid"]

    # Verify the old pin is replaced
    pins_after = client.get("/api/rules/pins").json()
    assert len(pins_after["pinned"]) == 2
    pin_map = {p["category_name"]: p["pin_group"] for p in pins_after["pinned"]}
    assert pin_map["OpenAI"] == "AI 服务"
    assert pin_map["YouTube"] == "流媒体"
    # Old group "旧分组" should be gone
    group_names = [g["group_name"] for g in pins_after["groups"]]
    assert "旧分组" not in group_names
    assert "AI 服务" in group_names
    assert "流媒体" in group_names


def test_business_group_alias_endpoints(client) -> None:
    _seed_categories(client)

    created = client.post(
        "/api/rules/business-groups",
        json={"name": "AI 服务", "mode": BUSINESS_GROUP_MODE_AD_BLOCK},
    )
    assert created.status_code == 200
    assert created.json()["item"]["mode"] == BUSINESS_GROUP_MODE_AD_BLOCK

    assigned = client.put(
        "/api/rules/categories/OpenAI/business-group",
        json={"business_group": "AI 服务", "sort_order": 3},
    )
    assert assigned.status_code == 200

    listed = client.get("/api/rules/business-groups")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert any(item["name"] == "AI 服务" for item in items)
    ai_group = next(item for item in items if item["name"] == "AI 服务")
    assert "OpenAI" in ai_group["category_names"]
    assert ai_group["mode"] == BUSINESS_GROUP_MODE_AD_BLOCK

    renamed = client.put(
        "/api/rules/business-groups/AI 服务/rename",
        json={"new_name": "AI 工作流"},
    )
    assert renamed.status_code == 200

    listed = client.get("/api/rules/business-groups")
    assert listed.status_code == 200
    assert any(item["name"] == "AI 工作流" for item in listed.json()["items"])

    unassigned = client.delete("/api/rules/categories/OpenAI/business-group")
    assert unassigned.status_code == 200

    deleted = client.delete("/api/rules/business-groups/AI 工作流")
    assert deleted.status_code == 200


def test_ad_block_preview_and_subscription_rendering_varies_by_target(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_standard_source(
        StandardSource(
            id="s-ad",
            name="广告源",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="中等质量",
            enabled=True,
        )
    )
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-ad",
            device_key="iphone",
            device_name="iPhone",
            token="tok-ad",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-ad",
        [
            NodeRecord(
                name="node-1",
                host="n1.example.com",
                port=443,
                protocol="http",
                quality_group="中等质量",
            )
        ],
    )
    services.repo.save_rule_categories(
        [RuleCategory(name="Ads", assigned_group="中等质量", rule_count=1)]
    )
    services.repo.save_rule_cache("Ads", ["DOMAIN-SUFFIX,ads.example.com,PLACEHOLDER"])
    created = client.post(
        "/api/rules/business-groups",
        json={"name": "广告拦截", "mode": BUSINESS_GROUP_MODE_AD_BLOCK},
    )
    assert created.status_code == 200
    pinned = client.put(
        "/api/rules/categories/Ads/business-group",
        json={"business_group": "广告拦截"},
    )
    assert pinned.status_code == 200

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    clash_preview = client.get("/api/devices/tok-ad/render-preview?target=clash")
    assert clash_preview.status_code == 200
    clash_preview_payload = yaml.safe_load(clash_preview.json()["content"])
    assert "RULE-SET,catalog-rules-ad_block,REJECT" in clash_preview_payload["rules"]
    assert "name: 广告拦截" not in clash_preview.json()["content"]

    sr_preview = client.get("/api/devices/tok-ad/render-preview?target=shadowrocket")
    assert sr_preview.status_code == 200
    assert "DOMAIN-SUFFIX,ads.example.com,REJECT" in sr_preview.json()["content"]
    assert "广告拦截 = select" not in sr_preview.json()["content"]

    surge_preview = client.get("/api/devices/tok-ad/render-preview?target=surge")
    assert surge_preview.status_code == 200
    assert "广告拦截 = select" not in surge_preview.json()["content"]
    assert "/surge/domain-set/reject-domains.txt" in surge_preview.json()["content"]
    assert "REJECT,pre-matching" in surge_preview.json()["content"]
    ad_group = next(
        item
        for item in surge_preview.json()["policy_ir"]["business_groups"]
        if item["name"] == "广告拦截"
    )
    assert ad_group["mode"] == BUSINESS_GROUP_MODE_AD_BLOCK
    assert any(item["code"] == "empty-pool" for item in surge_preview.json()["warnings"])

    clash_sub = client.get(_scenario_sub_path("tok-ad", "clash.yaml"))
    assert clash_sub.status_code == 200
    clash_sub_payload = yaml.safe_load(clash_sub.text)
    assert "RULE-SET,catalog-rules-ad_block,REJECT" in clash_sub_payload["rules"]
    assert "name: 广告拦截" not in clash_sub.text
    clash_ad_rules = client.get(_scenario_sub_path("tok-ad", "clash/rules/catalog-rules-ad_block.list"))
    assert clash_ad_rules.status_code == 200
    assert clash_ad_rules.text == "DOMAIN-SUFFIX,ads.example.com\n"

    sr_sub = client.get(_scenario_sub_path("tok-ad", "shadowrocket.conf"))
    assert sr_sub.status_code == 200
    assert "DOMAIN-SUFFIX,ads.example.com,REJECT" in sr_sub.text
    assert "广告拦截 = select" not in sr_sub.text

    surge_sub = client.get(_scenario_sub_path("tok-ad", "surge.conf"))
    assert surge_sub.status_code == 200
    assert "广告拦截 = select" not in surge_sub.text
    assert "/surge/domain-set/reject-domains.txt" in surge_sub.text
    assert "REJECT,pre-matching" in surge_sub.text

    reject_asset = client.get(_scenario_sub_path("tok-ad", "surge/domain-set/reject-domains.txt"))
    assert reject_asset.status_code == 200
    assert reject_asset.text == ".ads.example.com\n"


def test_surge_settings_preview_and_overlay_endpoints(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d1",
            device_key="mac",
            device_name="Mac",
            token="tok1",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s1",
            name="源A",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="高质量-高倍率",
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
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1)]
    )
    services.repo.save_rule_cache("OpenAI", ["DOMAIN-SUFFIX,openai.com,PLACEHOLDER"])
    services.repo.pin_category("OpenAI", "AI 服务")

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    process_rules = client.put(
        "/api/settings/surge/process-rules",
        json={
            "items": [
                {
                    "business_group": "AI 服务",
                    "match_type": "PROCESS-NAME",
                    "value": "Claude",
                    "sort_order": 10,
                    "enabled": True,
                }
            ]
        },
    )
    assert process_rules.status_code == 200
    assert process_rules.json()["items"][0]["business_group"] == "AI 服务"
    assert process_rules.json()["items"][0]["contract_id"] == ""

    programs = client.put(
        "/api/settings/surge/external-proxy-programs",
        json={
            "items": [
                {
                    "business_group": "AI 服务",
                    "program_path": "/usr/local/bin/ssh-socks",
                    "args": ["--listen", "17890"],
                    "local_port": 17890,
                    "name": "SSH SOCKS",
                    "enabled": True,
                }
            ]
        },
    )
    assert programs.status_code == 200
    assert programs.json()["items"][0]["local_port"] == 17890

    preview = client.get("/api/devices/tok1/render-preview?target=surge")
    assert preview.status_code == 200
    assert preview.json()["target"] == "surge"
    assert "FINAL,兜底代理,dns-failed" in preview.json()["content"]
    assert any(item["name"] == "高质量-高倍率" for item in preview.json()["policy_ir"]["business_groups"])
    assert not any(item["name"] == "AI 服务" for item in preview.json()["policy_ir"]["business_groups"])
    assert any(item["code"] == "mac-only-rule-ignored" for item in preview.json()["warnings"])

    devices = client.get("/api/devices")
    assert devices.status_code == 200
    device_payload = next(item for item in devices.json()["items"] if item["device_name"] == "Mac")
    subscription_id = device_payload["subscription_id"]
    assert device_payload["overlay_status"]["available"] is True
    assert device_payload["overlay_status"]["reason_code"] == ""
    assert device_payload["overlay_status"]["renderable_process_rule_count"] == 1
    assert device_payload["overlay_status"]["renderable_external_proxy_program_count"] == 1

    overlay = client.get(_scenario_sub_path("tok1", "surge-mac-overlay.conf"))
    assert overlay.status_code == 200
    assert (
        "#!MANAGED-CONFIG "
        f"http://testserver/sub/device/{subscription_id}/default/surge-mac-overlay.conf"
        in overlay.text
    )
    assert f"#!include http://testserver/sub/device/{subscription_id}/default/surge.conf" in overlay.text
    assert "PROCESS-NAME,Claude,高质量-高倍率" in overlay.text
    assert "exec=/usr/local/bin/ssh-socks" in overlay.text
    assert "surge-mac-overlay-empty" not in overlay.text


def test_surge_mac_overlay_reports_disabled_templates_as_unavailable(client, monkeypatch) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-disabled",
            device_key="mac-disabled",
            device_name="Mac Disabled",
            token="tok-disabled-overlay",
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
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1)]
    )
    services.repo.save_rule_cache("OpenAI", ["DOMAIN-SUFFIX,openai.com,PLACEHOLDER"])
    services.repo.pin_category("OpenAI", "AI 服务")

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)

    saved = client.put(
        "/api/settings/surge/process-rules",
        json={
            "items": [
                {
                    "business_group": "AI 服务",
                    "match_type": "PROCESS-NAME",
                    "value": "Claude",
                    "sort_order": 10,
                    "enabled": False,
                }
            ]
        },
    )
    assert saved.status_code == 200

    devices = client.get("/api/devices")
    assert devices.status_code == 200
    device_payload = next(
        item
        for item in devices.json()["items"]
        if item["device_name"] == "Mac Disabled"
    )
    subscription_id = device_payload["subscription_id"]
    overlay_status = device_payload["overlay_status"]
    assert overlay_status["available"] is False
    assert overlay_status["reason_code"] == "all_templates_disabled"
    assert overlay_status["renderable_process_rule_count"] == 0
    assert overlay_status["renderable_external_proxy_program_count"] == 0

    overlay = client.get(_scenario_sub_path("tok-disabled-overlay", "surge-mac-overlay.conf"))
    assert overlay.status_code == 200
    assert "[Rule]" not in overlay.text
    assert (
        "#!MANAGED-CONFIG "
        f"http://testserver/sub/device/{subscription_id}/default/surge-mac-overlay.conf"
        in overlay.text
    )
    assert (
        f"#!include http://testserver/sub/device/{subscription_id}/default/surge.conf"
        in overlay.text
    )
    assert "surge-mac-overlay-empty" not in overlay.text
    assert "none are enabled" not in overlay.text
    assert "Open SubHub Manage > Advanced > Surge Process Rules / External Proxy Programs." not in overlay.text


def test_contract_service_catalog_and_general_profile_endpoints(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1)]
    )

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

    unchanged_contract = client.put(
        "/api/contracts/medium",
        json={
            "strategy_type": "strict",
            "primary_pools": ["medium"],
            "fallback_pools": [],
            "failure_action": "interrupt",
            "enabled": True,
        },
    )
    assert unchanged_contract.status_code == 200
    assert unchanged_contract.json()["item"]["strategy_type"] == "strict"
    assert unchanged_contract.json()["item"]["primary_pools"] == ["medium"]
    assert unchanged_contract.json()["item"]["fallback_pools"] == []

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
    assert openai_entry["contract_display_name"] == "高质量-高倍率"

    contracts = client.get("/api/contracts")
    assert contracts.status_code == 200
    contract_items = {item["id"]: item for item in contracts.json()["items"]}
    assert contract_items["hq_standard"]["display_name"] == "高质量低延迟"
    assert contract_items["hq_standard"]["description"] == "适合 AI / 实时 API / 低延迟场景"
    global_entry = client.app.state.services.repo.get_service_catalog_entry("OpenAI")
    assert global_entry is not None
    assert global_entry.contract_id == "hq_premium"
    assert global_entry.catalog_group == "AI 服务"

    general_profile = client.get("/api/general-profile")
    assert general_profile.status_code == 200
    assert general_profile.json()["item"]["is_system_default"] is True
    assert "capabilities" in general_profile.json()["item"]

    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200
    first_group = profile_capabilities.json()["groups"][0]
    assert first_group["title_i18n"]["zh"]
    assert first_group["title_i18n"]["en"] == first_group["title"]
    assert any(
        capability["id"] == "excluded-routes"
        for group in profile_capabilities.json()["groups"]
        for capability in group["capabilities"]
    )
    mihomo_runtime = next(
        capability
        for group in profile_capabilities.json()["groups"]
        for capability in group["capabilities"]
        if capability["id"] == "mihomo-runtime"
    )
    log_level = next(item for item in mihomo_runtime["subfields"] if item["id"] == "log_level")
    assert log_level["clients"]["surge"]["support"]["kind"] == "mirror_missing"
    assert log_level["clients"]["surge"]["support"]["status"] == "unsupported"
    assert log_level["clients"]["surge"]["editing_mode"] == "standalone"
    assert log_level["clients"]["surge"]["key"] == "surge_loglevel"
    assert "surge_loglevel" in log_level["clients"]["surge"]["support"]["reason"]
    assert "client-specific override" in log_level["clients"]["surge"]["support"]["reason"]
    clash_log_level = _find_capability_view(
        profile_capabilities.json(),
        group_id="mihomo-core",
        capability_id="mihomo-runtime",
        subfield_id="log_level",
        client="clash",
    )
    assert clash_log_level["type"] == "select"
    assert clash_log_level["editing_mode"] == "shared"
    assert [item["value"] for item in clash_log_level["options"]] == ["silent", "error", "warning", "info", "debug"]
    assert clash_log_level["options"][0]["description_i18n"]["zh"]
    surge_runtime_log_level = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="surge-runtime",
        subfield_id="loglevel",
        client="surge",
    )
    assert surge_runtime_log_level["type"] == "select"
    assert surge_runtime_log_level["editing_mode"] == "shared"
    assert [item["value"] for item in surge_runtime_log_level["options"]] == ["notify", "warning", "info", "verbose"]
    assert "options" not in log_level["clients"]["shadowrocket"]
    mixed_port = next(item for item in mihomo_runtime["subfields"] if item["id"] == "mixed_port")
    assert mixed_port["clients"]["surge"]["support"]["status"] == "unsupported"
    assert mixed_port["clients"]["surge"]["editing_mode"] == "unavailable"
    assert "key" not in mixed_port["clients"]["surge"]
    assert "shared mirror" in mixed_port["clients"]["surge"]["support"]["reason"]
    assert "native" in mixed_port["clients"]["surge"]["support"]["reason"]
    allow_lan = next(item for item in mihomo_runtime["subfields"] if item["id"] == "allow_lan")
    assert allow_lan["clients"]["surge"]["support"]["status"] == "unsupported"
    assert allow_lan["clients"]["surge"]["editing_mode"] == "unavailable"
    assert "key" not in allow_lan["clients"]["surge"]
    assert "shared mirror" in allow_lan["clients"]["surge"]["support"]["reason_i18n"]["en"]
    assert "override" in allow_lan["clients"]["surge"]["support"]["reason_i18n"]["en"].lower()
    udp_default = next(item for item in mihomo_runtime["subfields"] if item["id"] == "udp_default")
    assert udp_default["clients"]["surge"]["support"]["status"] == "unsupported"
    assert udp_default["clients"]["surge"]["editing_mode"] == "unavailable"
    assert "key" not in udp_default["clients"]["surge"]
    assert "shared mirror" in udp_default["clients"]["surge"]["support"]["reason_i18n"]["en"]
    assert (
        "override" in udp_default["clients"]["surge"]["support"]["reason_i18n"]["en"].lower()
        or "native" in udp_default["clients"]["surge"]["support"]["reason_i18n"]["en"].lower()
    )
    external_controller = _find_capability_view(
        profile_capabilities.json(),
        group_id="mihomo-core",
        capability_id="mihomo-control-api",
        subfield_id="external_controller",
        client="surge",
    )
    assert external_controller["key"] == "surge_http_api"
    assert external_controller["editing_mode"] == "shared"
    secret = _find_capability_view(
        profile_capabilities.json(),
        group_id="mihomo-core",
        capability_id="mihomo-control-api",
        subfield_id="secret",
        client="surge",
    )
    assert secret["key"] == "surge_http_api_secret"
    assert secret["editing_mode"] == "shared"
    url_rewrite = next(
        capability
        for group in profile_capabilities.json()["groups"]
        for capability in group["capabilities"]
        if capability["id"] == "url-rewrite"
    )
    assert url_rewrite["subfields"][0]["clients"]["clash"]["support"]["kind"] == "client_missing"
    assert url_rewrite["subfields"][0]["clients"]["shadowrocket"]["editing_mode"] == "standalone"
    ipv6_capability = next(
        capability
        for group in profile_capabilities.json()["groups"]
        for capability in group["capabilities"]
        if capability["id"] == "ipv6-policy"
    )
    assert ipv6_capability["subfields"][0]["clients"]["clash"]["support"]["status"] == "auto_mapped"
    assert ipv6_capability["subfields"][0]["clients"]["clash"]["editing_mode"] == "shared"

    updated_profile = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {
                "surge_always_real_ip": ["test.example.com"],
                "surge_tun_excluded_routes": ["10.0.0.0/8"],
            },
        },
    )
    assert updated_profile.status_code == 200
    assert updated_profile.json()["item"]["settings"]["surge_always_real_ip"] == ["test.example.com"]

    updated_from_capabilities = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "capabilities": {
                "excluded-routes": {
                    "routes": ["10.0.0.0/8", "172.16.0.0/12"],
                },
                "ipv6-policy": {
                    "enabled": False,
                },
                "mihomo-runtime": {
                    "mixed_port": 7891,
                },
            },
        },
    )
    assert updated_from_capabilities.status_code == 200
    updated_settings = updated_from_capabilities.json()["item"]["settings"]
    assert updated_settings["tun_excluded_routes"] == ["10.0.0.0/8", "172.16.0.0/12"]
    assert updated_settings["surge_tun_excluded_routes"] == ["10.0.0.0/8", "172.16.0.0/12"]
    assert updated_settings["shadowrocket_tun_excluded_routes"] == ["10.0.0.0/8", "172.16.0.0/12"]
    assert updated_settings["clash_ipv6"] is False
    assert updated_settings["surge_ipv6"] is False
    assert updated_settings["shadowrocket_ipv6"] is False
    assert updated_settings["clash_mixed_port"] == 7891


def test_profile_capabilities_unsupported_support_kind_is_classified(client) -> None:
    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200

    client_missing = {
        ("mihomo-runtime", "mixed_port", "shadowrocket"),
        ("mihomo-runtime", "allow_lan", "shadowrocket"),
        ("mihomo-runtime", "udp_default", "shadowrocket"),
        ("mihomo-profile-store", "store_selected", "surge"),
        ("mihomo-profile-store", "store_selected", "shadowrocket"),
        ("mihomo-profile-store", "store_fake_ip", "surge"),
        ("mihomo-profile-store", "store_fake_ip", "shadowrocket"),
        ("mihomo-control-api", "external_controller", "shadowrocket"),
        ("mihomo-control-api", "secret", "shadowrocket"),
        ("mihomo-control-api", "external_ui", "surge"),
        ("mihomo-control-api", "external_ui", "shadowrocket"),
        ("mihomo-control-api", "external_ui_name", "surge"),
        ("mihomo-control-api", "external_ui_name", "shadowrocket"),
        ("mihomo-control-api", "external_ui_url", "surge"),
        ("mihomo-control-api", "external_ui_url", "shadowrocket"),
        ("surge-runtime", "loglevel", "shadowrocket"),
        ("surge-runtime", "group_timeout", "clash"),
        ("surge-runtime", "block_quic", "clash"),
        ("surge-runtime", "block_quic", "shadowrocket"),
        ("surge-runtime", "http_api_tls", "clash"),
        ("surge-runtime", "http_api_tls", "shadowrocket"),
        ("surge-runtime", "http_api_web_dashboard", "clash"),
        ("surge-runtime", "http_api_web_dashboard", "shadowrocket"),
        ("skip-proxy", "patterns", "clash"),
        ("url-rewrite", "rules", "clash"),
        ("mitm-hostname", "hostname", "clash"),
        ("mitm-hostname", "skip_cert_verify", "clash"),
        ("mitm-hostname", "skip_cert_verify", "shadowrocket"),
        ("mitm-hostname", "h2", "clash"),
        ("mitm-hostname", "h2", "shadowrocket"),
        ("mitm-hostname", "tcp_connection", "clash"),
        ("mitm-hostname", "tcp_connection", "shadowrocket"),
        ("surge-http-pipeline", "map_local", "clash"),
        ("script", "request", "surge"),
        ("script", "request", "clash"),
        ("script", "response", "surge"),
        ("script", "response", "clash"),
    }

    for group in profile_capabilities.json()["groups"]:
        for capability in group["capabilities"]:
            for subfield in capability["subfields"]:
                for client_name, view in subfield["clients"].items():
                    support = view.get("support", {})
                    if support.get("status") != "unsupported":
                        continue

                    expected = (
                        "client_missing"
                        if (capability["id"], subfield["id"], client_name) in client_missing
                        else "mirror_missing"
                    )
                    assert support.get("kind") == expected


def test_profile_capabilities_unsupported_views_all_include_support_kind(client) -> None:
    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200

    for group in profile_capabilities.json()["groups"]:
        for capability in group["capabilities"]:
            for subfield in capability["subfields"]:
                for view in subfield["clients"].values():
                    support = view.get("support", {})
                    if support.get("status") != "unsupported":
                        continue
                    assert support.get("kind") in {"mirror_missing", "client_missing"}


def test_profile_capabilities_views_include_editing_mode(client) -> None:
    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200

    allowed_modes = {"shared", "standalone", "experimental", "adapted", "unavailable"}
    for group in profile_capabilities.json()["groups"]:
        for capability in group["capabilities"]:
            for subfield in capability["subfields"]:
                for view in subfield["clients"].values():
                    assert view.get("editing_mode") in allowed_modes


def test_profile_capabilities_shadowrocket_map_local_is_downgraded_with_intercept_only_diagnostics(client) -> None:
    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200

    map_local = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="surge-http-pipeline",
        subfield_id="map_local",
        client="shadowrocket",
    )

    assert map_local["support"]["status"] == "downgraded"
    assert map_local["support"]["diagnostic_codes"] == [
        "shadowrocket-map-local-intercept-only",
        "shadowrocket-map-local-inline-data-unreliable",
    ]
    assert map_local["editing_mode"] == "standalone"
    assert map_local["key"] == "shadowrocket_map_local"


def test_profile_capabilities_shadowrocket_script_is_supported_and_standalone(client) -> None:
    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200

    request_script = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="script",
        subfield_id="request",
        client="shadowrocket",
    )
    response_script = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="script",
        subfield_id="response",
        client="shadowrocket",
    )

    assert request_script["support"]["status"] == "supported"
    assert request_script["editing_mode"] == "standalone"
    assert request_script["key"] == "shadowrocket_script_request"
    assert response_script["support"]["status"] == "supported"
    assert response_script["editing_mode"] == "standalone"
    assert response_script["key"] == "shadowrocket_script_response"


def test_profile_capabilities_expose_new_surge_native_runtime_and_mitm_fields(client) -> None:
    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200

    block_quic = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="surge-runtime",
        subfield_id="block_quic",
        client="surge",
    )
    assert block_quic["support"]["status"] == "supported"
    assert block_quic["editing_mode"] == "shared"
    assert block_quic["key"] == "surge_block_quic"

    http_api_tls = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="surge-runtime",
        subfield_id="http_api_tls",
        client="surge",
    )
    assert http_api_tls["support"]["status"] == "supported"
    assert http_api_tls["key"] == "surge_http_api_tls"

    mitm_h2 = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="mitm-hostname",
        subfield_id="h2",
        client="surge",
    )
    assert mitm_h2["support"]["status"] == "supported"
    assert mitm_h2["key"] == "surge_mitm_h2"
    assert mitm_h2.get("syntax_hints")

    mitm_tcp = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="mitm-hostname",
        subfield_id="tcp_connection",
        client="surge",
    )
    assert mitm_tcp["support"]["status"] == "supported"
    assert mitm_tcp["key"] == "surge_mitm_tcp_connection"


def test_profile_capabilities_skip_proxy_clash_is_adapted_mode(client) -> None:
    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200

    skip_proxy_clash = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="skip-proxy",
        subfield_id="patterns",
        client="clash",
    )

    assert skip_proxy_clash["editing_mode"] == "adapted"
    assert skip_proxy_clash.get("adapted_hint")
    assert skip_proxy_clash.get("adapted_targets")
    assert len(skip_proxy_clash["adapted_targets"]) == 2


def test_profile_capabilities_shadowrocket_skip_proxy_is_supported_from_real_device_validation(client) -> None:
    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200

    sr_skip_proxy = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="skip-proxy",
        subfield_id="patterns",
        client="shadowrocket",
    )

    assert sr_skip_proxy["support"]["status"] == "supported"
    assert sr_skip_proxy["support"]["diagnostic_codes"] == []
    assert sr_skip_proxy["editing_mode"] == "shared"
    assert "用户实机" in sr_skip_proxy["support"]["reason_i18n"]["zh"]


def test_preview_skip_proxy_decomposition_endpoint(client) -> None:
    response = client.post(
        "/api/profile-capabilities/preview-decomposition",
        json={"patterns": ["example.com", "10.0.0.0/8", "*.local"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True

    surge = data["clients"]["surge"]
    assert "example.com" in surge["value"]
    assert "10.0.0.0/8" not in surge["value"]

    clash = data["clients"]["clash"]
    sections = {s["section"]: s["entries"] for s in clash["sections"]}
    assert "+.example.com" in sections["dns.fake-ip-filter"]
    assert "+.local" in sections["dns.fake-ip-filter"]
    assert "DOMAIN-SUFFIX,example.com,DIRECT" in sections["rules"]
    assert "DOMAIN-SUFFIX,local,DIRECT" in sections["rules"]
    assert data["excluded_routes"]["entries"] == ["10.0.0.0/8"]

    shadowrocket = data["clients"]["shadowrocket"]
    assert "example.com" in shadowrocket["value"]
    assert "10.0.0.0/8" not in shadowrocket["value"]


def test_preview_skip_proxy_decomposition_empty_patterns(client) -> None:
    response = client.post(
        "/api/profile-capabilities/preview-decomposition",
        json={"patterns": []},
    )
    assert response.status_code == 200
    data = response.json()
    clash = data["clients"]["clash"]
    for s in clash["sections"]:
        assert s["entries"] == []


def test_profile_capabilities_syntax_hints_present_on_experimental_fields(client) -> None:
    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200

    sr_skip_proxy = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="skip-proxy",
        subfield_id="patterns",
        client="shadowrocket",
    )
    assert sr_skip_proxy.get("syntax_hints")
    assert len(sr_skip_proxy["syntax_hints"]) > 0
    assert sr_skip_proxy["syntax_hints"][0].get("body")


def test_general_profile_shared_mirror_and_native_override_fields_are_stable(client) -> None:
    assert client.get("/api/general-profile").status_code == 200

    native_override_profile = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {"surge_loglevel": "verbose"},
        },
    )
    assert native_override_profile.status_code == 200
    native_override_settings = native_override_profile.json()["item"]["settings"]
    assert native_override_settings["surge_loglevel"] == "verbose"

    updated_from_capabilities = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "capabilities": {
                "excluded-routes": {
                    "routes": ["10.0.0.0/8", "172.16.0.0/12"],
                },
                "ipv6-policy": {
                    "enabled": False,
                },
                "mihomo-runtime": {
                    "mixed_port": 7891,
                },
            },
        },
    )
    assert updated_from_capabilities.status_code == 200
    updated_settings = updated_from_capabilities.json()["item"]["settings"]
    assert updated_settings["tun_excluded_routes"] == ["10.0.0.0/8", "172.16.0.0/12"]
    assert updated_settings["surge_tun_excluded_routes"] == ["10.0.0.0/8", "172.16.0.0/12"]
    assert updated_settings["shadowrocket_tun_excluded_routes"] == ["10.0.0.0/8", "172.16.0.0/12"]
    assert updated_settings["clash_ipv6"] is False
    assert updated_settings["surge_ipv6"] is False
    assert updated_settings["shadowrocket_ipv6"] is False
    assert updated_settings["clash_mixed_port"] == 7891
    assert updated_settings["surge_loglevel"] == "verbose"


def test_general_profile_settings_can_persist_standalone_and_experimental_profile_fields(client) -> None:
    response = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {
                "surge_http_api": "127.0.0.1:6170",
                "surge_http_api_secret": "surge-secret-01",
                "surge_http_api_tls": True,
                "surge_http_api_web_dashboard": True,
                "surge_block_quic": "all-proxy",
                "surge_mitm_h2": True,
                "surge_mitm_tcp_connection": True,
                "shadowrocket_map_local": [
                    '^https?://example.com/mock data-type=text data="ok" status-code=200'
                ],
                "shadowrocket_script_request": [
                    "type=http-request,pattern=^https://example.com/api,script-path=https://example.com/request.js"
                ],
                "shadowrocket_script_response": [
                    "type=http-response,pattern=^https://example.com/api,requires-body=1,script-path=https://example.com/response.js"
                ],
                "shadowrocket_skip_proxy": ["localhost", "192.168.0.0/16"],
            },
        },
    )

    assert response.status_code == 200
    settings = response.json()["item"]["settings"]
    assert settings["surge_http_api"] == "127.0.0.1:6170"
    assert settings["surge_http_api_secret"] == "surge-secret-01"
    assert settings["surge_http_api_tls"] is True
    assert settings["surge_http_api_web_dashboard"] is True
    assert settings["surge_block_quic"] == "all-proxy"
    assert settings["surge_mitm_h2"] is True
    assert settings["surge_mitm_tcp_connection"] is True
    assert settings["shadowrocket_map_local"] == [
        '^https?://example.com/mock data-type=text data="ok" status-code=200'
    ]
    assert settings["shadowrocket_script_request"] == [
        "type=http-request,pattern=^https://example.com/api,script-path=https://example.com/request.js"
    ]
    assert settings["shadowrocket_script_response"] == [
        "type=http-response,pattern=^https://example.com/api,requires-body=1,script-path=https://example.com/response.js"
    ]
    assert settings["surge_skip_proxy"] == ["localhost"]
    assert settings["shadowrocket_skip_proxy"] == ["localhost"]
    assert settings["tun_excluded_routes"] == ["6.6.6.6/32", "2000::6666/128", "192.168.0.0/16"]
    assert settings["surge_tun_excluded_routes"] == ["6.6.6.6/32", "2000::6666/128", "192.168.0.0/16"]
    assert settings["shadowrocket_tun_excluded_routes"] == ["6.6.6.6/32", "2000::6666/128", "192.168.0.0/16"]


def test_profile_editor_schema_exposes_capability_cards_and_special_families(client) -> None:
    response = client.get("/api/profile-editor-schema")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["groups"]
    assert payload["families"]
    assert payload["cards"]
    assert payload["default_mode"]["skip-proxy"] == "shared"
    assert "runtime-log-level" not in payload["default_mode"]
    assert all(family["id"] != "runtime-log-level" for family in payload["families"])
    assert all(card["family_id"] != "runtime-log-level" for card in payload["cards"])

    skip_proxy_cards = [card for card in payload["cards"] if card["family_id"] == "skip-proxy"]
    assert any(card["id"] == "skip-proxy:shared" for card in skip_proxy_cards)
    assert any(card["id"] == "skip-proxy:mihomo" for card in skip_proxy_cards)
    shared_skip_proxy = next(card for card in skip_proxy_cards if card["id"] == "skip-proxy:shared")
    assert {field["key"] for field in shared_skip_proxy["input_schema"]} == {"surge_skip_proxy"}
    mihomo_projection = next(card for card in skip_proxy_cards if card["id"] == "skip-proxy:mihomo")
    assert mihomo_projection["input_schema"] == []

    rewrite_cards = [card for card in payload["cards"] if card["family_id"] == "url-rewrite"]
    mihomo_card = next(card for card in rewrite_cards if card["client"] == "clash")
    assert mihomo_card["mode_kind"] == "unsupported"
    assert mihomo_card["input_schema"] == []
    shadowrocket_rewrite = next(card for card in rewrite_cards if card["client"] == "shadowrocket")
    assert shadowrocket_rewrite["status_badge"] == "stable"
    assert shadowrocket_rewrite["mode_kind"] == "client_native"

    map_local_cards = [card for card in payload["cards"] if card["family_id"] == "map-local"]
    shadowrocket_map_local = next(card for card in map_local_cards if card["client"] == "shadowrocket")
    assert shadowrocket_map_local["status_badge"] == "limited"
    assert shadowrocket_map_local["mode_kind"] == "client_native"
    assert "Prefer Script" in shadowrocket_map_local["description"]
    assert any(
        section["kind"] == "recommendation" and "switch to Shadowrocket Script" in section["body"]
        for section in shadowrocket_map_local["detail_sections"]
    )
    assert any(section["status"] == "limited" for section in shadowrocket_map_local["detail_sections"])

    script_cards = [card for card in payload["cards"] if card["family_id"] == "script"]
    assert any(card["id"] == "script:shadowrocket" for card in script_cards)
    script_shadowrocket = next(card for card in script_cards if card["id"] == "script:shadowrocket")
    assert script_shadowrocket["status_badge"] == "stable"
    assert "primary path" in script_shadowrocket["description"]
    assert {field["key"] for field in script_shadowrocket["input_schema"]} == {
        "shadowrocket_script_request",
        "shadowrocket_script_response",
    }
    assert any(
        section["kind"] == "recommendation" and "primary Shadowrocket HTTP pipeline tool" in section["body"]
        for section in script_shadowrocket["detail_sections"]
    )

    surge_runtime_card = next(card for card in payload["cards"] if card["id"] == "surge-runtime-native:surge")
    assert {field["key"] for field in surge_runtime_card["input_schema"]} >= {
        "surge_loglevel",
        "surge_block_quic",
        "surge_http_api_tls",
        "surge_http_api_web_dashboard",
    }
    surge_loglevel_field = next(field for field in surge_runtime_card["input_schema"] if field["key"] == "surge_loglevel")
    assert [item["value"] for item in surge_loglevel_field["options"]] == ["notify", "warning", "info", "verbose"]

    surge_mitm_card = next(card for card in payload["cards"] if card["id"] == "mitm:surge")
    assert {field["key"] for field in surge_mitm_card["input_schema"]} >= {
        "surge_mitm_h2",
        "surge_mitm_tcp_connection",
    }
    shadowrocket_mitm_card = next(card for card in payload["cards"] if card["id"] == "mitm:shadowrocket")
    assert shadowrocket_mitm_card["status_badge"] == "stable"
    assert shadowrocket_mitm_card["mode_kind"] == "client_native"
    assert "port limits" in shadowrocket_mitm_card["description"]

    real_host_cards = [card for card in payload["cards"] if card["family_id"] == "real-host-dns"]
    assert any(card["id"] == "real-host-dns:surge" for card in real_host_cards)
    assert any(card["id"] == "real-host-dns:shadowrocket" for card in real_host_cards)
    assert any(card["id"] == "real-host-dns:mihomo" for card in real_host_cards)
    shadowrocket_real_host = next(card for card in real_host_cards if card["id"] == "real-host-dns:shadowrocket")
    assert shadowrocket_real_host["status_badge"] == "limited"
    assert shadowrocket_real_host["mode_kind"] == "client_native"
    assert "skip-proxy" in shadowrocket_real_host["description"]
    mihomo_real_host = next(card for card in real_host_cards if card["id"] == "real-host-dns:mihomo")
    assert mihomo_real_host["status_badge"] == "generated"
    assert mihomo_real_host["mode_kind"] == "client_native"
    assert mihomo_real_host["input_schema"][0]["key"] == "clash_fake_ip_filter"

    host_record_cards = [card for card in payload["cards"] if card["family_id"] == "host-records"]
    assert any(card["id"] == "host-records:surge" for card in host_record_cards)
    assert any(card["id"] == "host-records:shadowrocket" for card in host_record_cards)
    assert any(card["id"] == "host-records:mihomo" for card in host_record_cards)
    surge_host_records = next(card for card in host_record_cards if card["id"] == "host-records:surge")
    assert surge_host_records["input_schema"][0]["key"] == "surge_host_records"
    assert surge_host_records["input_schema"][0]["type"] == "dict"
    assert "高级兜底" in surge_host_records["description_i18n"]["zh"]
    assert "fallback" in surge_host_records["description"].lower()
    shadowrocket_host_records = next(card for card in host_record_cards if card["id"] == "host-records:shadowrocket")
    assert shadowrocket_host_records["status_badge"] == "stable"
    assert shadowrocket_host_records["mode_kind"] == "client_native"
    assert "basic hostname -> IP mapping" in shadowrocket_host_records["description"]
    mihomo_host_records = next(card for card in host_record_cards if card["id"] == "host-records:mihomo")
    assert mihomo_host_records["input_schema"][0]["key"] == "clash_host_records"
    assert "redir-host" in mihomo_host_records["detail_sections"][1]["body"]

    mihomo_dns_behavior = next(card for card in payload["cards"] if card["id"] == "mihomo-dns-behavior:clash")
    assert mihomo_dns_behavior["client"] == "clash"
    assert mihomo_dns_behavior["status_badge"] == "stable"
    assert any(field["key"] == "clash_dns_enhanced_mode" for field in mihomo_dns_behavior["input_schema"])
    assert any(field["key"] == "clash_dns_use_hosts" for field in mihomo_dns_behavior["input_schema"])
    assert any(field["key"] == "clash_tun_dns_hijack" for field in mihomo_dns_behavior["input_schema"])
    assert any(field["key"] == "clash_sniffer_force_dns_mapping" for field in mihomo_dns_behavior["input_schema"])

    mihomo_runtime_card = next(card for card in payload["cards"] if card["id"] == "mihomo-runtime-native:clash")
    assert {field["key"] for field in mihomo_runtime_card["input_schema"]} >= {
        "clash_log_level",
        "clash_mixed_port",
        "clash_allow_lan",
        "clash_udp_default_enabled",
    }
    clash_loglevel_field = next(field for field in mihomo_runtime_card["input_schema"] if field["key"] == "clash_log_level")
    assert [item["value"] for item in clash_loglevel_field["options"]] == ["silent", "error", "warning", "info", "debug"]

    mihomo_dns_upstreams = next(card for card in payload["cards"] if card["id"] == "mihomo-dns-upstreams:clash")
    assert mihomo_dns_upstreams["client"] == "clash"
    assert mihomo_dns_upstreams["status_badge"] == "stable"
    assert any(field["key"] == "clash_dns_default_nameserver" for field in mihomo_dns_upstreams["input_schema"])
    assert any(field["key"] == "clash_dns_direct_nameserver" for field in mihomo_dns_upstreams["input_schema"])


def test_general_profile_editor_state_round_trips_and_cleans_non_active_family_fields(client) -> None:
    response = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {
                "surge_skip_proxy": ["example.com"],
                "shadowrocket_skip_proxy": ["localhost"],
                "clash_fake_ip_filter": ["+.legacy.test"],
                "tun_excluded_routes": ["10.0.0.0/8"],
                "surge_url_rewrite": ["^https://a reject"],
            },
            "editor_state": {
                "families": {
                    "skip-proxy": "mihomo_split",
                    "url-rewrite": "surge_native",
                },
                "active_client": {
                    "skip-proxy": "clash",
                    "url-rewrite": "surge",
                },
                "legacy": False,
            },
        },
    )
    assert response.status_code == 200
    item = response.json()["item"]
    assert item["editor_state"]["legacy"] is False
    settings = item["settings"]
    assert settings["surge_skip_proxy"] == ["example.com", "localhost"]
    assert settings["shadowrocket_skip_proxy"] == ["example.com", "localhost"]
    assert settings["clash_fake_ip_filter"] == ["+.legacy.test"]
    assert settings["tun_excluded_routes"] == ["10.0.0.0/8", "6.6.6.6/32", "2000::6666/128"]
    assert settings["surge_url_rewrite"] == ["^https://a reject"]


def test_general_profile_editor_state_keeps_real_host_dns_values_available_across_clients(client) -> None:
    response = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {
                "surge_always_real_ip": ["*.surge.example"],
                "shadowrocket_always_real_ip": ["*.shadowrocket.example"],
                "clash_fake_ip_filter": ["+.mihomo.example"],
            },
            "editor_state": {"legacy": False},
        },
    )
    assert response.status_code == 200
    settings = response.json()["item"]["settings"]
    assert settings["surge_always_real_ip"] == ["*.surge.example"]
    assert settings["shadowrocket_always_real_ip"] == ["*.shadowrocket.example"]
    assert settings["clash_fake_ip_filter"] == ["+.mihomo.example"]


def test_general_profile_editor_state_keeps_host_records_values_available_across_clients(client) -> None:
    response = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {
                "surge_host_records": {"subhub.devbox.heiyu.space": "192.168.0.108"},
                "shadowrocket_host_records": {"subhub.prodbox.heiyu.space": "192.168.0.109"},
                "clash_host_records": {"subhub.devbox.heiyu.space": "192.168.0.108"},
            },
            "editor_state": {"legacy": False},
        },
    )
    assert response.status_code == 200
    settings = response.json()["item"]["settings"]
    assert settings["surge_host_records"] == {
        "subhub.devbox.heiyu.space": "192.168.0.108",
    }
    assert settings["shadowrocket_host_records"] == {
        "subhub.prodbox.heiyu.space": "192.168.0.109",
    }
    assert settings["clash_host_records"] == {
        "subhub.devbox.heiyu.space": "192.168.0.108",
    }


def test_general_profile_accepts_legacy_surge_host_alias_and_normalizes_to_host_records(client) -> None:
    response = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {
                "surge_host": {"subhub.devbox.heiyu.space": "192.168.0.108"},
            },
            "editor_state": {"legacy": False},
        },
    )
    assert response.status_code == 200
    settings = response.json()["item"]["settings"]
    assert settings["surge_host_records"] == {
        "subhub.devbox.heiyu.space": "192.168.0.108",
    }


def test_devices_and_surge_subscription_prefer_lazycat_ingress_when_base_url_is_private(client) -> None:
    services = client.app.state.services
    services.settings.app_base_url = "http://192.168.0.108:8080"
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="sub-ingress",
            device_key="mac",
            device_name="Mac",
            token="tok1",
            enabled=True,
        )
    )

    response = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {
                "surge_host_records": {
                    "subhub.devbox.heiyu.space": "fd00:db8::108",
                },
            },
            "editor_state": {"legacy": False},
        },
    )
    assert response.status_code == 200

    surge_base = resolve_preferred_surge_base_url(
        services.settings.app_base_url,
        response.json()["item"]["settings"],
    )
    links = build_device_import_links_for_scenario(
        services.settings.app_base_url,
        "Mac",
        "tok1",
        DEFAULT_SCENARIO_SLUG,
        surge_base_url=surge_base,
    )
    assert links["clash_url"].startswith("http://192.168.0.108:8080/")
    assert links["surge_url"].startswith("https://subhub.devbox.heiyu.space/")
    assert "https%3A%2F%2Fsubhub.devbox.heiyu.space%2Fsub%2Fdevice%2F" in links["surge_scheme"]

    surge = client.get(_scenario_sub_path("tok1", "surge.conf"))
    assert surge.status_code == 200
    assert surge.headers["x-subscription-base-url"] == "https://subhub.devbox.heiyu.space"
    assert surge.headers["x-surge-managed-url"].startswith(
        "https://subhub.devbox.heiyu.space/sub/device/"
    )
    assert "#!MANAGED-CONFIG https://subhub.devbox.heiyu.space/sub/device/" in surge.text
    assert "/default/surge.conf" in surge.text


def test_general_profile_reset_editor_state_clears_settings_and_marks_non_legacy(client) -> None:
    client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {"surge_skip_proxy": ["example.com"]},
            "editor_state": {
                "families": {"skip-proxy": "surge_native"},
                "active_client": {"skip-proxy": "surge"},
                "legacy": False,
            },
        },
    )
    response = client.post("/api/general-profile/reset-editor-state")
    assert response.status_code == 200
    item = response.json()["item"]
    assert item["legacy"] is False
    assert item["editor_state"]["legacy"] is False
    assert item["settings"]["surge_skip_proxy"] == []
    assert item["settings"]["shadowrocket_skip_proxy"] == []


def test_imported_scenarios_and_templates_are_legacy_until_reset(client) -> None:
    created_profile = client.post(
        "/api/general-profiles",
        json={"name": "Legacy Template"},
    )
    assert created_profile.status_code == 200
    assert created_profile.json()["item"]["legacy"] is True

    created_scenario = client.post(
        "/api/scenarios",
        json={
            "slug": "legacy-scene",
            "name": "Legacy Scenario",
            "settings": {"surge_skip_proxy": ["legacy.example.com"]},
        },
    )
    assert created_scenario.status_code == 200
    assert created_scenario.json()["item"]["legacy"] is True

    reset_scenario = client.post(
        f"/api/scenarios/{created_scenario.json()['item']['id']}/reset-editor-state"
    )
    assert reset_scenario.status_code == 200
    assert reset_scenario.json()["item"]["legacy"] is False


def test_general_profile_settings_reject_invalid_log_level_enum_values(client) -> None:
    response = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "settings": {
                "surge_loglevel": "trace",
            },
        },
    )
    assert response.status_code == 400
    assert "surge_loglevel" in response.json()["detail"]
    for option in ("notify", "warning", "info", "verbose"):
        assert option in response.json()["detail"]


def test_general_profile_capabilities_reject_invalid_log_level_enum_values(client) -> None:
    response = client.put(
        "/api/general-profile",
        json={
            "name": "LazyCat Default",
            "capabilities": {
                "surge-runtime": {
                    "loglevel": "trace",
                },
            },
        },
    )
    assert response.status_code == 400
    assert "surge_loglevel" in response.json()["detail"]
    assert "trace" in response.json()["detail"]


def test_general_profile_keeps_unknown_historical_log_level_readable(client) -> None:
    services = client.app.state.services
    current_profile = services.repo.get_default_general_profile()
    assert current_profile is not None
    services.repo.save_general_profile(
        GeneralProfile(
            id=current_profile.id,
            name=current_profile.name,
            settings={**current_profile.settings, "surge_loglevel": "trace"},
            is_system_default=True,
        )
    )

    response = client.get("/api/general-profile")
    assert response.status_code == 200
    assert response.json()["item"]["settings"]["surge_loglevel"] == "trace"
    assert response.json()["item"]["capabilities"]["surge-runtime"]["loglevel"] == "trace"


def test_pools_endpoint_returns_200_with_gorelay_active_snapshot(client) -> None:
    services = client.app.state.services
    services.repo.save_gorelay_account(
        GoRelayAccount(
            id="acc-a",
            name="主账号",
            login_url="https://relay.example.com",
            enabled=True,
        )
    )
    services.repo.save_gorelay_account_snapshot(
        GoRelayAccountSnapshotPayload(
            account=GoRelayAccountSnapshot(
                account_id="acc-a",
                snapshot_id="snap-a",
                created_at="2026-03-09T00:00:00Z",
                node_count=2,
                device_count=1,
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
            },
            device_names={"mac": "Mac"},
            pending_bindings=[],
            source_status={},
        )
    )
    services.repo.save_gorelay_active_snapshot_id("acc-a", "snap-a")
    with services.repo._lock:
        services.repo._conn.execute(
            """
            INSERT OR REPLACE INTO gorelay_node_cache (source_id, device_key, nodes_json, device_name, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("acc-bad", "bad", "{invalid-json", "Bad", "2026-03-09T00:00:00Z"),
        )
        services.repo._conn.commit()

    response = client.get("/api/pools")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 6
    by_id = {item["id"]: item for item in items}
    assert by_id["hq_premium"]["node_count"] == 1
    assert by_id["chain_home"]["node_count"] == 0
    assert by_id["direct"]["pseudo"] is True


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


def test_gorelay_device_strategy_preset_endpoint(client) -> None:
    created = client.post(
        "/api/gorelay/accounts",
        json={
            "name": "家宽A",
            "login_url": "https://relay.example.com",
            "rules_url": "https://relay.example.com/rules",
            "gorelay_username": "u",
            "gorelay_password": "p",
            "selectors_json": "{}",
            "enabled": True,
        },
    )
    assert created.status_code == 200
    account_id = created.json()["item"]["id"]

    updated = client.put(
        f"/api/gorelay/accounts/{account_id}/devices/mac-mini/strategy-preset",
        json={"strategy_preset": "streaming"},
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["strategy_preset"] == "streaming"

    invalid = client.put(
        f"/api/gorelay/accounts/{account_id}/devices/mac-mini/strategy-preset",
        json={"strategy_preset": "unknown"},
    )
    assert invalid.status_code == 400
