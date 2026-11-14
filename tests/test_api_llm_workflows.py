from __future__ import annotations

import io
import json

from app.models import (
    BUSINESS_GROUP_MODE_AD_BLOCK,
    BUSINESS_GROUP_MODE_STANDARD,
    RuleCategory,
    ScenarioProfile,
    ServiceCatalogEntry,
)


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
    assert by_name["OpenAI"]["effective_contract_id"] == "action-reject"
    assert by_name["OpenAI"]["effective_contract_source"] == "ad_block_group"
    assert by_name["Ads"]["catalog_group"] == ""


def test_llm_workflow_grouping_export_inherits_pin_group_metadata_from_default_scenario(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="中等质量", rule_count=8)]
    )
    services.repo.create_pin_group(
        "广告拦截",
        mode=BUSINESS_GROUP_MODE_AD_BLOCK,
        description="继承的广告拦截组",
    )
    services.repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="广告拦截",
            contract_id="medium",
            sort_order=0,
            source="manual",
        )
    )
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work"),
    )

    exported = client.post("/api/llm/workflows/grouping/export?scenario_id=scenario-work", json={})
    assert exported.status_code == 200
    data = exported.json()
    groups = {item["group_name"]: item for item in data["groups"]}
    assert groups["广告拦截"]["mode"] == BUSINESS_GROUP_MODE_AD_BLOCK
    assert groups["广告拦截"]["description"] == "继承的广告拦截组"

    openai = next(item for item in data["items"] if item["name"] == "OpenAI")
    assert openai["catalog_group"] == "广告拦截"
    assert openai["catalog_group_mode"] == BUSINESS_GROUP_MODE_AD_BLOCK
    assert openai["effective_contract_id"] == "action-reject"


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


def test_llm_workflow_routing_apply_respects_scenario_id(client) -> None:
    services = client.app.state.services
    services.repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=8)]
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
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work"),
    )

    exported = client.post("/api/llm/workflows/routing/export?scenario_id=scenario-work", json={})
    assert exported.status_code == 200
    data = exported.json()

    applied = client.post(
        "/api/llm/workflows/routing/apply?scenario_id=scenario-work",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {"OpenAI": "medium"},
        },
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] == 1

    scenario_categories = client.get("/api/rules/categories?scenario_id=scenario-work")
    assert scenario_categories.status_code == 200
    scenario_openai = next(item for item in scenario_categories.json()["items"] if item["name"] == "OpenAI")
    assert scenario_openai["assigned_group"] == "中等质量"
    assert scenario_openai["stored_contract_id"] == "medium"

    default_categories = client.get("/api/rules/categories")
    assert default_categories.status_code == 200
    default_openai = next(item for item in default_categories.json()["items"] if item["name"] == "OpenAI")
    assert default_openai["assigned_group"] == "高质量-高倍率"
    assert default_openai["stored_contract_id"] == "hq_premium"


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


def test_llm_workflow_directness_apply_respects_scenario_id(client) -> None:
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
    services.repo.save_scenario(
        ScenarioProfile(id="scenario-work", slug="work", name="Work"),
    )
    default_before = client.get("/api/rules/categories")
    assert default_before.status_code == 200
    default_before_12306 = next(item for item in default_before.json()["items"] if item["name"] == "12306")

    exported = client.post("/api/llm/workflows/directness/export?scenario_id=scenario-work", json={})
    assert exported.status_code == 200
    data = exported.json()

    applied = client.post(
        "/api/llm/workflows/directness/apply?scenario_id=scenario-work",
        json={
            "snapshot_fingerprint": data["snapshot_fingerprint"],
            "result": {
                "12306": {"decision": "PROXY", "confidence": "high", "reason": "工作场景走代理"}
            },
        },
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] == 1

    scenario_categories = client.get("/api/rules/categories?scenario_id=scenario-work")
    assert scenario_categories.status_code == 200
    scenario_12306 = next(item for item in scenario_categories.json()["items"] if item["name"] == "12306")
    assert scenario_12306["assigned_group"] == ""
    assert scenario_12306["directness_override"] == "PROXY"
    assert scenario_12306["locked"] is True
    assert scenario_12306["lock_source"] == "manual"

    default_categories = client.get("/api/rules/categories")
    assert default_categories.status_code == 200
    default_12306 = next(item for item in default_categories.json()["items"] if item["name"] == "12306")
    assert default_12306["assigned_group"] == default_before_12306["assigned_group"]
    assert default_12306["directness_override"] == default_before_12306["directness_override"]
    assert default_12306["lock_source"] == default_before_12306["lock_source"]

    assert services.repo.list_rule_category_directness_reviews(status="all") == []


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


def test_log_routing_workflow_uses_default_scenario_contract_rename(client) -> None:
    renamed = client.put(
        "/api/contracts/medium",
        json={"display_name": "默认中转"},
    )
    assert renamed.status_code == 200

    created = client.post("/api/llm/log-routing/sessions")
    assert created.status_code == 200
    session_id = created.json()["item"]["session_id"]

    exported = client.post(
        f"/api/llm/log-routing/sessions/{session_id}/export",
        json={"intent_override": "", "sample_evidence_limit": 1},
    )
    assert exported.status_code == 200
    medium = next(item for item in exported.json()["available_routes"] if item["id"] == "medium")
    assert medium["display_name"] == "默认中转"


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
                        "contract_id": "not-real",
                    }
                ],
            },
        },
    )
    assert bad_route.status_code == 400
    assert "unknown route contract" in bad_route.json()["detail"]
