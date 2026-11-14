from __future__ import annotations

from app.models import (
    ExternalProxyProgramTemplate,
    MacOverlayTemplate,
    NodeRecord,
    ProcessRuleTemplate,
    QUALITY_HIGH_PREMIUM,
    QUALITY_MEDIUM,
)
from app.services.subscription_builder import (
    build_surge_config,
    build_surge_mac_overlay,
    build_surge_profile_artifacts,
)


def _find_line(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(f"missing line starting with {prefix!r}")


def _surge_nodes() -> list[NodeRecord]:
    return [
        NodeRecord(
            name="premium-1",
            host="premium.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_HIGH_PREMIUM,
        ),
        NodeRecord(
            name="medium-1",
            host="medium.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
    ]


def test_surge_managed_overlay_include_output_remains_valid() -> None:
    overlay = MacOverlayTemplate(
        managed_url="https://example.com/sub/device/tok1/surge-mac-overlay.conf?flavor=lazycat",
        include_url="https://example.com/sub/device/tok1/surge.conf?flavor=lazycat",
        process_rules=[
            ProcessRuleTemplate(
                id="pr-1",
                contract_id="hq_premium",
                contract_display_name="高质量-高倍率",
                match_type="PROCESS-NAME",
                value="Claude",
                sort_order=10,
                enabled=True,
            )
        ],
        external_proxy_programs=[
            ExternalProxyProgramTemplate(
                id="ep-1",
                contract_id="hq_premium",
                contract_display_name="高质量-高倍率",
                program_path="/usr/local/bin/ssh-socks",
                args=["--listen", "17890"],
                local_port=17890,
                name="SSH SOCKS",
                enabled=True,
            )
        ],
    )

    rendered = build_surge_mac_overlay(overlay, profile_name="Mac Overlay")

    assert rendered.startswith(
        "#!MANAGED-CONFIG https://example.com/sub/device/tok1/surge-mac-overlay.conf?flavor=lazycat interval=1800 strict=false"
    )
    assert "#!include https://example.com/sub/device/tok1/surge.conf?flavor=lazycat" in rendered
    assert "#!MACOS-ONLY" in rendered
    assert "[Proxy]" in rendered
    assert "SSH SOCKS = external, exec=/usr/local/bin/ssh-socks, args=--listen, 17890, local-port=17890" in rendered
    assert "[Rule]" in rendered
    assert "PROCESS-NAME,Claude,高质量-高倍率" in rendered


def test_surge_vless_refusal_diagnostics_are_emitted() -> None:
    artifacts = build_surge_profile_artifacts(
        [
            NodeRecord(
                name="vless-1",
                host="vless.example.com",
                port=443,
                protocol="vless",
                quality_group=QUALITY_MEDIUM,
                username="uuid-vless",
                raw={"uuid": "uuid-vless"},
            ),
            NodeRecord(
                name="http-1",
                host="http.example.com",
                port=443,
                protocol="http",
                quality_group=QUALITY_MEDIUM,
            ),
        ],
        ["DOMAIN-SUFFIX,openai.com,中等质量"],
        "https://example.com/sub/device/tok1/surge.conf",
    )

    assert "vless-1" in artifacts.skipped
    assert "http-1 = http, http.example.com, 443" in artifacts.main_conf
    assert any(item.code == "surge-unsupported-node" and item.target == "vless" for item in artifacts.diagnostics)
    assert any(item.code == "surge-vless-refused" and item.target == "vless-1" for item in artifacts.diagnostics)


def test_surge_renders_newly_confirmed_mitm_fields_but_keeps_unconfigured_script_features_out() -> None:
    artifacts = build_surge_profile_artifacts(
        _surge_nodes(),
        ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"],
        "https://example.com/sub/device/tok1/surge.conf?profile=lazycat",
        profile="lazycat",
        profile_settings={
            "surge_script": ["example-script.js"],
            "surge_script_request": ["http-request ^https?://example.com script-path=script.js"],
            "surge_mitm_h2": True,
            "surge_mitm_tcp_connection": True,
            "surge_smart_group": ["Auto = smart-group, premium-1, medium-1"],
        },
    )

    assert "[Script]" not in artifacts.main_conf
    assert "script-path=" not in artifacts.main_conf
    assert "smart-group" not in artifacts.main_conf
    assert "h2 = true" in artifacts.main_conf
    assert "tcp-connection = true" in artifacts.main_conf


def test_surge_general_dns_host_and_mitm_safe_fields_render_from_profile_settings() -> None:
    artifacts = build_surge_profile_artifacts(
        _surge_nodes(),
        ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"],
        "https://example.com/sub/device/tok1/surge.conf?profile=lazycat",
        profile="lazycat",
        profile_settings={
            "surge_dns_server": ["system", "223.5.5.5", "8.8.8.8"],
            "surge_encrypted_dns_server": ["https://1.1.1.1/dns-query"],
            "surge_encrypted_dns_follow_outbound_mode": True,
            "surge_loglevel": "notify",
            "surge_host": {
                "example.com": "1.2.3.4",
                "*.example.net": "server:https://cloudflare-dns.com/dns-query",
                "a.example.org": "alias:b.example.org",
            },
            "surge_mitm_hostname": ["*.example.com", "-*.apple.com"],
            "surge_mitm_skip_server_cert_verify": False,
        },
    )

    assert "dns-server = system, 223.5.5.5, 8.8.8.8" in artifacts.main_conf
    assert "encrypted-dns-server = https://1.1.1.1/dns-query" in artifacts.main_conf
    assert "encrypted-dns-follow-outbound-mode = true" in artifacts.main_conf
    assert "loglevel = notify" in artifacts.main_conf
    assert "[Host]" in artifacts.main_conf
    assert "example.com = 1.2.3.4" in artifacts.main_conf
    assert "*.example.net = server:https://cloudflare-dns.com/dns-query" in artifacts.main_conf
    assert "a.example.org = alias:b.example.org" in artifacts.main_conf
    assert "[MITM]" in artifacts.main_conf
    assert "hostname = *.example.com, -*.apple.com" in artifacts.main_conf
    assert "skip-server-cert-verify = false" in artifacts.main_conf


def test_surge_http_api_fields_render_from_profile_settings() -> None:
    artifacts = build_surge_profile_artifacts(
        _surge_nodes(),
        ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"],
        "https://example.com/sub/device/tok1/surge.conf?profile=lazycat",
        profile="lazycat",
        profile_settings={
            "surge_http_api": "127.0.0.1:6170",
            "surge_http_api_secret": "surge-secret-01",
        },
    )

    assert "http-api = surge-secret-01@127.0.0.1:6170" in artifacts.main_conf
    assert "http-api-tls = false" in artifacts.main_conf
    assert "http-api-web-dashboard = false" in artifacts.main_conf


def test_surge_general_block_quic_and_http_api_companion_fields_render_from_profile_settings() -> None:
    artifacts = build_surge_profile_artifacts(
        _surge_nodes(),
        ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"],
        "https://example.com/sub/device/tok1/surge.conf?profile=lazycat",
        profile="lazycat",
        profile_settings={
            "surge_block_quic": "all-proxy",
            "surge_http_api": "127.0.0.1:6170",
            "surge_http_api_tls": True,
            "surge_http_api_web_dashboard": True,
        },
    )

    assert "block-quic = all-proxy" in artifacts.main_conf
    assert "http-api = 127.0.0.1:6170" in artifacts.main_conf
    assert "http-api-tls = true" in artifacts.main_conf
    assert "http-api-web-dashboard = true" in artifacts.main_conf


def test_surge_proxy_groups_render_explicit_timeout_and_tolerance() -> None:
    surge_text, skipped = build_surge_config(
        _surge_nodes(),
        [
            "DOMAIN-SUFFIX,openai.com,高质量-高倍率",
            "DOMAIN-SUFFIX,example.com,中等质量",
        ],
        "https://example.com/sub/device/tok1/surge.conf",
    )

    assert skipped == []
    auto_line = _find_line(surge_text, "高质量-高倍率·自动 = url-test")
    fallback_line = _find_line(surge_text, "中等质量·自动 = fallback")

    assert "tolerance=" in auto_line
    assert "timeout=" in auto_line
    assert "timeout=" in fallback_line


def test_surge_http_processing_sections_render_from_profile_settings() -> None:
    artifacts = build_surge_profile_artifacts(
        _surge_nodes(),
        ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"],
        "https://example.com/sub/device/tok1/surge.conf?profile=lazycat",
        profile="lazycat",
        profile_settings={
            "surge_header_rewrite": [
                "http-request ^https?://example.com header-add X-Debug 1",
            ],
            "surge_body_rewrite": [
                "http-response ^https?://api.example.com s/foo/bar/g",
            ],
            "surge_jq_body_rewrite": [
                "http-response-jq ^https?://api.example.com .items=[]",
            ],
            "surge_map_local": [
                "^https?://surgetest\\.com/json data-type=text data=\"{}\" status-code=500",
            ],
        },
    )

    assert "[Header Rewrite]" in artifacts.main_conf
    assert "http-request ^https?://example.com header-add X-Debug 1" in artifacts.main_conf
    assert "[Body Rewrite]" in artifacts.main_conf
    assert "http-response ^https?://api.example.com s/foo/bar/g" in artifacts.main_conf
    assert "http-response-jq ^https?://api.example.com .items=[]" in artifacts.main_conf
    assert "[Map Local]" in artifacts.main_conf
    assert '^https?://surgetest\\.com/json data-type=text data="{}" status-code=500' in artifacts.main_conf


def test_surge_artifacts_publish_detached_or_module_metadata_when_available() -> None:
    artifacts = build_surge_profile_artifacts(
        _surge_nodes(),
        ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"],
        "https://example.com/sub/device/tok1/surge.conf?profile=lazycat",
        profile="lazycat",
        profile_settings={
            "surge_header_rewrite": [
                "http-request ^https?://example.com header-add X-Debug 1",
            ]
        },
    )

    assert "managed_url" in artifacts.subscription_metadata
    assert any(
        key in artifacts.subscription_metadata
        for key in ("include_url", "module_url", "sgmodule_url")
    )
