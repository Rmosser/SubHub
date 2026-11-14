from __future__ import annotations

import yaml

import pytest

from app.models import DeviceSubscription, NodeRecord, RuleCategory, StandardSource
from tests.api_helpers import _find_capability_view, _scenario_sub_path


def test_shadowrocket_editor_map_local_description_matches_omitted_output(client):
    response = client.get("/api/profile-editor-schema")
    assert response.status_code == 200
    cards = {card["id"]: card for card in response.json()["cards"]}
    mapping = cards["map-local:shadowrocket"]
    assert "omitted" in mapping["description"]
    assert "不下发" in mapping["description_i18n"]["zh"]
    assert mapping["status_badge"] == "limited"
    assert mapping["input_schema"][0]["key"] == "shadowrocket_map_local"
    for card_id in ("map-local:shadowrocket", "script:shadowrocket"):
        guidance = next(section for section in cards[card_id]["detail_sections"] if section["kind"] == "recommendation")
        assert "omitted from output" in guidance["body"]
        assert "fallback" not in guidance["body"]


@pytest.mark.parametrize("settings", [None, {}])
def test_empty_new_scenario_profile_can_be_edited_without_reset(client, settings) -> None:
    payload = {"slug": "new-scene", "name": "New Scenario"}
    if settings is not None:
        payload["settings"] = settings
    created = client.post("/api/scenarios", json=payload)
    assert created.status_code == 200
    scenario_id = created.json()["item"]["id"]
    assert created.json()["item"]["legacy"] is False

    profile = client.get("/api/general-profile", params={"scenario_id": scenario_id})
    assert profile.status_code == 200
    item = profile.json()["item"]
    assert item["legacy"] is False
    assert item["editor_state"]["legacy"] is False

    updated = client.put(
        "/api/general-profile",
        params={"scenario_id": scenario_id},
        json={"capabilities": {"ipv6-policy": {"enabled": False}}},
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["legacy"] is False
    assert updated.json()["item"]["settings"]["clash_ipv6"] is False
    persisted = client.get("/api/general-profile", params={"scenario_id": scenario_id})
    assert persisted.json()["item"]["settings"]["clash_ipv6"] is False
    assert persisted.json()["item"]["legacy"] is False


def test_new_scenario_with_legacy_settings_keeps_configuration(client) -> None:
    created = client.post(
        "/api/scenarios",
        json={
            "slug": "imported-scene",
            "name": "Imported Scenario",
            "settings": {"surge_skip_proxy": ["legacy.example.com"]},
        },
    )
    assert created.status_code == 200
    item = created.json()["item"]
    assert item["legacy"] is True
    assert item["settings"]["surge_skip_proxy"] == ["legacy.example.com"]
    profile = client.get("/api/general-profile", params={"scenario_id": item["id"]})
    assert profile.status_code == 200
    assert profile.json()["item"]["legacy"] is True
    assert profile.json()["item"]["settings"]["surge_skip_proxy"] == ["legacy.example.com"]


@pytest.mark.parametrize(
    "path", ("/api/general-profile", "/api/profile-capabilities")
)
def test_management_profile_endpoints_require_lazycat_identity(client, path: str) -> None:
    response = client.get(path, headers={"X-HC-User-ID": ""})
    assert response.status_code == 401
    assert response.json() == {"detail": "lazycat login required"}


def test_general_profile_endpoints_expose_capabilities_and_support_updates(client) -> None:
    general_profile = client.get("/api/general-profile")
    assert general_profile.status_code == 200
    assert general_profile.json()["item"]["is_system_default"] is True
    assert "capabilities" in general_profile.json()["item"]

    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200
    assert "clients" not in profile_capabilities.json()
    first_group = profile_capabilities.json()["groups"][0]
    assert first_group["title_i18n"]["zh"]
    assert first_group["title_i18n"]["en"] == first_group["title"]
    assert any(
        capability["id"] == "excluded-routes"
        for group in profile_capabilities.json()["groups"]
        for capability in group["capabilities"]
    )

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


def test_profile_capabilities_views_include_editing_mode_and_support_hints(client) -> None:
    profile_capabilities = client.get("/api/profile-capabilities")
    assert profile_capabilities.status_code == 200

    allowed_modes = {"shared", "standalone", "experimental", "adapted", "unavailable"}
    for group in profile_capabilities.json()["groups"]:
        for capability in group["capabilities"]:
            for subfield in capability["subfields"]:
                for view in subfield["clients"].values():
                    assert view.get("editing_mode") in allowed_modes
                    support = view.get("support", {})
                    if support.get("status") == "unsupported":
                        assert support.get("kind") in {"mirror_missing", "client_missing"}


def test_profile_capability_views_expose_specialized_client_mappings(client) -> None:
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

    request_script = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="script",
        subfield_id="request",
        client="shadowrocket",
    )
    assert request_script["support"]["status"] == "supported"
    assert request_script["editing_mode"] == "standalone"
    assert request_script["key"] == "shadowrocket_script_request"

    skip_proxy_clash = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="skip-proxy",
        subfield_id="patterns",
        client="clash",
    )
    assert skip_proxy_clash["editing_mode"] == "adapted"
    assert len(skip_proxy_clash["adapted_targets"]) == 2

    sr_skip_proxy = _find_capability_view(
        profile_capabilities.json(),
        group_id="surge-routing",
        capability_id="skip-proxy",
        subfield_id="patterns",
        client="shadowrocket",
    )
    assert sr_skip_proxy["support"]["status"] == "supported"
    assert sr_skip_proxy.get("syntax_hints")


def test_preview_skip_proxy_decomposition_endpoints(client) -> None:
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

    empty = client.post(
        "/api/profile-capabilities/preview-decomposition",
        json={"patterns": []},
    )
    assert empty.status_code == 200
    for section in empty.json()["clients"]["clash"]["sections"]:
        assert section["entries"] == []


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
    assert item["clash_dns_enable"] is False
    assert item["clash_mixed_port"] == 17890
    assert item["tun_excluded_routes"] == ["10.0.0.0/8", "198.18.0.0/15", "172.16.0.0/12"]
    assert item["surge_tun_excluded_routes"] == ["10.0.0.0/8", "198.18.0.0/15", "172.16.0.0/12"]
    assert item["shadowrocket_tun_excluded_routes"] == ["10.0.0.0/8", "198.18.0.0/15", "172.16.0.0/12"]

    clash = client.get(_scenario_sub_path("tok1", "clash.yaml"))
    assert clash.status_code == 200
    assert "enable: false" in clash.text
    assert "listen: 0.0.0.0:5353" in clash.text
    assert "enhanced-mode: redir-host" in clash.text
    clash_payload = yaml.safe_load(clash.text)
    assert "render-warnings" not in clash_payload
    preview = client.get("/api/devices/tok1/preview-summary?target=clash")
    assert preview.status_code == 200
    warning_codes = [item["code"] for item in preview.json()["summary"]["warnings"]]
    assert "clash-always-real-ip-pending-validation" in warning_codes

    sr = client.get(_scenario_sub_path("tok1", "shadowrocket.conf"))
    assert sr.status_code == 200
    assert "always-real-ip = *.custom.shadowrocket.test" in sr.text
    assert "tun-excluded-routes = 10.0.0.0/8,198.18.0.0/15,172.16.0.0/12" in sr.text

    surge = client.get(_scenario_sub_path("tok1", "surge.conf"))
    assert surge.status_code == 200
    assert "always-real-ip = *.custom.surge.test" in surge.text
    assert "tun-excluded-routes = 10.0.0.0/8,198.18.0.0/15,172.16.0.0/12" in surge.text


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


@pytest.mark.parametrize("key", ["clash_dns_nameserver", "clash_dns_default_nameserver", "clash_dns_proxy_server_nameserver"])
def test_empty_required_dns_rejected_at_profile_write_boundary(client, key) -> None:
    response = client.put("/api/general-profile", json={"name":"Synthetic", "settings":{key:[]}})
    assert response.status_code == 400
    assert key in response.text
