from __future__ import annotations

import base64

from app.models import DeviceSubscription, NodeRecord, StandardSource, QUALITY_MEDIUM
from app.services.subscription_builder import (
    build_shadowrocket_config,
    build_shadowrocket_nodes_subscription,
    derive_shadowrocket_profile_diagnostics,
)


def _seed_shadowrocket_preview(client, *, token: str, nodes: list[NodeRecord]) -> None:
    services = client.app.state.services
    services.repo.save_device_subscription(
        DeviceSubscription(
            id=f"d-{token}",
            device_key=f"device-{token}",
            device_name=f"Device {token}",
            token=token,
            enabled=True,
        )
    )
    services.repo.save_standard_source(
        StandardSource(
            id=f"s-{token}",
            name=f"Source {token}",
            clash_url="https://example.com/clash.yaml",
            shadowrocket_url="https://example.com/shadowrocket.conf",
            surge_url="https://example.com/surge.conf",
            quality_group=QUALITY_MEDIUM,
            enabled=True,
        )
    )
    services.repo.save_standard_node_cache(f"s-{token}", nodes)


def test_shadowrocket_preview_summary_classifies_pending_validation_without_supported_claims(client) -> None:
    _seed_shadowrocket_preview(
        client,
        token="tok-shadowrocket-capabilities",
        nodes=[
            NodeRecord(
                name="safe-http",
                host="safe.example.com",
                port=443,
                protocol="http",
                quality_group=QUALITY_MEDIUM,
            ),
            NodeRecord(
                name="vless-ext",
                host="vless.example.com",
                port=443,
                protocol="vless",
                quality_group=QUALITY_MEDIUM,
                username="uuid-vless",
                raw={
                    "uuid": "uuid-vless",
                    "flow": "xtls-rprx-vision",
                    "packet_encoding": "packetaddr",
                    "reality_opts": {
                        "public-key": "pub-key",
                        "short-id": "short-id",
                    },
                },
            ),
            NodeRecord(
                name="tuic-v4",
                host="tuic.example.com",
                port=9443,
                protocol="tuic",
                quality_group=QUALITY_MEDIUM,
                raw={
                    "token": "token-v4",
                    "tuic_version": 4,
                },
            ),
        ],
    )

    response = client.get(
        "/api/devices/tok-shadowrocket-capabilities/preview-summary?target=shadowrocket"
    )

    assert response.status_code == 200
    diagnostics = response.json()["summary"]["diagnostics"]
    pending_codes = {item["code"] for item in diagnostics["pending_validation"]}
    assert "shadowrocket-tuic-v4-pending-validation" in pending_codes
    assert "shadowrocket-vless-extension-pending-validation" not in pending_codes
    assert "shadowrocket-inline-unsupported" in {item["code"] for item in diagnostics["refused"]}

    for bucket_name in ("supported", "downgraded", "refused"):
        bucket_codes = {item["code"] for item in diagnostics[bucket_name]}
        assert "shadowrocket-tuic-v4-pending-validation" not in bucket_codes
        assert "shadowrocket-vless-extension-pending-validation" not in bucket_codes


def test_shadowrocket_safe_default_config_omits_advanced_dns_tun_mitm_rewrite_and_script_claims() -> None:
    text, skipped = build_shadowrocket_config(
        [
            NodeRecord(
                name="safe-http",
                host="safe.example.com",
                port=443,
                protocol="http",
                quality_group=QUALITY_MEDIUM,
            )
        ],
        ["DOMAIN-SUFFIX,openai.com,中等质量"],
        "http://test/sub/device/t1/shadowrocket.conf",
    )

    assert skipped == []
    assert "[General]" in text
    assert "ipv6 = true" in text
    assert "[Proxy]" in text
    assert "[Proxy Group]" in text
    assert "[Rule]" in text

    forbidden_tokens = (
        "[Host]",
        "[MITM]",
        "[URL Rewrite]",
        "always-real-ip =",
        "tun-excluded-routes =",
        "skip-proxy =",
        "dns-server =",
        "hijack-dns =",
        "script-path=",
        "type=http-response",
        "script =",
    )
    for token in forbidden_tokens:
        assert token not in text


def test_shadowrocket_always_real_ip_diagnostics_move_to_downgraded_direct_access_scope() -> None:
    diagnostics = derive_shadowrocket_profile_diagnostics(
        {
            "shadowrocket_always_real_ip": ["sr-b.192-168-0-108.sslip.io"],
        }
    )

    always_real_ip = next(
        item for item in diagnostics if item.code == "shadowrocket-always-real-ip-direct-access-validated"
    )
    assert always_real_ip.bucket == "downgraded"
    assert "skip-proxy" in always_real_ip.message


def test_shadowrocket_inline_rejects_extensions_while_node_uri_preserves_them() -> None:
    nodes = [
        NodeRecord(
            name="vless-ext",
            host="vless.example.com",
            port=443,
            protocol="vless",
            quality_group=QUALITY_MEDIUM,
            username="uuid-vless",
            raw={
                "uuid": "uuid-vless",
                "flow": "xtls-rprx-vision",
                "packet_encoding": "packetaddr",
                "reality_opts": {
                    "public-key": "pub-key",
                    "short-id": "short-id",
                },
            },
        ),
        NodeRecord(
            name="tuic-v4",
            host="tuic.example.com",
            port=9443,
            protocol="tuic",
            quality_group=QUALITY_MEDIUM,
            raw={
                "token": "token-v4",
                "tuic_version": 4,
                "reduce_rtt": True,
                "udp_relay_mode": "native",
            },
        ),
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,中等质量"]

    text, skipped = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf",
    )
    encoded_nodes, nodes_skipped = build_shadowrocket_nodes_subscription(nodes)
    decoded_nodes = base64.b64decode(encoded_nodes.encode("ascii")).decode("utf-8")

    assert "tuic-v4" in skipped
    assert "tuic-v4" in nodes_skipped
    assert "vless-ext" in skipped
    assert "shadowrocket-inline-unsupported" in text
    assert "vless://uuid-vless@vless.example.com:443" in decoded_nodes
    assert "tuic://" not in decoded_nodes
    assert "security=reality" in decoded_nodes
    assert "flow=xtls-rprx-vision" in decoded_nodes
    assert "pbk=pub-key" in decoded_nodes
    assert "sid=short-id" in decoded_nodes
    assert "packet-encoding=packetaddr" in decoded_nodes

    forbidden_tokens = (
        "flow=",
        "packet-encoding",
        "packet_encoding",
        "reality",
        "public-key",
        "short-id",
        "token=token-v4",
        "reduce-rtt",
        "udp-relay-mode",
        "xtls-rprx-vision",
    )
    for token in forbidden_tokens:
        assert token not in text


def test_shadowrocket_lazycat_profile_renders_http_pipeline_sections_with_notes() -> None:
    text, skipped = build_shadowrocket_config(
        [
            NodeRecord(
                name="safe-http",
                host="safe.example.com",
                port=443,
                protocol="http",
                quality_group=QUALITY_MEDIUM,
            )
        ],
        ["DOMAIN-SUFFIX,openai.com,中等质量"],
        "http://test/sub/device/t1/shadowrocket.conf?profile=lazycat",
        profile="lazycat",
        profile_settings={
            "shadowrocket_url_rewrite": [
                "^https://example.com/rewrite https://example.com/ok 302",
            ],
            "shadowrocket_map_local": [
                '^https?://example.com/mock data-type=text data="ok" status-code=200',
            ],
            "shadowrocket_mitm_hostname": ["example.com", "*.example.net"],
            "shadowrocket_script_request": [
                "type=http-request,pattern=^https://example.com/api,script-path=https://example.com/request.js",
            ],
            "shadowrocket_script_response": [
                "type=http-response,pattern=^https://example.com/api,requires-body=1,script-path=https://example.com/response.js",
            ],
        },
    )

    assert skipped == []
    assert "Shadowrocket 2.2.93" in text
    assert "full system trust" in text
    assert "[Map Local]" not in text
    assert "shadowrocket-map-local-intercept-only" in text
    assert '^https?://example.com/mock data-type=text data="ok" status-code=200' not in text
    assert "[URL Rewrite]" in text
    assert "[Script]" in text
    assert "type=http-request,pattern=^https://example.com/api,script-path=https://example.com/request.js" in text
    assert "type=http-response,pattern=^https://example.com/api,requires-body=1,script-path=https://example.com/response.js" in text
    assert "[MITM]" in text
    assert "enable = true" in text
    assert "hostname = example.com, *.example.net" in text
