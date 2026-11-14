from __future__ import annotations

import io
import zipfile
from urllib.parse import urlsplit

import pytest
import yaml

from app.models import (
    CustomRule,
    DeviceSubscription,
    GeneralProfile,
    NodeRecord,
    RuleCategory,
    RouteContractView,
    StandardSource,
)
from app.services.subscription_contracts import CLASH_BUNDLE_FILES
from tests.api_helpers import _scenario_sub_path


def _shadowrocket_diagnostics_repo(client, monkeypatch):
    services = client.app.state.services
    repo = services.repo
    repo.save_device_subscription(DeviceSubscription(
        id="diagnostics", device_key="diagnostics", device_name="Diagnostics", token="synthetic-diagnostics",
    ))
    repo.save_standard_source(StandardSource(
        id="diagnostics", name="Diagnostics", clash_url="https://source.example.com/clash.yaml",
        shadowrocket_url="", surge_url="", quality_group="中等质量", enabled=True,
    ))
    repo.save_standard_node_cache("diagnostics", [NodeRecord(
        name="diagnostic-node", host="node.example.com", port=443, protocol="http", quality_group="中等质量",
    )])

    async def refresh(force=False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", refresh)
    return repo


@pytest.mark.parametrize("managed_host", ["testserver", "sub.example.com"])
def test_shadowrocket_rejection_warning_is_shared_by_management_responses(client, monkeypatch, managed_host):
    repo = _shadowrocket_diagnostics_repo(client, monkeypatch)
    if managed_host != "testserver":
        monkeypatch.setattr(client.app.state.services.settings, "app_base_url", f"https://{managed_host}")
    repo.save_custom_rule(CustomRule(
        id="host-reject", rule_type="DOMAIN", value=managed_host, target_group="REJECT",
    ))
    code = "shadowrocket-subscription-host-rejected"
    warnings = []
    for endpoint in ("preview-summary", "render-preview"):
        response = client.get(f"/api/devices/synthetic-diagnostics/{endpoint}?target=shadowrocket")
        assert response.status_code == 200, response.text
        payload = response.json()
        summary = payload["summary"] if endpoint == "preview-summary" else payload
        warning = next(item for item in summary["warnings"] if item["code"] == code)
        assert warning["severity"] == "warning"
        assert warning["target"] == managed_host
        assert "Shadowrocket 连接时无法更新这份配置" in warning["message"]
        assert "改为可用代理或 DIRECT" in warning["message"]
        assert warning in summary["diagnostics"]["downgraded"]
        if endpoint == "render-preview":
            assert summary["blockers"] == [] and summary["blocked"] is False
        warnings.append(warning)
        if endpoint == "render-preview":
            assert f"# SubHub warning [{code}]: {warning['message']}" in payload["content"]
    assert warnings[0] == warnings[1]


@pytest.mark.parametrize("endpoint", ["preview-summary", "render-preview", "preview-content", "subscription"])
def test_shadowrocket_rejection_warning_survives_an_unrelated_blocker(client, monkeypatch, endpoint):
    repo = _shadowrocket_diagnostics_repo(client, monkeypatch)
    repo.save_custom_rule(CustomRule(id="host-reject", rule_type="DOMAIN", value="testserver", target_group="REJECT"))
    repo.save_custom_rule(CustomRule(id="dangling", rule_type="DOMAIN", value="missing.example", target_contract_id="missing"))
    path = (_scenario_sub_path("synthetic-diagnostics", "shadowrocket.conf") if endpoint == "subscription"
            else f"/api/devices/synthetic-diagnostics/{endpoint}?target=shadowrocket")
    response = client.get(path)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "shadowrocket-referenced-missing-contract" in {item["code"] for item in detail["blockers"]}
    warning = next(item for item in detail["warnings"] if item["code"] == "shadowrocket-subscription-host-rejected")
    assert warning["severity"] == "warning"
    assert warning["code"] not in {item["code"] for item in detail["blockers"]}


@pytest.mark.parametrize("action", ["proxy", "reject"])
def test_shadowrocket_management_uses_contract_actions_instead_of_display_names(client, monkeypatch, action):
    repo = _shadowrocket_diagnostics_repo(client, monkeypatch)
    response = client.post("/api/contracts", json={
        "display_name": "REJECT-office", "routing_action": action,
        "primary_pools": ["medium"] if action == "proxy" else [],
    })
    assert response.status_code == 200, response.text
    contract = response.json()["item"]
    assert contract["routing_action"] == action
    if action == "proxy":
        repo.save_scenario_route_contract_view("scenario-default", RouteContractView(
            scenario_id="scenario-default", contract_id=contract["id"], display_name="REJECT-office", is_default=True,
        ))
        response = client.get("/api/devices/synthetic-diagnostics/render-preview?target=shadowrocket")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["policy_ir"]["default_contract_id"] == contract["id"]
        assert "FINAL,兜底代理" in payload["content"]
        assert "DOMAIN,testserver,DIRECT" not in payload["content"]
        assert "shadowrocket-subscription-host-rejected" not in {w["code"] for w in payload["diagnostics"]["downgraded"]}
    repo.save_custom_rule(CustomRule(
        id="host-contract", rule_type="DOMAIN", value="testserver", target_contract_id=contract["id"],
    ))
    response = client.get("/api/devices/synthetic-diagnostics/render-preview?target=shadowrocket")
    assert response.status_code == 200, response.text
    payload = response.json()
    target = "REJECT" if action == "reject" else "REJECT-office"
    assert f"DOMAIN,testserver,{target}" in payload["content"]
    assert ("shadowrocket-subscription-host-rejected" in {w["code"] for w in payload["warnings"]}) == (action == "reject")
    assert ("shadowrocket-subscription-host-rejected" in {w["code"] for w in payload["diagnostics"]["downgraded"]}) == (action == "reject")


@pytest.mark.parametrize("user_agent", ["clash.meta/1.19.32", "clash.meta/v1.19.33", "Go-http-client/1.1", ""])
def test_provider_fetches_ignore_ua_but_enforce_identity_and_signature(client, monkeypatch, user_agent):
    services = client.app.state.services
    services.repo.save_device_subscription(DeviceSubscription(
        id="delivery", device_key="delivery", device_name="Delivery", token="delivery-fake", enabled=True,
    ))
    services.repo.save_standard_source(StandardSource(
        id="delivery", name="Delivery", clash_url="https://source.example.com/clash.yaml",
        shadowrocket_url="", surge_url="", quality_group="中等质量", enabled=True,
    ))
    services.repo.save_standard_node_cache("delivery", [NodeRecord(
        name="delivery-node", host="node.example.com", port=443, protocol="http", quality_group="中等质量",
    )])
    services.repo.save_rule_categories([RuleCategory(name="Delivery", assigned_group="中等质量", rule_count=1)])
    services.repo.save_rule_cache("Delivery", ["DOMAIN,delivery.example.com,PLACEHOLDER"])

    async def refresh(force=False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", refresh)
    headers = {"User-Agent": user_agent}
    main = client.get(_scenario_sub_path("delivery-fake", "clash.yaml"), headers=headers)
    assert main.status_code == 200
    payload = yaml.safe_load(main.text)
    for key, section, expected in (
        ("medium", "proxy-providers", "delivery-node"),
        ("catalog-rules-medium", "rule-providers", "DOMAIN,delivery.example.com\n"),
    ):
        provider = payload[section][key]
        assert provider["proxy"] == "DIRECT"
        url = provider["url"]
        response = client.get(url, headers=headers)
        assert response.status_code == 200 and expected in response.text
        invalid_sig = client.get(url.replace("sig=", "sig=invalid", 1), headers=headers)
        assert invalid_sig.status_code == 403
        public_id = urlsplit(url).path.split("/")[3]
        unknown_owner = client.get(url.replace(f"/{public_id}/", "/unknown-token/"), headers=headers)
        assert unknown_owner.status_code == 403


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


def test_preview_endpoints_require_explicit_target(client) -> None:
    summary = client.get("/api/devices/tok-missing/preview-summary")
    content = client.get("/api/devices/tok-missing/preview-content")
    render = client.get("/api/devices/tok-missing/render-preview")

    assert summary.status_code == 422
    assert content.status_code == 422
    assert render.status_code == 422


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
    assert "shadowrocket-vless-extension-pending-validation" not in pending_codes
    assert any(item["code"] == "shadowrocket-inline-unsupported" for item in shadowrocket_diags["refused"])


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
    portal = client.portal
    assert portal is not None
    portal.call(client.app.state.services.hub_service.refresh)
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


def _save_blocked_intent_device(client, monkeypatch):
    """Store a device whose only category points at a contract with no nodes."""
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id="d-intent-blocked",
            device_key="intent-blocked",
            device_name="Intent Blocked",
            token="tok-intent-blocked",
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id="s-intent-blocked",
            name="Synthetic Blocked",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/sr.conf",
            surge_url="https://example.com/surge.conf",
            quality_group="高质量-高倍率",
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(
        "s-intent-blocked",
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
    # The category points at a contract whose pool has no nodes: every client blocks.
    services.repo.save_rule_categories(
        [RuleCategory(name="Streaming", assigned_group="高质量-低倍率", rule_count=1)]
    )
    services.repo.save_rule_cache("Streaming", ["DOMAIN-SUFFIX,youtube.com,PLACEHOLDER"])

    async def _fake_refresh(force: bool = False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", _fake_refresh)
    return services


def test_blocked_device_409_bodies_omit_intent_diagnostics(client, monkeypatch) -> None:
    # Intent diagnostics are management-only. A blocked build must answer the
    # anonymous device endpoints with the established 409 body, while the
    # authenticated preview of the same blocked build keeps them.
    _save_blocked_intent_device(client, monkeypatch)

    device_paths = [
        _scenario_sub_path("tok-intent-blocked", "clash.yaml"),
        _scenario_sub_path("tok-intent-blocked", "shadowrocket.conf"),
        _scenario_sub_path("tok-intent-blocked", "surge.conf"),
        _scenario_sub_path("tok-intent-blocked", "surge/domain-set/catalog-domains-hq_standard.txt"),
        _scenario_sub_path("tok-intent-blocked", "surge/rule-set/catalog-rules-hq_standard.list"),
    ]
    for path in device_paths:
        response = client.get(path)
        assert response.status_code == 409, path
        detail = response.json()["detail"]
        assert detail["blockers"], path
        assert "intent-" not in response.text, path

    for target in ("clash", "surge", "shadowrocket"):
        preview = client.get(f"/api/devices/tok-intent-blocked/preview-content?target={target}")
        assert preview.status_code == 409, target
        warning_codes = [warning["code"] for warning in preview.json()["detail"]["warnings"]]
        assert any(code.startswith("intent-") for code in warning_codes), target


def test_blocked_bundle_export_409_judges_host_records_with_local_aliases(client, monkeypatch) -> None:
    # The bundle export renders its own blocked detail. It must compare host
    # records with the same local aliases as the bundle, so a record that
    # points at this machine's name is still reported.
    services = _save_blocked_intent_device(client, monkeypatch)
    scenario = services.repo.get_scenario("scenario-default")
    scenario.settings = {
        **scenario.settings,
        "clash_host_records": {"z.heiyu.space": "review-host.example"},
    }
    services.repo.save_scenario(scenario)
    monkeypatch.setattr(
        "app.routes.management.capture_local_host_aliases",
        lambda: {"localhost", "127.0.0.1", "::1", "review-host.example"},
    )

    response = client.get("/api/devices/tok-intent-blocked/export/clash-bundle.zip")

    assert response.status_code == 409, response.text
    host_warnings = [
        warning
        for warning in response.json()["detail"]["warnings"]
        if warning["code"] == "clash-lazycat-host-record-local-target"
    ]
    assert [warning["target"] for warning in host_warnings] == ["clash_host_records.z.heiyu.space"]
    assert "points to the current machine" in host_warnings[0]["message"]


def test_surge_migration_state_diagnostics_follow_hub_needs_rebind_path(client, monkeypatch) -> None:
    # A legacy reference whose group no longer maps to a contract goes through
    # Hub's real loader: Hub marks it needs_rebind and disables it. The intent
    # diagnostics must still report it, because the overlay is unavailable.
    repo = _shadowrocket_diagnostics_repo(client, monkeypatch)
    legacy_process_rule = {
        "id": "legacy-process",
        "contract_id": "",
        "business_group": "No Such Legacy Group",
        "match_type": "PROCESS-NAME-REGEX",
        "value": "^Legacy.*",
        "sort_order": 1,
        "enabled": True,
    }
    legacy_external_program = {
        "id": "legacy-external",
        "contract_id": "",
        "business_group": "No Such Legacy Group",
        "program_path": "/usr/bin/legacy-proxy",
        "args": ["--port", "17899"],
        "local_port": 17899,
        "name": "Legacy External",
        "sort_order": 1,
        "enabled": True,
    }
    repo.set_scenario_process_rules("scenario-default", [legacy_process_rule])
    repo.set_scenario_external_proxy_programs("scenario-default", [legacy_external_program])

    summary = client.get("/api/devices/synthetic-diagnostics/preview-summary?target=surge")
    assert summary.status_code == 200, summary.text
    warnings = summary.json()["summary"]["warnings"]
    warnings_by_code = {warning["code"]: warning for warning in warnings}
    assert "needs-rebind" in warnings_by_code

    process_warning = warnings_by_code["intent-process-migration-state-surge-pending-validation"]
    external_warning = warnings_by_code["intent-external-migration-state-surge-pending-validation"]
    assert process_warning["target"] == "^Legacy.*"
    assert external_warning["target"] == "Legacy External"
    assert "overlay 当前不可用" in process_warning["message"]
    assert "overlay 当前不可用" in external_warning["message"]

    overlay = client.get(_scenario_sub_path("synthetic-diagnostics", "surge-mac-overlay.conf"))
    assert overlay.status_code == 409


def test_named_shadowrocket_delivery_and_clash_profile_title(client, monkeypatch) -> None:
    import base64
    from urllib.parse import urlparse

    services = client.app.state.services
    services.repo.save_device_subscription(DeviceSubscription(
        id="d-client-maintenance", device_key="fake-device", device_name="private-device-name",
        token="fake-client-maintenance", enabled=True,
    ))
    services.repo.save_standard_source(StandardSource(
        id="s-client-maintenance", name="Synthetic", quality_group="中等质量",
        ingest_kind="manual_nodes", manual_nodes_text="synthetic", enabled=True,
    ))
    services.repo.save_standard_node_cache("s-client-maintenance", [NodeRecord(
        name="USA-01", host="node.example.com", port=443, protocol="ss", password="fake-password",
        quality_group="中等质量", source_id="s-client-maintenance", source_type="standard", raw={"cipher":"aes-128-gcm"},
    )])

    async def refresh(force=False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", refresh)
    item = next(item for item in client.get("/api/devices").json()["items"] if item["device_name"] == "private-device-name")
    links = item["links"]
    path = urlparse(links["shadowrocket_url"]).path
    assert path.rsplit("/", 1)[-1].isascii()
    assert "private-device-name" not in path
    named = client.get(path, headers={"X-HC-User-ID":""})
    assert named.status_code == 200
    assert links["shadowrocket_url"] in named.text
    old = client.get(path.rsplit("/", 1)[0] + "/shadowrocket.conf")
    assert old.status_code == 200 and "[Proxy]" in old.text
    # The new filename parameter must not become a new query constraint on old URLs.
    assert client.get(path.rsplit("/", 1)[0] + "/shadowrocket.conf?config_id=ignored").status_code == 200
    assert client.get(path.rsplit("/", 1)[0] + "/shadowrocket-legacy.conf", follow_redirects=False).status_code == 308
    assert client.get(path.rsplit("/", 1)[0] + "/shadowrocket-0000000000000000.conf").status_code == 404
    clash = client.get(urlparse(links["clash_url"]).path)
    assert clash.status_code == 200
    title = clash.headers["profile-title"]
    assert title.startswith("base64:")
    assert "SubHub" in base64.b64decode(title.removeprefix("base64:")).decode()
    assert "private-device-name" not in base64.b64decode(title.removeprefix("base64:")).decode()
    cached = client.get(urlparse(links["clash_url"]).path, headers={"If-None-Match":clash.headers["etag"]})
    assert cached.status_code == 304 and cached.headers["profile-title"] == title


@pytest.mark.parametrize("target", ["clash", "surge", "shadowrocket"])
@pytest.mark.parametrize("endpoint", ["preview-summary", "render-preview"])
def test_intent_dns_and_ip_only_warnings_are_management_only(client, monkeypatch, target, endpoint):
    from types import SimpleNamespace
    from app.models import PolicyRuleEntry, RouteContract
    from app.services.subscription_builder import build_policy_ir

    _shadowrocket_diagnostics_repo(client, monkeypatch)
    node = NodeRecord(name="synthetic",host="node.example.com",port=443,protocol="ss",password="synthetic",quality_group="中等质量",raw={"cipher":"aes-128-gcm"})
    policy = build_policy_ir([node], [], rule_entries=[
        PolicyRuleEntry("medium","IP-CIDR","192.0.2.0/24",category_name="Only IP"),
        PolicyRuleEntry("medium","IP-CIDR6","2001:db8::/32",["no-resolve"],category_name="Only IP"),
    ], contracts=[RouteContract("medium","Proxy",primary_pools=["medium"]),RouteContract("direct-default","Direct",routing_action="direct")], default_contract_id="direct-default")

    async def cached(*args, **kwargs):
        return SimpleNamespace(nodes=[node],policy_ir=policy,revision="fixed-synthetic-revision")

    monkeypatch.setattr(client.app.state.services.hub_service,"get_cached_policy_ir",cached)
    monkeypatch.setattr("app.routes.management.capture_local_host_aliases",lambda:{"localhost","127.0.0.1","::1"})
    response = client.get(f"/api/devices/synthetic-diagnostics/{endpoint}?target={target}")
    assert response.status_code == 200, response.text
    body=response.json()
    summary=body["summary"] if endpoint=="preview-summary" else body
    warnings=summary["warnings"]
    codes={w["code"] for w in warnings}
    assert {"intent-ip-dns-client-default-differs","intent-ip-only-category-direct-fallback"} <= codes
    if target=="shadowrocket":
        assert "intent-shadowrocket-ip-dns-conditional" in codes
    structured=[w for values in summary["diagnostics"].values() for w in values]
    for warning in warnings:
        if warning["code"].startswith("intent-"):
            assert warning in structured
            assert warning["severity"]=="warning"
            assert "请" in warning["message"]
    difference=next(w for w in warnings if w["code"]=="intent-ip-dns-client-default-differs")
    assert "E-R-" not in difference["message"] and "[已确认]" not in difference["message"]
    fallback=next(w for w in warnings if w["code"]=="intent-ip-only-category-direct-fallback")
    assert fallback["target"]=="Only IP" and "兜底直连" in fallback["message"]
    if endpoint=="render-preview":
        assert not body["blocked"] and body["blockers"]==[]
        assert "intent-" not in body["content"]


@pytest.mark.parametrize("target", ["clash", "surge", "shadowrocket"])
def test_intent_setting_limit_warnings_reach_preview_diagnostics(client, monkeypatch, target):
    repo=_shadowrocket_diagnostics_repo(client,monkeypatch)
    scenario=repo.get_scenario("scenario-default")
    scenario.settings={**scenario.settings,"clash_sniffer_enable":True,"shadowrocket_map_local":["^http://example.com/mock data-type=text data=synthetic"],"surge_host_records":{"example.com":"192.0.2.1"}}
    repo.save_scenario(scenario)
    response=client.get(f"/api/devices/synthetic-diagnostics/render-preview?target={target}")
    assert response.status_code==200,response.text
    payload=response.json()
    assert any(w["code"].startswith("intent-") for values in payload["diagnostics"].values() for w in values)
    assert not payload["blocked"] and "intent-" not in payload["content"]


def test_intent_inventory_covers_untyped_pin_group_settings(client):
    from app.routes.management import CreatePinGroupPayload
    from app.services.configuration_intent import intent_registry

    registry={row["id"] for row in intent_registry()["routing"]}
    assert {"PinGroup."+key for key in CreatePinGroupPayload.model_fields} <= registry
    response=client.post("/api/rules/pin-groups",json={"group_name":"Synthetic Inventory","mode":"standard"})
    assert response.status_code==200,response.text
    stored=next(row for row in client.app.state.services.repo.list_pin_groups() if row["group_name"]=="Synthetic Inventory")
    assert {"PinGroup."+key for key in stored} <= registry
