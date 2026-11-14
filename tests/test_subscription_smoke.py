from __future__ import annotations

import yaml

from app.models import (
    NodeRecord,
    QUALITY_CHAIN_HOME,
    QUALITY_HIGH_PREMIUM,
    QUALITY_HIGH_STANDARD,
    QUALITY_MEDIUM,
)
from app.services.export_artifacts import attach_clash_bundle_audit
from app.services.subscription_builder import (
    build_clash_export_bundle,
    build_shadowrocket_config,
)
from app.services.subscription_contracts import (
    CLASH_BUNDLE_FILES,
    SHADOWROCKET_MAIN_CONFIG_MODE,
)


def test_shadowrocket_main_config_uses_inline_proxies_and_keeps_chain_proxy() -> None:
    medium = NodeRecord(name="medium", host="c.example.com", port=443, protocol="http", quality_group=QUALITY_MEDIUM)
    nodes = [
        NodeRecord(name="premium", host="a.example.com", port=443, protocol="http", quality_group=QUALITY_HIGH_PREMIUM),
        NodeRecord(name="standard", host="b.example.com", port=443, protocol="http", quality_group=QUALITY_HIGH_STANDARD),
        medium,
        NodeRecord(
            name="链式家宽 | medium -> 家宽1",
            host="e.example.com",
            port=1080,
            protocol="socks5",
            quality_group=QUALITY_CHAIN_HOME,
            raw={"chain_home": True, "chain_front_dedupe_key": medium.dedupe_key()},
        ),
    ]
    rules = [
        "DOMAIN-SUFFIX,openai.com,高质量-高倍率",
        "DOMAIN-SUFFIX,youtube.com,高质量-低倍率",
    ]

    shadowrocket_text, skipped = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf",
    )
    assert skipped == []
    assert SHADOWROCKET_MAIN_CONFIG_MODE == "inline-proxies"
    assert "[Proxy]" in shadowrocket_text
    assert "链式入口·自动 = url-test, 中等质量·自动" in shadowrocket_text
    assert "中等质量·手动 = select" not in shadowrocket_text
    assert "forwarding-proxy=链式入口·自动" in shadowrocket_text


def test_clash_bundle_smoke_has_contract_layout_and_audit_summary() -> None:
    nodes = [
        NodeRecord(
            name="ss-medium",
            host="medium.example.com",
            port=443,
            protocol="ss",
            quality_group=QUALITY_MEDIUM,
            password="p1",
            raw={"cipher": "aes-128-gcm", "password": "p1"},
        ),
        NodeRecord(
            name="anytls-medium",
            host="anytls.example.com",
            port=443,
            protocol="anytls",
            quality_group=QUALITY_MEDIUM,
            password="p2",
            raw={"password": "p2"},
        ),
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,中等质量"]

    bundle = build_clash_export_bundle(
        nodes,
        rules,
        device_name="Smoke Device",
        device_key="smoke-device",
        subscription_token="tok-smoke",
    )
    bundle = attach_clash_bundle_audit(bundle, profile="lazycat", base_url="http://test")

    assert sorted(bundle["files"]) == sorted(CLASH_BUNDLE_FILES)
    clash_payload = yaml.safe_load(bundle["files"]["clash.yaml"])
    medium_provider = yaml.safe_load(bundle["files"]["providers/medium.yaml"])

    assert "render-warnings" not in clash_payload
    assert clash_payload["mixed-port"] == 7890
    assert [proxy["udp"] for proxy in medium_provider["proxies"]] == [True, True]
    assert "render-warnings stripped: yes" in bundle["files"]["AUDIT.md"]
    assert "UDP explicit on supported proxies: yes" in bundle["files"]["AUDIT.md"]
