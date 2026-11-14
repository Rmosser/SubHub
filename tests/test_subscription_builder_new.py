from __future__ import annotations

import base64
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

import yaml
import pytest

from app.models import (
    BUSINESS_GROUP_MODE_AD_BLOCK,
    BusinessGroup,
    StandardSource,
    ExternalProxyProgramTemplate,
    PolicyRuleEntry,
    NodeRecord,
    ProcessRuleTemplate,
    QUALITY_BULK,
    QUALITY_CHAIN_HOME,
    QUALITY_GROUPS,
    QUALITY_HIGH_PREMIUM,
    QUALITY_HIGH_STANDARD,
    QUALITY_MEDIUM,
    QUALITY_REJECT,
)
from app.services.subscription_contracts import (
    CLASH_BUNDLE_FILES,
    CLASH_PROVIDER_KEYS,
    SHADOWROCKET_MAIN_CONFIG_MODE,
)
from app.storage.sqlite_repo import _default_route_contracts
from app.config import Settings
from app.services.source_fetcher import SourceFetcher
from app.services.subscription_country_rules import (
    COUNTRY_ALIAS_RULES,
    SOURCE_COUNTRY_RULESETS,
    detect_node_country,
    extract_source_hint,
)
from app.services.subscription_builder import (
    _detect_node_country,
    build_clash_audit_markdown,
    build_clash_blocked_detail,
    build_policy_ir,
    build_clash_config,
    build_clash_profile_artifacts,
    build_clash_export_bundle,
    build_clash_provider_config,
    build_clash_rule_provider_config,
    build_device_import_links,
    derive_shadowrocket_profile_diagnostics,
    derive_protocol_diagnostics,
    build_subscription_display_name,
    build_surge_profile_artifacts,
    build_shadowrocket_config,
    build_shadowrocket_nodes_subscription,
    build_shadowrocket_subscription_name,
    build_surge_config,
)


def _proxy_group_map_from_clash(text: str) -> tuple[list[str], dict[str, dict[str, object]]]:
    payload = yaml.safe_load(text)
    groups = payload["proxy-groups"]
    return [item["name"] for item in groups], {item["name"]: item for item in groups}


def _without_udp_guards(rules: list[str]) -> list[str]:
    # Guard behavior is independently tested by test_proxy_maintenance and local UDP probes.
    return [line for line in rules if not line.endswith(",(NETWORK,UDP)),REJECT") and not line.startswith("NETWORK,UDP,")]


def _find_line(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(f"missing line starting with {prefix!r}")


@pytest.mark.parametrize("protocol", ["vmess", "vless", "trojan"])
def test_native_grpc_preserved_for_mihomo_and_refused_by_other_renderers(protocol) -> None:
    source = StandardSource(id="grpc", name="GRPC", quality_group=QUALITY_MEDIUM)
    original = {
        "name": "GRPC", "type": protocol, "server": "grpc.example", "port": 443,
        "uuid": "uuid", "password": "secret", "network": "grpc", "tls": True,
        "grpc-opts": {"grpc-service-name": "my-service", "grpc-user-agent": "test-agent", "ping-interval": 15},
    }
    parsed = SourceFetcher(Settings.from_env())._parse_clash_payload(yaml.safe_dump({"proxies": [original]}), source)
    assert len(parsed.nodes) == 1
    provider, skipped = build_clash_provider_config(parsed.nodes, "medium")
    assert skipped == []
    proxy = yaml.safe_load(provider)["proxies"][0]
    assert proxy["network"] == "grpc"
    assert proxy["grpc-opts"] == original["grpc-opts"]
    surge, skipped = build_surge_config(parsed.nodes, [], "https://sub.example/surge.conf")
    assert parsed.nodes[0].name in skipped
    assert "grpc.example, 443" not in surge
    diagnostics = derive_protocol_diagnostics(parsed.nodes, skipped, target="surge")
    assert diagnostics[0].bucket == "refused"
    assert diagnostics[0].code == ("surge-vless-refused" if protocol == "vless" else "surge-transport-refused")
    _, skipped = build_shadowrocket_nodes_subscription(parsed.nodes)
    assert parsed.nodes[0].name in skipped


@pytest.mark.parametrize("query, refused", [("security=none", False), ("security=none&packet-encoding=packetaddr", True)])
def test_shadowrocket_plain_tcp_survives_but_packet_encoding_is_explicitly_refused(query, refused) -> None:
    source = StandardSource(id="tcp", name="TCP", quality_group=QUALITY_MEDIUM, ingest_kind="manual_nodes",
                            manual_nodes_text="vless://uuid@tcp.example:443?" + query + "#TCP")
    nodes = SourceFetcher(Settings.from_env()).parse_manual_nodes(source).nodes
    assert len(nodes) == 1
    text, skipped = build_shadowrocket_config(nodes, [], "https://sub.example/shadowrocket.conf")
    diagnostics = derive_protocol_diagnostics(nodes, skipped, target="shadowrocket")
    if refused:
        assert nodes[0].name in skipped
        assert "shadowrocket-inline-unsupported" in text
        assert [(item.code, item.bucket) for item in diagnostics] == [("shadowrocket-inline-unsupported", "refused")]
    else:
        assert skipped == []
        assert "vless, tcp.example, 443" in text
        assert diagnostics == []


@pytest.mark.parametrize("fields", [
    {"network": "ws", "ws-opts": {"path": "/required-path", "headers": {"Host": "front.example"}}},
    {"alpn": ["http/1.1"]},
    {"client-fingerprint": "chrome"},
])
def test_native_trojan_node_uri_refuses_fields_it_cannot_preserve(fields) -> None:
    original = {"name": "Native Trojan", "type": "trojan", "server": "native.example", "port": 443, "password": "secret", **fields}
    source = StandardSource(id="native", name="Native", quality_group=QUALITY_MEDIUM)
    nodes = SourceFetcher(Settings.from_env())._parse_clash_payload(yaml.safe_dump({"proxies": [original]}), source).nodes
    assert len(nodes) == 1
    encoded, skipped = build_shadowrocket_nodes_subscription(nodes)
    assert encoded == ""
    assert skipped == [nodes[0].name]
    inline, skipped = build_shadowrocket_config(nodes, [], "https://sub.example/shadowrocket.conf")
    assert skipped == []
    assert " = trojan," in inline
    if fields.get("network") == "ws":
        assert "obfs-uri=/required-path" in inline
    else:
        assert "shadowrocket-unverified-fields-omitted" in inline
    provider, skipped = build_clash_provider_config(nodes, "medium")
    assert skipped == []
    proxy = yaml.safe_load(provider)["proxies"][0]
    for key, value in fields.items():
        assert proxy[key] == value


@pytest.mark.parametrize("query", ["type=ws&security=tls&path=%2Frequired&host=front.example&alpn=http%2F1.1&fp=chrome", "fp=chrome"])
def test_trojan_source_uri_preserves_extensions_and_plain_native_uri_remains_supported(query) -> None:
    uri = "trojan://secret@native.example:443?" + query + "#Trojan"
    source = StandardSource(id="uri", name="URI", quality_group=QUALITY_MEDIUM, ingest_kind="manual_nodes", manual_nodes_text=uri)
    nodes = SourceFetcher(Settings.from_env()).parse_manual_nodes(source).nodes
    encoded, skipped = build_shadowrocket_nodes_subscription(nodes)
    assert skipped == []
    assert urlparse(base64.b64decode(encoded).decode()).query == urlparse(uri).query
    inline, skipped = build_shadowrocket_config(nodes, [], "https://sub.example/shadowrocket.conf")
    assert skipped == []
    assert " = trojan," in inline
    assert "shadowrocket-unverified-fields-omitted" in inline
    native = SourceFetcher(Settings.from_env())._parse_clash_payload(yaml.safe_dump({"proxies": [{
        "name": "Plain", "type": "trojan", "server": "plain.example", "port": 443, "password": "secret", "sni": "sni.example",
    }]}), source).nodes
    encoded, skipped = build_shadowrocket_nodes_subscription(native)
    assert skipped == []
    assert parse_qs(urlparse(base64.b64decode(encoded).decode()).query)["sni"] == ["sni.example"]


def test_uri_parser_to_mihomo_and_node_export_preserves_vless_tls_websocket_fields() -> None:
    uri = (
        "vless://ed3fe100-9247-4eac-a7d9-646aac14b979@server.example:443"
        "?type=ws&security=tls&path=%2Fwebsocket&host=front.example&sni=tls.example&alpn=h2%2Chttp%2F1.1&fp=chrome#WS"
    )
    source = StandardSource(id="s", name="Source", quality_group=QUALITY_MEDIUM, ingest_kind="manual_nodes", manual_nodes_text=uri)
    nodes = SourceFetcher(Settings.from_env()).parse_manual_nodes(source).nodes
    assert len(nodes) == 1
    provider, skipped = build_clash_provider_config(nodes, "medium")
    assert skipped == []
    proxy = yaml.safe_load(provider)["proxies"][0]
    assert proxy["tls"] is True
    assert proxy["servername"] == "tls.example"
    assert proxy["alpn"] == ["h2", "http/1.1"]
    assert proxy["client-fingerprint"] == "chrome"
    assert proxy["skip-cert-verify"] is False
    assert proxy["network"] == "ws"
    assert proxy["ws-opts"] == {"path": "/websocket", "headers": {"Host": "front.example"}}
    encoded, skipped = build_shadowrocket_nodes_subscription(nodes)
    assert skipped == []
    exported = base64.b64decode(encoded).decode()
    assert urlparse(exported).query == urlparse(uri).query
    inline, skipped = build_shadowrocket_config(nodes, [], "https://sub.example/shadowrocket.conf")
    assert skipped == []
    assert " = vless," in inline
    assert "tls=true" in inline and "obfs-uri=/websocket" in inline
    assert "peer=tls.example" in inline


def test_legacy_vmess_parser_to_three_outputs_preserves_fields_or_reports_rejection() -> None:
    payload = {
        "add": "vm.example", "port": 443, "id": "uuid", "aid": "0", "scy": "aes-128-gcm",
        "net": "ws", "path": "/ws", "host": "front.example", "sni": "tls.example", "tls": "tls",
    }
    uri = "vmess://" + base64.b64encode(json.dumps(payload).encode()).decode()
    source = StandardSource(id="s", name="Source", quality_group=QUALITY_MEDIUM, ingest_kind="manual_nodes", manual_nodes_text=uri)
    nodes = SourceFetcher(Settings.from_env()).parse_manual_nodes(source).nodes
    provider, skipped = build_clash_provider_config(nodes, "medium")
    assert skipped == []
    proxy = yaml.safe_load(provider)["proxies"][0]
    assert proxy["tls"] is True
    assert proxy["cipher"] == "aes-128-gcm"
    assert proxy["ws-opts"]["path"] == "/ws"
    surge, skipped = build_surge_config(nodes, [], managed_subscription_url="https://sub.example/config")
    assert skipped == []
    line = next(line for line in surge.splitlines() if " = vmess," in line)
    assert "tls=true" in line
    assert "sni=tls.example" in line
    assert "ws-path=/ws" in line
    assert "ws-headers=Host:front.example" in line
    assert "encrypt-method=aes-128-gcm" in line
    encoded, skipped = build_shadowrocket_nodes_subscription(nodes)
    assert skipped == []
    exported_uri = base64.b64decode(encoded).decode()
    exported_json = json.loads(base64.b64decode(exported_uri[8:]))
    assert exported_json["tls"] == "tls"
    assert exported_json["net"] == "ws"
    assert exported_json["path"] == "/ws"
    assert exported_json["host"] == "front.example"
    assert exported_json["sni"] == "tls.example"
    assert exported_json["scy"] == "aes-128-gcm"
    inline, skipped = build_shadowrocket_config(nodes, [], "https://sub.example/shadowrocket.conf")
    assert skipped == []
    assert "alterId=0, method=auto" in inline and "obfs-uri=/ws" in inline


def test_sip002_plugin_survives_parser_provider_and_node_uri_export() -> None:
    uri = "ss://YWVzLTEyOC1nY206c2VjcmV0@ss.example:443/?plugin=obfs-local%3Bobfs%3Dhttp%3Bobfs-host%3Dfront.example#SS"
    source = StandardSource(id="s", name="SS", quality_group=QUALITY_MEDIUM, ingest_kind="manual_nodes", manual_nodes_text=uri)
    nodes = SourceFetcher(Settings.from_env()).parse_manual_nodes(source).nodes
    provider, skipped = build_clash_provider_config(nodes, "medium")
    assert skipped == []
    proxy = yaml.safe_load(provider)["proxies"][0]
    assert proxy["plugin"] == "obfs"
    assert proxy["plugin-opts"] == {"mode": "http", "host": "front.example"}
    encoded, skipped = build_shadowrocket_nodes_subscription(nodes)
    assert skipped == []
    assert urlparse(base64.b64decode(encoded).decode()).query == urlparse(uri).query
    inline, skipped = build_shadowrocket_config(nodes, [], "https://sub.example/shadowrocket.conf")
    assert skipped == [nodes[0].name]
    assert "shadowrocket-inline-unsupported" in inline


def test_build_configs_with_four_quality_groups() -> None:
    medium = NodeRecord(name="p3", host="c.example.com", port=443, protocol="http", quality_group=QUALITY_MEDIUM)
    nodes = [
        NodeRecord(name="p1", host="a.example.com", port=443, protocol="http", quality_group=QUALITY_HIGH_PREMIUM),
        NodeRecord(name="p2", host="b.example.com", port=443, protocol="http", quality_group=QUALITY_HIGH_STANDARD),
        medium,
        NodeRecord(name="p4", host="d.example.com", port=443, protocol="http", quality_group=QUALITY_BULK),
        NodeRecord(
            name="链式家宽 | p3 -> 家宽1",
            host="e.example.com",
            port=1080,
            protocol="socks5",
            quality_group=QUALITY_CHAIN_HOME,
            raw={
                "chain_home": True,
                "chain_front_dedupe_key": medium.dedupe_key(),
                "chain_rear_label": "家宽1",
                "chain_rear_target": "e.example.com:1080",
            },
        ),
    ]
    rules = [
        "DOMAIN-SUFFIX,openai.com,高质量-高倍率",
        "DOMAIN-SUFFIX,youtube.com,高质量-低倍率",
    ]

    clash, skipped_c = build_clash_config(
        nodes,
        rules,
        provider_base_url="http://test",
        subscription_token="tok1",
    )
    sr, skipped_s = build_shadowrocket_config(nodes, rules, "http://test/sub/device/t1/shadowrocket.conf")
    surge, skipped_surge = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
    )

    assert skipped_c == []
    assert skipped_s == []
    assert skipped_surge == []
    clash_payload = yaml.safe_load(clash)
    assert "proxies" not in clash_payload
    assert set(clash_payload["proxy-providers"]) == set(CLASH_PROVIDER_KEYS)
    premium_provider = clash_payload["proxy-providers"]["high-premium"]
    premium_url = urlparse(premium_provider["url"])
    assert premium_url.path == "/sub/device/tok1/clash/providers/high-premium.yaml"
    assert parse_qs(premium_url.query)["rev"]
    assert premium_provider["path"].startswith("./providers/subhub-")
    assert premium_provider["path"].endswith(".yaml")
    assert premium_provider["path"].endswith("-high-premium.yaml")
    assert premium_provider["proxy"] == "DIRECT"
    assert "health-check" not in premium_provider
    assert "高质量-高倍率" in clash
    assert "高质量-低倍率" in clash
    assert "中等质量" in clash
    assert "低质量大流量" in clash
    assert "链式家宽" in clash
    assert "链式入口·自动" in clash
    chain_provider = build_clash_provider_config(nodes, "chain-home")[0]
    chain_provider_payload = yaml.safe_load(chain_provider)
    assert chain_provider_payload["proxies"][0]["dialer-proxy"] == "链式入口·自动"
    assert chain_provider_payload["proxies"][0]["name"] == "链式家宽 | p3 -> 家宽1"
    assert "香港出口" not in chain_provider
    assert "rule-providers:" in clash
    assert "RULE-SET,catalog-rules-hq_premium,高质量-高倍率" in clash
    assert "FINAL,兜底代理" in sr
    assert "FINAL,兜底代理,dns-failed" in surge
    assert "高质量-高倍率·自动 = url-test" in sr
    assert "高质量-高倍率·手动 = select" not in sr
    assert "[Proxy]" in sr
    assert SHADOWROCKET_MAIN_CONFIG_MODE == "inline-proxies"
    assert "链式入口·自动 = url-test, 中等质量·自动, 低质量大流量·自动" in sr
    assert "forwarding-proxy=链式入口·自动" in sr
    assert "高质量-高倍率·自动 = smart" in surge
    assert "高质量-高倍率·手动 = select" not in surge
    assert "兜底代理 = select, 链式家宽·自动, REJECT" in surge
    assert "链式入口·自动 = fallback, 中等质量·自动, 低质量大流量·自动" in surge
    assert "timeout=5" in surge
    assert "tolerance=50" in surge
    assert "underlying-proxy=链式入口·自动" in surge
    assert "DOMAIN-SET,http://test/sub/device/t1/surge/domain-set/catalog-domains-hq_premium.txt,高质量-高倍率" in surge
    assert "DOMAIN-SET,http://test/sub/device/t1/surge/domain-set/catalog-domains-hq_standard.txt,高质量-低倍率" in surge
    assert "policy-path=" not in surge
    assert "policy-priority=" not in surge
    assert "#!REQUIREMENT CORE_VERSION>=22\n高质量-高倍率·自动 = smart" not in surge
    assert "#!REQUIREMENT CORE_VERSION<22\n高质量-高倍率·自动 = url-test" not in surge
    assert "#!REQUIREMENT CORE_VERSION>=22 高质量-高倍率·自动 = smart" in surge
    fallback_line = _find_line(surge, "高质量-高倍率·自动 = url-test")
    assert "高质量-高倍率·自动 = url-test, p1" in fallback_line
    assert "url=" not in fallback_line
    assert "interval=300" in fallback_line
    assert "timeout=5" in fallback_line
    assert "tolerance=50" in fallback_line
    assert fallback_line.endswith("//!REQUIREMENT CORE_VERSION<22")


def test_business_group_pool_contract_is_explicit_and_fail_closed() -> None:
    unbound_policy = build_policy_ir(
        [],
        [],
        business_groups=[BusinessGroup(name="AI tools", sort_order=0)],
    )
    unbound_text, _ = build_clash_config([], [], policy_ir=unbound_policy)
    _, unbound_groups = _proxy_group_map_from_clash(unbound_text)
    assert unbound_groups["AI tools"]["proxies"] == [QUALITY_REJECT]

    bound_policy = build_policy_ir(
        [],
        [],
        business_groups=[BusinessGroup(name="AI tools", sort_order=0, pool_names=["medium"])],
    )
    bound_text, _ = build_clash_config([], [], policy_ir=bound_policy)
    _, bound_groups = _proxy_group_map_from_clash(bound_text)
    assert bound_groups["AI tools"]["proxies"] == ["中等质量·自动", "DIRECT"]


def test_chain_home_provider_keeps_socks_auth_fields() -> None:
    medium = NodeRecord(name="p3", host="c.example.com", port=443, protocol="http", quality_group=QUALITY_MEDIUM)
    nodes = [
        medium,
        NodeRecord(
            name="链式家宽 | p3 -> 家宽1",
            host="rear.example.com",
            port=1080,
            protocol="socks5",
            username="chain-user",
            password="chain-pass",
            quality_group=QUALITY_CHAIN_HOME,
            raw={
                "chain_home": True,
                "chain_front_dedupe_key": medium.dedupe_key(),
            },
        ),
    ]

    provider_text, skipped = build_clash_provider_config(nodes, "chain-home")
    assert skipped == []
    payload = yaml.safe_load(provider_text)
    assert len(payload["proxies"]) == 1
    proxy = payload["proxies"][0]
    assert proxy["type"] == "socks5"
    assert proxy["dialer-proxy"] == "链式入口·自动"
    assert proxy["username"] == "chain-user"
    assert proxy["password"] == "chain-pass"


def test_clash_provider_revision_is_stable_and_only_changes_for_affected_provider() -> None:
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]
    nodes = [
        NodeRecord(name="premium-1", host="a.example.com", port=443, protocol="http", quality_group=QUALITY_HIGH_PREMIUM),
        NodeRecord(name="medium-1", host="b.example.com", port=443, protocol="http", quality_group=QUALITY_MEDIUM),
    ]

    first_text, _ = build_clash_config(nodes, rules, provider_base_url="http://test", subscription_token="tok1")
    second_text, _ = build_clash_config(nodes, rules, provider_base_url="http://test", subscription_token="tok1")

    first_payload = yaml.safe_load(first_text)["proxy-providers"]
    second_payload = yaml.safe_load(second_text)["proxy-providers"]
    assert first_payload == second_payload

    changed_nodes = [
        NodeRecord(name="premium-1", host="a.example.com", port=443, protocol="http", quality_group=QUALITY_HIGH_PREMIUM),
        NodeRecord(name="medium-2", host="c.example.com", port=443, protocol="http", quality_group=QUALITY_MEDIUM),
    ]
    changed_text, _ = build_clash_config(
        changed_nodes,
        rules,
        provider_base_url="http://test",
        subscription_token="tok1",
    )
    changed_payload = yaml.safe_load(changed_text)["proxy-providers"]

    assert changed_payload["medium"]["url"] != first_payload["medium"]["url"]
    assert changed_payload["medium"]["path"] == first_payload["medium"]["path"]
    assert changed_payload["high-premium"]["url"] == first_payload["high-premium"]["url"]
    assert changed_payload["high-premium"]["path"] == first_payload["high-premium"]["path"]


def test_build_configs_lazycat_profile_injection() -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        )
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]

    default_clash, _ = build_clash_config(nodes, rules, profile="")
    default_sr, _ = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf",
        profile="",
    )
    default_surge, _ = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
        profile="",
    )
    assert "fake-ip-filter" not in default_clash
    assert "always-real-ip" not in default_clash
    assert "route-exclude-address" not in default_clash
    assert "tun-excluded-routes" not in default_sr
    assert "tun-excluded-routes" not in default_surge

    lazycat_clash, _ = build_clash_config(nodes, rules, profile="lazycat")
    lazycat_sr, _ = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf?profile=lazycat",
        profile="lazycat",
    )
    lazycat_surge, _ = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf?profile=lazycat",
        profile="lazycat",
    )
    assert "fake-ip-filter" not in lazycat_clash
    assert "always-real-ip" not in lazycat_clash
    assert "enhanced-mode: redir-host" in lazycat_clash
    assert "use-hosts: true" in lazycat_clash
    assert "respect-rules: true" in lazycat_clash
    assert "fake-ip-range: 198.18.0.1/16" not in lazycat_clash
    assert "fake-ip-filter-mode: rule" not in lazycat_clash
    assert "listen: 127.0.0.1:1053" in lazycat_clash
    assert "mixed-port: 7890" in lazycat_clash
    assert "store-selected: true" in lazycat_clash
    assert "store-fake-ip: false" in lazycat_clash
    assert "external-controller: 127.0.0.1:9090" in lazycat_clash
    assert "default-nameserver" in lazycat_clash
    assert "proxy-server-nameserver" in lazycat_clash
    assert "dns-hijack" not in lazycat_clash
    assert "strict-route: true" not in lazycat_clash
    assert "route-exclude-address" not in lazycat_clash
    assert "DOMAIN-SUFFIX,heiyu.space,real-ip" not in lazycat_clash
    assert "2000::6666/128" not in lazycat_clash
    assert "[Proxy]" in lazycat_sr
    assert "[Proxy Group]" in lazycat_sr
    assert "always-real-ip = *.heiyu.space,*.lazycat.cloud,*.lazycatmicroserver.com" in lazycat_sr
    assert "tun-excluded-routes = 6.6.6.6/32,2000::6666/128" in lazycat_sr
    assert "always-real-ip = *.heiyu.space,*.lazycat.cloud,*.lazycatmicroserver.com" in lazycat_surge
    assert "tun-excluded-routes = 6.6.6.6/32,2000::6666/128" in lazycat_surge

    raw_clash, _ = build_clash_config(nodes, rules, profile="raw")
    raw_sr, _ = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf?profile=raw",
        profile="raw",
    )
    raw_surge, _ = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf?profile=raw",
        profile="raw",
    )
    assert "fake-ip-filter" not in raw_clash
    assert "always-real-ip" not in raw_clash
    assert "mixed-port: 7890" in raw_clash
    assert "route-exclude-address" not in raw_clash
    assert "tun-excluded-routes" not in raw_sr
    assert "tun-excluded-routes" not in raw_surge


def test_lazycat_surge_and_shadowrocket_skip_proxy_excludes_tun_routes() -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        )
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]
    profile_settings = {
        "surge_skip_proxy": ["6.6.6.6/32,", "2000::6666/128"],
        "surge_tun_excluded_routes": ["6.6.6.6/32", "2000::6666/128"],
        "shadowrocket_skip_proxy": ["6.6.6.6/32,", "2000::6666/128"],
        "shadowrocket_tun_excluded_routes": ["6.6.6.6/32", "2000::6666/128"],
    }

    surge_text, surge_skipped = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf?profile=lazycat",
        profile="lazycat",
        profile_settings=profile_settings,
    )
    shadowrocket_text, shadowrocket_skipped = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf?profile=lazycat",
        profile="lazycat",
        profile_settings=profile_settings,
    )

    assert surge_skipped == []
    assert shadowrocket_skipped == []
    assert "tun-excluded-routes = 6.6.6.6/32,2000::6666/128" in surge_text
    assert "skip-proxy =" not in surge_text
    assert "tun-excluded-routes = 6.6.6.6/32,2000::6666/128" in shadowrocket_text
    assert "skip-proxy =" not in shadowrocket_text


def test_lazycat_host_records_render_for_surge_shadowrocket_and_mihomo() -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        )
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]
    profile_settings = {
        "surge_host_records": {"subhub.devbox.heiyu.space": "203.0.113.10"},
        "shadowrocket_host_records": {"subhub.prodbox.heiyu.space": "203.0.113.11"},
        "clash_host_records": {"subhub.devbox.heiyu.space": "203.0.113.10"},
    }

    clash_text, clash_skipped, clash_warnings = build_clash_profile_artifacts(
        nodes,
        rules,
        profile="lazycat",
        profile_settings=profile_settings,
    )
    shadowrocket_text, shadowrocket_skipped = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf?profile=lazycat",
        profile="lazycat",
        profile_settings=profile_settings,
    )
    surge_artifacts = build_surge_profile_artifacts(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf?profile=lazycat",
        profile="lazycat",
        profile_settings=profile_settings,
    )

    clash_payload = yaml.safe_load(clash_text)
    assert clash_skipped == []
    assert shadowrocket_skipped == []
    assert clash_payload["hosts"] == {
        "subhub.devbox.heiyu.space": "203.0.113.10",
    }
    assert not any(item.code == "clash-lazycat-host-record-local-target" for item in clash_warnings)
    assert "[Host]" in shadowrocket_text
    assert "subhub.prodbox.heiyu.space = 203.0.113.11" in shadowrocket_text
    assert "[Host]" in surge_artifacts.main_conf
    assert "subhub.devbox.heiyu.space = 203.0.113.10" in surge_artifacts.main_conf
    assert not any(item.code == "surge-lazycat-host-record-local-target" for item in surge_artifacts.diagnostics)


def test_lazycat_real_host_path_without_host_records_does_not_emit_host_record_warnings() -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        )
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]

    clash_text, clash_skipped, clash_warnings = build_clash_profile_artifacts(
        nodes,
        rules,
        profile="lazycat",
    )
    shadowrocket_text, shadowrocket_skipped = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf?profile=lazycat",
        profile="lazycat",
    )
    surge_artifacts = build_surge_profile_artifacts(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf?profile=lazycat",
        profile="lazycat",
    )
    shadowrocket_warnings = derive_shadowrocket_profile_diagnostics({})

    clash_payload = yaml.safe_load(clash_text)
    assert clash_skipped == []
    assert shadowrocket_skipped == []
    assert "hosts" not in clash_payload
    assert "[Host]" not in shadowrocket_text
    assert "[Host]" not in surge_artifacts.main_conf
    assert not any(item.code == "clash-lazycat-host-record-local-target" for item in clash_warnings)
    assert not any(item.code == "shadowrocket-lazycat-host-record-local-target" for item in shadowrocket_warnings)
    assert not any(item.code == "surge-lazycat-host-record-local-target" for item in surge_artifacts.diagnostics)


def test_lazycat_host_records_warn_when_pointing_to_localhost_or_current_machine(monkeypatch) -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        )
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]
    profile_settings = {
        "surge_host_records": {
            "subhub.devbox.heiyu.space": "192.168.0.108",
            "cookiecloud.devbox.heiyu.space": "localhost",
        },
        "shadowrocket_host_records": {
            "cookiecloud.prodbox.heiyu.space": "127.0.0.1",
        },
        "clash_host_records": {
            "subhub.devbox.heiyu.space": "192.168.0.108",
        },
    }
    monkeypatch.setattr(
        "app.services.subscription_builder._local_host_target_aliases",
        lambda: {"localhost", "127.0.0.1", "::1", "192.168.0.108"},
    )

    _, _, clash_warnings = build_clash_profile_artifacts(
        nodes,
        rules,
        profile="lazycat",
        profile_settings=profile_settings,
        local_host_aliases=frozenset({"localhost", "127.0.0.1", "::1", "192.168.0.108"}),
    )
    _, _ = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf?profile=lazycat",
        profile="lazycat",
        profile_settings=profile_settings,
        local_host_aliases=frozenset({"localhost", "127.0.0.1", "::1", "192.168.0.108"}),
    )
    surge_artifacts = build_surge_profile_artifacts(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf?profile=lazycat",
        profile="lazycat",
        profile_settings=profile_settings,
        local_host_aliases=frozenset({"localhost", "127.0.0.1", "::1", "192.168.0.108"}),
    )
    shadowrocket_warnings = derive_shadowrocket_profile_diagnostics(profile_settings)

    assert any(item.code == "clash-lazycat-host-record-local-target" for item in clash_warnings)
    assert any(item.code == "shadowrocket-lazycat-host-record-local-target" for item in shadowrocket_warnings)
    assert any(item.code == "surge-lazycat-host-record-local-target" for item in surge_artifacts.diagnostics)


def test_detect_node_country_matches_current_source_patterns() -> None:
    countries = [rule.country for rule in COUNTRY_ALIAS_RULES]
    assert len(countries) == len(set(countries))
    source_keys = [ruleset.source_key for ruleset in SOURCE_COUNTRY_RULESETS]
    assert len(source_keys) == len(set(source_keys))
    assert extract_source_hint("[FlowerCloud] 🇺🇸 美国标准 IEPL 专线 1") == "FlowerCloud"
    assert detect_node_country("日本01[软银]0.5x", source_hint="山海") == "日本"
    assert _detect_node_country("[FlowerCloud] 🇺🇸 美国标准 IEPL 专线 1") == "美国"
    assert _detect_node_country("[山海] 美国01[专线]3.0x") == "美国"
    assert _detect_node_country("[FlowerCloud] Traffic: 2.01 GB | 20 GB") == "其他"


def test_country_routed_quality_groups_render_for_clash_surge_and_shadowrocket() -> None:
    nodes = [
        NodeRecord(
            name="[FlowerCloud] 🇺🇸 美国标准 IEPL 专线 1",
            host="medium-us.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
        NodeRecord(
            name="[FlowerCloud] 🇯🇵 日本标准 IEPL 专线 1",
            host="medium-jp.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
        NodeRecord(
            name="[FlowerCloud] Traffic: 2.01 GB | 20 GB",
            host="medium-other.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
        NodeRecord(
            name="[山海] 美国01[专线]3.0x",
            host="bulk-us.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_BULK,
        ),
        NodeRecord(
            name="[山海] 日本01[专线]4.0x",
            host="bulk-jp.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_BULK,
        ),
        NodeRecord(
            name="[山海] 香港01[专线]4.0x",
            host="bulk-hk.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_BULK,
        ),
    ]
    rules = [
        "DOMAIN-SUFFIX,openai.com,高质量-高倍率",
        "DOMAIN-SUFFIX,example.com,中等质量",
        "DOMAIN-SUFFIX,download.example,低质量大流量",
    ]
    policy_ir = build_policy_ir(nodes, rules, contracts=_default_route_contracts())

    clash_text, _ = build_clash_config(
        nodes,
        rules,
        provider_base_url="http://test",
        subscription_token="tok-country",
        policy_ir=policy_ir,
    )
    group_order, group_map = _proxy_group_map_from_clash(clash_text)
    assert group_order.index("中等质量") < group_order.index("中等质量·自动") < group_order.index("中等质量·美国")
    assert group_order.index("低质量大流量") < group_order.index("低质量大流量·自动") < group_order.index("低质量大流量·美国")
    assert group_map["中等质量·自动"]["type"] == "fallback"
    assert group_map["中等质量·自动"]["proxies"] == ["中等质量·美国", "中等质量·国际最优", "REJECT"]
    assert "中等质量·故障转移" not in group_map
    assert "中等质量·手动" not in group_map
    assert "低质量大流量·手动" not in group_map

    surge_text, _ = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
        policy_ir=policy_ir,
    )
    assert surge_text.index("中等质量 = fallback") < surge_text.index("中等质量·自动 = fallback") < surge_text.index("中等质量·美国 = smart")
    assert surge_text.index("低质量大流量 = fallback") < surge_text.index("低质量大流量·自动 = fallback") < surge_text.index("低质量大流量·美国 = smart")
    medium_auto_line = _find_line(surge_text, "中等质量·自动 = fallback")
    assert "中等质量·美国, 中等质量·国际最优, REJECT" in medium_auto_line
    assert "url=" not in medium_auto_line
    assert "interval=300" in medium_auto_line
    assert "timeout=5" in medium_auto_line
    assert "中等质量·手动 = select" not in surge_text
    medium_best_line = _find_line(
        surge_text,
        "#!REQUIREMENT CORE_VERSION>=22 中等质量·国际最优 = smart",
    )
    assert "[FlowerCloud] 🇯🇵 日本标准 IEPL 专线 1" in medium_best_line
    assert "[FlowerCloud] Traffic: 2.01 GB | 20 GB" in medium_best_line
    assert "中等质量·日本" not in medium_best_line
    assert "中等质量·其他" not in medium_best_line
    bulk_best_smart_line = _find_line(
        surge_text,
        "#!REQUIREMENT CORE_VERSION>=22 低质量大流量·国际最优 = smart",
    )
    assert "[山海] 日本01[专线]4.0x" in bulk_best_smart_line
    assert "[山海] 香港01[专线]4.0x" in bulk_best_smart_line
    assert "低质量大流量·日本" not in bulk_best_smart_line
    assert "低质量大流量·香港" not in bulk_best_smart_line
    bulk_best_line = _find_line(surge_text, "低质量大流量·国际最优 = url-test")
    assert "[山海] 日本01[专线]4.0x" in bulk_best_line
    assert "[山海] 香港01[专线]4.0x" in bulk_best_line
    assert "url=" not in bulk_best_line
    assert "interval=300" in bulk_best_line
    assert "timeout=5" in bulk_best_line
    assert "tolerance=50" in bulk_best_line
    assert bulk_best_line.endswith("//!REQUIREMENT CORE_VERSION<22")
    assert "include-other-group=" not in surge_text

    shadowrocket_text, _ = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf",
        policy_ir=policy_ir,
    )
    for text in (shadowrocket_text,):
        assert text.index("中等质量 = fallback") < text.index("中等质量·自动 = fallback") < text.index("中等质量·美国 = url-test")
        assert text.index("低质量大流量 = fallback") < text.index("低质量大流量·自动 = fallback") < text.index("低质量大流量·美国 = url-test")
        assert _find_line(text, "中等质量·自动 = fallback").startswith(
            "中等质量·自动 = fallback, 中等质量·美国, 中等质量·国际最优, REJECT"
        )
        assert "中等质量·手动 = select" not in text
        assert "低质量大流量·手动 = select" not in text


def test_country_routed_quality_groups_handle_missing_preferred_and_single_country() -> None:
    no_us_nodes = [
        NodeRecord(name="[FlowerCloud] 🇯🇵 日本标准 IEPL 专线 1", host="jp.example.com", port=443, protocol="http", quality_group=QUALITY_MEDIUM),
        NodeRecord(name="[FlowerCloud] 🇭🇰 香港标准 IEPL 专线 1", host="hk.example.com", port=443, protocol="http", quality_group=QUALITY_MEDIUM),
    ]
    no_us_policy = build_policy_ir(no_us_nodes, ["DOMAIN-SUFFIX,example.com,中等质量"], contracts=_default_route_contracts())
    clash_text, _ = build_clash_config(
        no_us_nodes,
        ["DOMAIN-SUFFIX,example.com,中等质量"],
        provider_base_url="http://test",
        subscription_token="tok-no-us",
        policy_ir=no_us_policy,
    )
    _, clash_groups = _proxy_group_map_from_clash(clash_text)
    assert clash_groups["中等质量·自动"]["proxies"] == ["中等质量·国际最优", "REJECT"]
    assert "中等质量·故障转移" not in clash_groups

    single_country_nodes = [
        NodeRecord(name="[山海] 日本01[专线]4.0x", host="bulk-jp.example.com", port=443, protocol="http", quality_group=QUALITY_BULK),
    ]
    single_policy = build_policy_ir(
        single_country_nodes,
        ["DOMAIN-SUFFIX,download.example,低质量大流量"],
        contracts=_default_route_contracts(),
    )
    single_clash_text, _ = build_clash_config(
        single_country_nodes,
        ["DOMAIN-SUFFIX,download.example,低质量大流量"],
        provider_base_url="http://test",
        subscription_token="tok-single",
        policy_ir=single_policy,
    )
    single_order, single_groups = _proxy_group_map_from_clash(single_clash_text)
    assert "低质量大流量·国际最优" not in single_order
    assert single_groups["低质量大流量·自动"]["proxies"] == ["低质量大流量·日本", "REJECT"]
    assert "低质量大流量·手动" not in single_groups


def test_build_configs_lazycat_profile_custom_settings() -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        )
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]
    profile_settings = {
        "clash_fake_ip_filter": ["+.custom.test"],
        "clash_always_real_ip": ["*.custom.test"],
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
        "shadowrocket_always_real_ip": ["*.sr.custom.test"],
        "shadowrocket_tun_excluded_routes": ["172.16.0.0/12"],
        "surge_always_real_ip": ["*.surge.custom.test"],
        "surge_tun_excluded_routes": ["100.64.0.0/10"],
    }

    lazycat_clash, _, render_warnings = build_clash_profile_artifacts(
        nodes,
        rules,
        profile="lazycat",
        profile_settings=profile_settings,
    )
    lazycat_sr, _ = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf",
        profile="lazycat",
        profile_settings=profile_settings,
    )
    lazycat_surge, _ = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
        profile="lazycat",
        profile_settings=profile_settings,
    )
    lazycat_clash_payload = yaml.safe_load(lazycat_clash)
    assert lazycat_clash_payload["dns"]["enable"] is False
    assert lazycat_clash_payload["dns"]["listen"] == "0.0.0.0:5353"
    assert lazycat_clash_payload["dns"]["enhanced-mode"] == "redir-host"
    assert lazycat_clash_payload["dns"]["use-hosts"] is True
    assert lazycat_clash_payload["mixed-port"] == 17890
    assert lazycat_clash_payload["dns"]["default-nameserver"] == ["1.1.1.1"]
    assert lazycat_clash_payload["dns"]["nameserver"] == ["https://dns.google/dns-query"]
    assert lazycat_clash_payload["dns"]["fallback"] == ["tls://9.9.9.9"]
    assert "fake-ip-filter" not in lazycat_clash_payload["dns"]
    assert "always-real-ip" not in lazycat_clash_payload["dns"]
    assert "tun" not in lazycat_clash_payload
    warning_codes = [item.code for item in render_warnings]
    assert "clash-always-real-ip-pending-validation" in warning_codes
    assert "always-real-ip = *.sr.custom.test" in lazycat_sr
    assert "tun-excluded-routes = 172.16.0.0/12" in lazycat_sr
    assert "always-real-ip = *.surge.custom.test" in lazycat_surge
    assert "tun-excluded-routes = 100.64.0.0/10" in lazycat_surge


def test_shadowrocket_http_pipeline_sections_render_in_main_and_legacy_configs() -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,中等质量"]
    profile_settings = {
        "shadowrocket_url_rewrite": ["^https://example.com/a https://example.com/b 302"],
        "shadowrocket_map_local": ['^https://example.com/mock data-type=text data="ok" status-code=200'],
        "shadowrocket_mitm_hostname": ["example.com", "*.example.net"],
        "shadowrocket_script_request": [
            "type=http-request,pattern=^https://example.com/api,script-path=https://example.com/request.js",
        ],
        "shadowrocket_script_response": [
            "type=http-response,pattern=^https://example.com/api,requires-body=1,script-path=https://example.com/response.js",
        ],
    }

    main_text, _ = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf?profile=lazycat",
        profile="lazycat",
        profile_settings=profile_settings,
    )
    for text in (main_text,):
        assert "Shadowrocket 2.2.93" in text
        assert "full system trust" in text
        assert "[URL Rewrite]" in text
        assert "^https://example.com/a https://example.com/b 302" in text
        assert "[Map Local]" not in text
        assert "shadowrocket-map-local-intercept-only" in text
        assert '[Script]' in text
        assert "type=http-request,pattern=^https://example.com/api,script-path=https://example.com/request.js" in text
        assert "type=http-response,pattern=^https://example.com/api,requires-body=1,script-path=https://example.com/response.js" in text
        assert "[MITM]" in text
        assert "enable = true" in text
        assert "hostname = example.com, *.example.net" in text


def test_clash_reject_rule_lines_output_correctly() -> None:
    """REJECT rules should appear as rule lines but NOT as a proxy-group."""
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
    ]
    rules = [
        "DOMAIN-SUFFIX,ads.example.com,REJECT",
        "DOMAIN-KEYWORD,tracker,REJECT",
        "DOMAIN-SUFFIX,openai.com,高质量-高倍率",
    ]

    clash_text, skipped = build_clash_config(nodes, rules)
    assert skipped == []

    parsed = yaml.safe_load(clash_text)

    # REJECT must NOT appear as a proxy-group name
    group_names = [g["name"] for g in parsed["proxy-groups"]]
    assert "REJECT" not in group_names
    assert "高质量-高倍率·自动" in group_names
    assert "中等质量·自动" in group_names
    for group in QUALITY_GROUPS:
        assert f"{group}·故障转移" not in group_names
        assert f"{group}·手动" not in group_names
    assert "兜底代理" in group_names

    # REJECT rule lines must be present in rules
    assert "RULE-SET,catalog-rules-ad_block,REJECT" in parsed["rules"]
    assert "RULE-SET,catalog-rules-hq_premium,高质量-高倍率" in parsed["rules"]
    assert set(parsed["rule-providers"]) >= {"catalog-rules-ad_block", "catalog-rules-hq_premium"}
    assert "MATCH,兜底代理" in parsed["rules"]


def test_shadowrocket_reject_rule_lines_output_correctly() -> None:
    """REJECT rules should appear as rule lines but NOT as a proxy-group in Shadowrocket."""
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
    ]
    rules = [
        "DOMAIN-SUFFIX,ads.example.com,REJECT",
        "DOMAIN-KEYWORD,tracker,REJECT",
        "DOMAIN-SUFFIX,openai.com,高质量-高倍率",
    ]

    sr_text, skipped = build_shadowrocket_config(
        nodes, rules, "http://test/sub/device/t1/shadowrocket.conf"
    )
    assert skipped == []

    # REJECT must NOT appear as a proxy-group line
    for line in sr_text.splitlines():
        if line.startswith("REJECT") and "= select" in line:
            raise AssertionError("REJECT should not be a proxy-group in Shadowrocket")
    assert "[Proxy]" in sr_text

    # REJECT rule lines must be present in the [Rule] section
    assert "DOMAIN-SUFFIX,ads.example.com,REJECT" in sr_text
    assert "DOMAIN-KEYWORD,tracker,REJECT" in sr_text
    # Normal rule still present
    assert "DOMAIN-SUFFIX,openai.com,高质量-高倍率" in sr_text
    # Fallback rule
    assert "FINAL,兜底代理" in sr_text


def test_reject_not_a_proxy_group_even_with_no_nodes() -> None:
    """Even with zero nodes, REJECT should never appear as a proxy-group."""
    rules = [
        "DOMAIN-SUFFIX,ads.example.com,REJECT",
    ]

    clash_text, _ = build_clash_config([], rules)
    parsed = yaml.safe_load(clash_text)
    group_names = [g["name"] for g in parsed["proxy-groups"]]
    assert "REJECT" not in group_names

    sr_text, _ = build_shadowrocket_config(
        [], rules, "http://test/sub/device/t1/shadowrocket.conf"
    )
    for line in sr_text.splitlines():
        if line.startswith("REJECT") and "= select" in line:
            raise AssertionError("REJECT should not be a proxy-group in Shadowrocket")


def test_clash_sanitizes_domain_ip_rules_and_surfaces_conflicts() -> None:
    rules = [
        "DOMAIN,103.224.182.210,低质量大流量",
        "DOMAIN,2001:db8::1,中等质量",
        "IP-CIDR,103.224.182.210/32,高质量-高倍率,no-resolve",
        "IP-CIDR6,invalid-ipv6,中等质量",
        "DOMAIN,example.com,中等质量",
    ]

    clash_text, skipped, render_warnings = build_clash_profile_artifacts([], rules)
    assert skipped == []

    parsed = yaml.safe_load(clash_text)
    assert _without_udp_guards(parsed["rules"]) == [
        "RULE-SET,catalog-rules-bulk,低质量大流量",
        "RULE-SET,catalog-rules-medium,中等质量",
        "MATCH,兜底代理",
    ]
    assert build_clash_rule_provider_config([], rules, "catalog-rules-bulk") == (
        "IP-CIDR,103.224.182.210/32,no-resolve\n"
    )
    assert build_clash_rule_provider_config([], rules, "catalog-rules-medium") == (
        "IP-CIDR6,2001:db8::1/128,no-resolve\n"
        "DOMAIN,example.com\n"
    )

    warning_codes = [item.code for item in render_warnings]
    assert warning_codes.count("clash-domain-ip-autofixed") == 2
    assert "clash-cidr-overlap-pruned" in warning_codes
    assert "clash-rule-dropped-invalid" in warning_codes


def test_clash_cidr_conflicts_ignore_no_resolve_differences() -> None:
    rules = [
        "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
        "IP-CIDR,10.0.0.0/8,低质量大流量",
        "IP-CIDR6,fc00::/7,DIRECT",
        "IP-CIDR6,fc00::/7,低质量大流量,no-resolve",
    ]

    clash_text, skipped, render_warnings = build_clash_profile_artifacts([], rules)
    assert skipped == []

    parsed = yaml.safe_load(clash_text)
    assert _without_udp_guards(parsed["rules"]) == [
        "RULE-SET,catalog-rules-bulk,低质量大流量",
        "MATCH,兜底代理",
    ]
    assert build_clash_rule_provider_config([], rules, "catalog-rules-bulk") == (
        "IP-CIDR,10.0.0.0/8,no-resolve\n"
        "IP-CIDR6,fc00::/7,no-resolve\n"
    )
    warning_codes = [item.code for item in render_warnings]
    assert warning_codes.count("conflicting-rule-target") == 2


def test_clash_prunes_fully_covered_later_cidr_rules() -> None:
    clash_text, skipped, render_warnings = build_clash_profile_artifacts(
        [],
        [
            "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,10.72.25.0/24,低质量大流量,no-resolve",
        ],
    )
    assert skipped == []

    parsed = yaml.safe_load(clash_text)
    assert _without_udp_guards(parsed["rules"]) == [
        "RULE-SET,catalog-rules-direct,DIRECT",
        "MATCH,兜底代理",
    ]
    assert build_clash_rule_provider_config([], [
        "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
        "IP-CIDR,10.72.25.0/24,低质量大流量,no-resolve",
    ], "catalog-rules-direct") == "IP-CIDR,10.0.0.0/8,no-resolve\n"
    warning_codes = [item.code for item in render_warnings]
    assert "clash-cidr-overlap-pruned" in warning_codes


def test_clash_splits_later_broader_cidr_rules_into_residuals() -> None:
    clash_text, skipped, render_warnings = build_clash_profile_artifacts(
        [],
        [
            "IP-CIDR,13.32.0.0/16,高质量-低倍率,no-resolve",
            "IP-CIDR,13.32.0.0/15,低质量大流量,no-resolve",
        ],
    )
    assert skipped == []

    parsed = yaml.safe_load(clash_text)
    assert _without_udp_guards(parsed["rules"]) == [
        "RULE-SET,catalog-rules-hq_standard,高质量-低倍率",
        "RULE-SET,catalog-rules-bulk,低质量大流量",
        "MATCH,兜底代理",
    ]
    assert build_clash_rule_provider_config([], [
        "IP-CIDR,13.32.0.0/16,高质量-低倍率,no-resolve",
        "IP-CIDR,13.32.0.0/15,低质量大流量,no-resolve",
    ], "catalog-rules-hq_standard") == "IP-CIDR,13.32.0.0/16,no-resolve\n"
    assert build_clash_rule_provider_config([], [
        "IP-CIDR,13.32.0.0/16,高质量-低倍率,no-resolve",
        "IP-CIDR,13.32.0.0/15,低质量大流量,no-resolve",
    ], "catalog-rules-bulk") == "IP-CIDR,13.33.0.0/16,no-resolve\n"
    warning_codes = [item.code for item in render_warnings]
    assert "clash-cidr-overlap-split" in warning_codes


def test_clash_src_cidr_rules_do_not_conflict_with_destination_cidr_rules() -> None:
    clash_text, skipped = build_clash_config(
        [],
        [
            "SRC-IP-CIDR,13.32.0.0/16,中等质量,no-resolve",
            "IP-CIDR,13.32.0.0/15,低质量大流量,no-resolve",
        ],
    )
    assert skipped == []

    parsed = yaml.safe_load(clash_text)
    assert _without_udp_guards(parsed["rules"]) == [
        "RULE-SET,catalog-rules-medium,中等质量",
        "RULE-SET,catalog-rules-bulk,低质量大流量",
        "MATCH,兜底代理",
    ]
    assert build_clash_rule_provider_config([], [
        "SRC-IP-CIDR,13.32.0.0/16,中等质量,no-resolve",
        "IP-CIDR,13.32.0.0/15,低质量大流量,no-resolve",
    ], "catalog-rules-medium") == "SRC-IP-CIDR,13.32.0.0/16,no-resolve\n"
    assert build_clash_rule_provider_config([], [
        "SRC-IP-CIDR,13.32.0.0/16,中等质量,no-resolve",
        "IP-CIDR,13.32.0.0/15,低质量大流量,no-resolve",
    ], "catalog-rules-bulk") == "IP-CIDR,13.32.0.0/15,no-resolve\n"


def test_clash_blocked_detail_reports_residual_cidr_overlap_blocker() -> None:
    rendered_content = yaml.safe_dump(
        {
            "proxy-providers": {
                "medium": {
                    "type": "file",
                    "path": "./providers/medium.yaml",
                    "health-check": {
                        "enable": True,
                        "url": "https://cp.cloudflare.com/generate_204",
                        "interval": 300,
                    },
                }
            },
            "proxy-groups": [
                {
                    "name": "中等质量·自动",
                    "type": "url-test",
                    "use": ["medium"],
                    "url": "https://cp.cloudflare.com/generate_204",
                    "interval": 300,
                }
            ],
            "rules": [
                "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
                "IP-CIDR,10.72.25.0/24,低质量大流量,no-resolve",
                "MATCH,兜底代理",
            ],
        },
        allow_unicode=True,
        sort_keys=False,
    )

    detail = build_clash_blocked_detail(
        build_policy_ir([], []),
        rendered_content=rendered_content,
        rendered_warnings=[],
    )

    blocker_codes = [item["code"] for item in detail["blockers"]]
    assert "clash-cidr-overlap-blocker" in blocker_codes


def test_clash_blocked_detail_reports_missing_provider_health_check_for_use_groups() -> None:
    rendered_content = yaml.safe_dump(
        {
            "proxy-providers": {
                "medium": {
                    "type": "file",
                    "path": "./providers/medium.yaml",
                }
            },
            "proxy-groups": [
                {
                    "name": "中等质量·自动",
                    "type": "url-test",
                    "use": ["medium"],
                    "url": "",
                    "interval": 300,
                }
            ],
            "rules": ["MATCH,兜底代理"],
        },
        allow_unicode=True,
        sort_keys=False,
    )

    detail = build_clash_blocked_detail(
        build_policy_ir([], []),
        rendered_content=rendered_content,
        rendered_warnings=[],
    )

    blocker_codes = [item["code"] for item in detail["blockers"]]
    assert "clash-provider-health-check-missing" in blocker_codes
    assert detail["provider_health"]["providers_missing_health_check"] == ["medium"]
    assert detail["provider_health"]["use_groups_without_provider_health_check"] == ["中等质量·自动"]


def test_cross_client_rule_precedence_uses_shared_rule_entries() -> None:
    policy_ir = build_policy_ir(
        [],
        [],
        rule_entries=[
            PolicyRuleEntry(
                target_contract_id="medium",
                rule_type="DOMAIN",
                value="custom.example.com",
                source_kind="custom",
                category_name="custom-medium",
            ),
            PolicyRuleEntry(
                target_contract_id="hq_premium",
                rule_type="DOMAIN",
                value="custom.example.com",
                source_kind="catalog",
                category_name="catalog-premium",
            ),
            PolicyRuleEntry(
                target_contract_id="direct",
                rule_type="DOMAIN",
                value="tier.example.com",
                source_kind="catalog",
                category_name="catalog-direct",
            ),
            PolicyRuleEntry(
                target_contract_id="hq_premium",
                rule_type="DOMAIN",
                value="tier.example.com",
                source_kind="catalog",
                category_name="catalog-premium-tier",
            ),
            PolicyRuleEntry(
                target_contract_id="direct",
                rule_type="DOMAIN-SUFFIX",
                value="heiyu.space",
                source_kind="system",
                category_name="system-direct",
            ),
            PolicyRuleEntry(
                target_contract_id="hq_premium",
                rule_type="DOMAIN-SUFFIX",
                value="heiyu.space",
                source_kind="catalog",
                category_name="catalog-system-conflict",
            ),
        ],
    )

    clash_text, _, render_warnings = build_clash_profile_artifacts([], [], policy_ir=policy_ir)
    sr_text, _ = build_shadowrocket_config([], [], "http://test/sub/device/t1/shadowrocket.conf", policy_ir=policy_ir)
    surge_artifacts = build_surge_profile_artifacts(
        [],
        [],
        "http://test/sub/device/t1/surge.conf",
        policy_ir=policy_ir,
    )

    clash_payload = yaml.safe_load(clash_text)
    clash_rules = clash_payload["rules"]
    clash_warning_codes = [item.code for item in render_warnings]
    assert _without_udp_guards(clash_rules) == [
        "DOMAIN-SUFFIX,heiyu.space,DIRECT",
        "RULE-SET,manual-rules-medium,中等质量",
        "RULE-SET,catalog-rules-hq_premium,高质量-高倍率",
        "MATCH,兜底代理",
    ]
    assert build_clash_rule_provider_config([], [], "manual-rules-medium", policy_ir=policy_ir) == (
        "DOMAIN,custom.example.com\n"
    )
    assert build_clash_rule_provider_config([], [], "catalog-rules-hq_premium", policy_ir=policy_ir) == (
        "DOMAIN,tier.example.com\n"
    )
    assert clash_warning_codes.count("conflicting-rule-target") == 3

    assert "DOMAIN,custom.example.com,中等质量" in sr_text
    assert "DOMAIN,tier.example.com,高质量-高倍率" in sr_text
    assert "DOMAIN-SUFFIX,heiyu.space,DIRECT" in sr_text

    assert surge_artifacts.domain_sets["manual-domains-medium"] == "custom.example.com\n"
    assert surge_artifacts.domain_sets["catalog-domains-hq_premium"] == "tier.example.com\n"
    assert "catalog-domains-direct" not in surge_artifacts.domain_sets
    assert "DOMAIN-SUFFIX,heiyu.space,DIRECT" in surge_artifacts.main_conf
    assert "DOMAIN-SET,http://test/sub/device/t1/surge/domain-set/catalog-domains-hq_premium.txt,高质量-高倍率" in surge_artifacts.main_conf
    assert any(item.code == "conflicting-rule-target" for item in surge_artifacts.diagnostics)
    assert "# Render warnings" not in surge_artifacts.main_conf
    assert "# Build blockers" not in surge_artifacts.main_conf
    assert "conflicting-rule-target" not in surge_artifacts.main_conf


def test_surge_reject_rule_lines_output_correctly() -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
    ]
    rules = [
        "DOMAIN-SUFFIX,ads.example.com,REJECT",
        "DOMAIN-KEYWORD,tracker,REJECT",
        "DOMAIN-SUFFIX,openai.com,高质量-高倍率",
    ]

    artifacts = build_surge_profile_artifacts(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
    )
    surge_text = artifacts.main_conf
    assert artifacts.skipped == []
    for line in surge_text.splitlines():
        if line.startswith("REJECT") and "= select" in line:
            raise AssertionError("REJECT should not be a proxy-group in Surge")
    assert "DOMAIN-SET,http://test/sub/device/t1/surge/domain-set/reject-domains.txt,REJECT,pre-matching" in surge_text
    assert "RULE-SET,http://test/sub/device/t1/surge/rule-set/reject-rules.list,REJECT,pre-matching" in surge_text
    assert artifacts.domain_sets["reject-domains"] == ".ads.example.com\n"
    assert artifacts.rule_sets["reject-rules"] == "DOMAIN-KEYWORD,tracker\n"
    assert artifacts.domain_sets["catalog-domains-hq_premium"] == ".openai.com\n"
    assert "FINAL,兜底代理,dns-failed" in surge_text
    assert "# Render warnings" not in surge_text
    assert "# Build blockers" not in surge_text


def test_ad_block_business_group_lowers_to_reject_for_clash_and_shadowrocket() -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
    ]
    rules = ["DOMAIN-SUFFIX,ads.example.com,广告拦截"]
    policy_ir = build_policy_ir(
        nodes,
        rules,
        business_groups=[
            BusinessGroup(
                name="广告拦截",
                sort_order=0,
                mode=BUSINESS_GROUP_MODE_AD_BLOCK,
            )
        ],
    )

    clash_text, _ = build_clash_config(nodes, rules, policy_ir=policy_ir)
    sr_text, _ = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf",
        policy_ir=policy_ir,
    )
    surge_artifacts = build_surge_profile_artifacts(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
        policy_ir=policy_ir,
    )
    surge_text = surge_artifacts.main_conf

    clash_payload = yaml.safe_load(clash_text)
    clash_group_names = [item["name"] for item in clash_payload["proxy-groups"]]
    assert "广告拦截" not in clash_group_names
    assert "RULE-SET,catalog-rules-ad_block,REJECT" in clash_payload["rules"]

    assert "DOMAIN-SUFFIX,ads.example.com,REJECT" in sr_text
    for line in sr_text.splitlines():
        if line.startswith("广告拦截 = select"):
            raise AssertionError("ad_block group should not render as a Shadowrocket proxy-group")

    assert "广告拦截 = select" not in surge_text
    assert "DOMAIN-SET,http://test/sub/device/t1/surge/domain-set/reject-domains.txt,REJECT,pre-matching" in surge_text
    assert surge_artifacts.domain_sets["reject-domains"] == ".ads.example.com\n"


def test_ad_block_lowering_preserves_rule_suffixes_for_clash_and_shadowrocket() -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
    ]
    rules = [
        "IP-CIDR,198.18.0.0/15,广告拦截,no-resolve",
        "DOMAIN-SUFFIX,ads.example.com,广告拦截",
    ]
    policy_ir = build_policy_ir(
        nodes,
        rules,
        business_groups=[
            BusinessGroup(
                name="广告拦截",
                sort_order=0,
                mode=BUSINESS_GROUP_MODE_AD_BLOCK,
            )
        ],
    )

    clash_text, _ = build_clash_config(nodes, rules, policy_ir=policy_ir)
    sr_text, _ = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf",
        policy_ir=policy_ir,
    )

    clash_payload = yaml.safe_load(clash_text)
    assert _without_udp_guards(clash_payload["rules"]) == [
        "RULE-SET,catalog-rules-ad_block,REJECT",
        "MATCH,兜底代理",
    ]
    assert build_clash_rule_provider_config(nodes, rules, "catalog-rules-ad_block", policy_ir=policy_ir) == (
        "DOMAIN-SUFFIX,ads.example.com\n"
        "IP-CIDR,198.18.0.0/15,no-resolve\n"
    )
    assert "IP-CIDR,198.18.0.0/15,REJECT,no-resolve" in sr_text
    assert "DOMAIN-SUFFIX,ads.example.com,REJECT" in sr_text


def test_surge_empty_pool_and_contract_hard_fail() -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_HIGH_PREMIUM,
        ),
    ]
    rules = ["DOMAIN-SUFFIX,youtube.com,高质量-低倍率"]

    artifacts = build_surge_profile_artifacts(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
        policy_ir=build_policy_ir(nodes, rules, contracts=_default_route_contracts()),
    )

    assert artifacts.blocked is True
    assert "高质量-低倍率·自动 = select, REJECT" in artifacts.main_conf
    assert "高质量-低倍率 = select, REJECT" in artifacts.main_conf
    assert any(item.code == "surge-referenced-empty-contract" and item.target == "高质量-低倍率" for item in artifacts.blockers)
    assert any(item.code == "empty-pool" and item.target == "高质量-低倍率" for item in artifacts.diagnostics)
    assert artifacts.referenced_contracts[0]["id"] == "hq_standard"
    assert artifacts.referenced_contracts[0]["rule_entry_count"] == 1


def test_surge_unused_empty_pool_is_not_blocking() -> None:
    nodes = [
        NodeRecord(
            name="m1",
            host="m.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        )
    ]
    rules = ["DOMAIN-SUFFIX,example.com,中等质量"]

    artifacts = build_surge_profile_artifacts(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
        policy_ir=build_policy_ir(nodes, rules, contracts=_default_route_contracts(), default_contract_id="medium"),
    )

    assert artifacts.blocked is False
    assert any(item.code == "empty-pool" and item.target == "高质量-低倍率" for item in artifacts.diagnostics)
    assert artifacts.blockers == []


def test_surge_empty_fallback_pool_only_warns_when_primary_pool_is_available() -> None:
    nodes = [
        NodeRecord(
            name="m1",
            host="m.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        )
    ]
    rules = ["DOMAIN-SUFFIX,example.com,中等质量"]
    contracts = _default_route_contracts()

    artifacts = build_surge_profile_artifacts(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
        policy_ir=build_policy_ir(nodes, rules, contracts=contracts, default_contract_id="medium"),
    )

    assert artifacts.blocked is False
    assert "中等质量 = fallback, 中等质量·自动, REJECT" in artifacts.main_conf
    assert any(item.code == "empty-pool" and item.target == "高质量-低倍率" for item in artifacts.diagnostics)
    assert all(item.target != "中等质量" for item in artifacts.blockers)


def test_surge_process_rule_reference_blocks_empty_contract() -> None:
    nodes = [
        NodeRecord(
            name="m1",
            host="m.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        )
    ]
    contracts = _default_route_contracts()
    policy_ir = build_policy_ir(nodes, [], contracts=contracts)
    policy_ir.process_rules = [
        ProcessRuleTemplate(
            id="pr1",
            contract_id="hq_standard",
            contract_display_name="高质量-低倍率",
            match_type="DOMAIN",
            value="Claude",
            enabled=True,
        )
    ]
    policy_ir.external_proxy_programs = [
        ExternalProxyProgramTemplate(
            id="ep1",
            contract_id="direct",
            contract_display_name="直连",
            program_path="/usr/bin/env",
            local_port=18080,
            enabled=True,
        )
    ]

    artifacts = build_surge_profile_artifacts(
        nodes,
        [],
        "http://test/sub/device/t1/surge.conf",
        policy_ir=policy_ir,
    )

    assert artifacts.blocked is True
    assert artifacts.referenced_contracts[0]["process_rule_count"] == 1
    assert artifacts.referenced_contracts[0]["external_proxy_program_count"] == 0


def test_surge_prunes_fully_covered_lower_priority_cidr_rules() -> None:
    rules = [
        "IP-CIDR,13.32.0.0/15,中等质量,no-resolve",
        "IP-CIDR,13.32.0.0/16,低质量大流量,no-resolve",
    ]

    artifacts = build_surge_profile_artifacts(
        [],
        rules,
        "http://test/sub/device/t1/surge.conf",
    )

    assert artifacts.blocked is False
    assert artifacts.rule_sets["ip-rules-medium"] == "IP-CIDR,13.32.0.0/15,no-resolve\n"
    assert "ip-rules-bulk" not in artifacts.rule_sets
    assert any(item.code == "surge-cidr-overlap-pruned" for item in artifacts.diagnostics)


def test_surge_splits_lower_priority_cidr_rules_into_non_overlapping_residuals() -> None:
    rules = [
        "IP-CIDR,13.32.0.0/16,高质量-低倍率,no-resolve",
        "IP-CIDR,13.32.0.0/15,低质量大流量,no-resolve",
    ]

    artifacts = build_surge_profile_artifacts(
        [],
        rules,
        "http://test/sub/device/t1/surge.conf",
    )

    assert artifacts.blocked is False
    assert artifacts.rule_sets["ip-rules-hq_standard"] == "IP-CIDR,13.32.0.0/16,no-resolve\n"
    assert artifacts.rule_sets["ip-rules-bulk"] == "IP-CIDR,13.33.0.0/16,no-resolve\n"
    assert any(item.code == "surge-cidr-overlap-split" for item in artifacts.diagnostics)
    assert not any(item.code == "surge-cidr-overlap-blocker" for item in artifacts.blockers)


def test_surge_src_cidr_rules_do_not_conflict_with_destination_cidr_rules() -> None:
    rules = [
        "SRC-IP-CIDR,13.32.0.0/16,中等质量,no-resolve",
        "IP-CIDR,13.32.0.0/15,低质量大流量,no-resolve",
    ]

    artifacts = build_surge_profile_artifacts(
        [],
        rules,
        "http://test/sub/device/t1/surge.conf",
    )

    assert artifacts.blocked is False
    assert "ip-rules-medium" not in artifacts.rule_sets
    assert any(w.code == "surge-rule-unsupported" for w in artifacts.diagnostics)
    assert artifacts.rule_sets["ip-rules-bulk"] == "IP-CIDR,13.32.0.0/15,no-resolve\n"


def test_surge_geoip_and_ip_asn_conflicts_are_resolved_by_identity_only() -> None:
    rules = [
        "GEOIP,US,中等质量",
        "GEOIP,US,低质量大流量",
        "IP-ASN,13335,中等质量,no-resolve",
        "IP-ASN,13335,高质量-低倍率,no-resolve",
    ]

    artifacts = build_surge_profile_artifacts(
        [],
        rules,
        "http://test/sub/device/t1/surge.conf",
    )

    assert artifacts.blocked is False
    assert artifacts.rule_sets["ip-rules-medium"] == "GEOIP,US\n"
    assert artifacts.rule_sets["ip-rules-hq_standard"] == "IP-ASN,13335,no-resolve\n"
    assert "ip-rules-bulk" not in artifacts.rule_sets
    assert [item.code for item in artifacts.diagnostics].count("conflicting-rule-target") >= 2


def test_surge_ruleset_assets_keep_domain_rules_ahead_of_keywords() -> None:
    rules = [
        "DOMAIN-KEYWORD,microsoft,低质量大流量",
        "DOMAIN,api.statsig.com,高质量-高倍率",
        "DOMAIN-SUFFIX,cloudflare.net,低质量大流量",
        "DOMAIN,chat.openai.com.cdn.cloudflare.net,高质量-高倍率",
    ]

    artifacts = build_surge_profile_artifacts(
        [],
        rules,
        "http://test/sub/device/t1/surge.conf",
    )
    main_lines = artifacts.main_conf.splitlines()
    premium_domain_idx = next(
        i
        for i, line in enumerate(main_lines)
        if "catalog-domains-hq_premium.txt,高质量-高倍率" in line
    )
    bulk_domain_idx = next(
        i
        for i, line in enumerate(main_lines)
        if "catalog-domains-bulk.txt,低质量大流量" in line
    )
    bulk_rule_idx = next(
        i
        for i, line in enumerate(main_lines)
        if "catalog-rules-bulk.list,低质量大流量" in line
    )

    assert premium_domain_idx < bulk_domain_idx < bulk_rule_idx
    assert artifacts.domain_sets["catalog-domains-hq_premium"] == "api.statsig.com\nchat.openai.com.cdn.cloudflare.net\n"
    assert artifacts.domain_sets["catalog-domains-bulk"] == ".cloudflare.net\n"
    assert artifacts.rule_sets["catalog-rules-bulk"] == "DOMAIN-KEYWORD,microsoft\n"


def test_surge_main_config_keeps_dns_trigger_ip_rules_at_rule_tail() -> None:
    nodes = [
        NodeRecord(
            name="premium-联通",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_HIGH_PREMIUM,
        ),
        NodeRecord(
            name="medium",
            host="b.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
    ]
    rules = [
        "DOMAIN-SUFFIX,openai.com,高质量-高倍率",
        "DOMAIN-KEYWORD,taobao,中等质量",
        "IP-CIDR,100.24.211.130/32,中等质量",
        "GEOIP,US,高质量-高倍率",
    ]
    policy_ir = build_policy_ir(nodes, rules)
    policy_ir.process_rules = [
        ProcessRuleTemplate(
            id="process-claude", contract_id="hq_premium", contract_display_name="高质量-高倍率",
            match_type="PROCESS-NAME", value="Claude", enabled=True,
        )
    ]

    artifacts = build_surge_profile_artifacts(
        nodes,
        rules,
        "https://review.example.com/sub/device/t1/surge.conf",
        policy_ir=policy_ir,
    )

    main_lines = artifacts.main_conf.splitlines()
    first_ip_ruleset_idx = next(
        idx
        for idx, line in enumerate(main_lines)
        if "/surge/rule-set/ip-rules-" in line
    )
    later_lines = main_lines[first_ip_ruleset_idx + 1 :]

    assert "PROCESS-NAME,Claude" not in artifacts.main_conf
    assert not any(line.startswith("DOMAIN-SET,") for line in later_lines)
    assert not any(line.startswith("PROCESS-") for line in later_lines)
    assert all(
        line.startswith("RULE-SET,") or line == "FINAL,兜底代理,dns-failed"
        for line in later_lines
    )
    assert later_lines[-1] == "FINAL,兜底代理,dns-failed"


def test_surge_main_profile_marks_mac_only_process_rules_as_overlay_only() -> None:
    nodes = [
        NodeRecord(
            name="p1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_HIGH_PREMIUM,
        ),
    ]
    policy_ir = build_policy_ir(
        nodes,
        ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"],
    )
    policy_ir.process_rules = [
        ProcessRuleTemplate(
            id="process-claude", contract_id="hq_premium", contract_display_name="高质量-高倍率",
            match_type="PROCESS-NAME", value="Claude", enabled=True,
        )
    ]

    artifacts = build_surge_profile_artifacts(
        nodes,
        policy_ir.rule_lines,
        "http://test/sub/device/t1/surge.conf",
        policy_ir=policy_ir,
    )

    assert "PROCESS-NAME,Claude" not in artifacts.main_conf
    assert any(item.code == "mac-only-rule-ignored" and item.severity == "info" for item in artifacts.diagnostics)


def test_surge_skips_vless_nodes() -> None:
    nodes = [
        NodeRecord(
            name="vless-1",
            host="vless.example.com",
            port=443,
            protocol="vless",
            quality_group=QUALITY_MEDIUM,
            raw={"uuid": "abc"},
            username="abc",
        ),
        NodeRecord(
            name="http-1",
            host="http.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_MEDIUM,
        ),
    ]
    surge_text, skipped = build_surge_config(
        nodes,
        ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"],
        "http://test/sub/device/t1/surge.conf",
    )
    assert "vless-1" in skipped
    assert "http-1 = http, http.example.com, 443" in surge_text


def test_surge_socks5_keeps_username_when_password_empty() -> None:
    nodes = [
        NodeRecord(
            name="gorelay-socks",
            host="socks.example.com",
            port=1080,
            protocol="socks5",
            quality_group=QUALITY_MEDIUM,
            username="gorelay-user",
            password="",
        ),
    ]

    surge_text, skipped = build_surge_config(
        nodes,
        [],
        "http://test/sub/device/t1/surge.conf",
    )

    assert skipped == []
    assert "gorelay-socks = socks5, socks.example.com, 1080, gorelay-user" in surge_text


def test_surge_maps_ss_obfs_plugin_fields() -> None:
    nodes = [
        NodeRecord(
            name="ss-obfs",
            host="ss.example.com",
            port=443,
            protocol="ss",
            quality_group=QUALITY_MEDIUM,
            password="p1",
            raw={
                "cipher": "aes-128-gcm",
                "password": "p1",
                "plugin": "obfs",
                "plugin-opts": {
                    "mode": "http",
                    "host": "plugin.example.com",
                    "path": "/surge-check",
                },
            },
        ),
    ]

    surge_text, skipped = build_surge_config(
        nodes,
        ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"],
        "http://test/sub/device/t1/surge.conf",
    )

    assert skipped == []
    assert _find_line(
        surge_text,
        "ss-obfs = ss, ss.example.com, 443",
    ) == (
        "ss-obfs = ss, ss.example.com, 443, encrypt-method=aes-128-gcm, password=p1, "
        "udp-relay=true, obfs=http, obfs-host=plugin.example.com, obfs-uri=/surge-check"
    )


def test_surge_skips_ss_nodes_with_unsupported_plugin() -> None:
    nodes = [
        NodeRecord(
            name="ss-plugin-unsupported",
            host="ss.example.com",
            port=443,
            protocol="ss",
            quality_group=QUALITY_MEDIUM,
            password="p1",
            raw={
                "cipher": "aes-128-gcm",
                "password": "p1",
                "plugin": "v2ray-plugin",
            },
        ),
    ]

    artifacts = build_surge_profile_artifacts(
        nodes,
        ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"],
        "http://test/sub/device/t1/surge.conf",
    )

    assert "ss-plugin-unsupported" in artifacts.skipped
    assert "ss-plugin-unsupported = ss," not in artifacts.main_conf
    assert any(
        item.code == "surge-unsupported-node"
        and "unsupported ss plugin v2ray-plugin" in item.message
        for item in artifacts.diagnostics
    )


def test_flowercloud_cache_sample_renders_obfs_for_surge() -> None:
    nodes = [
        NodeRecord(
            name="[FlowerCloud] 🇭🇰 香港高级 IEPL 专线 1",
            host="hk-node.example.com",
            port=12001,
            protocol="ss",
            quality_group=QUALITY_MEDIUM,
            password="test-password-1234",
            raw={
                "password": "test-password-1234",
                "cipher": "aes-128-gcm",
                "plugin": "obfs",
                "plugin-opts": {
                    "mode": "http",
                    "host": "obfs.example.com",
                },
                "udp": True,
            },
        ),
    ]

    surge_text, skipped = build_surge_config(
        nodes,
        ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"],
        "http://test/sub/device/t1/surge.conf",
    )

    assert skipped == []
    line = _find_line(
        surge_text,
        "[FlowerCloud] 🇭🇰 香港高级 IEPL 专线 1 = ss, hk-node.example.com, 12001",
    )
    assert "obfs=http" in line
    assert "obfs-host=obfs.example.com" in line


def test_build_configs_support_anytls_hysteria2_tuic() -> None:
    nodes = [
        NodeRecord(
            name="anytls-1",
            host="anytls.example.com",
            port=443,
            protocol="anytls",
            quality_group=QUALITY_MEDIUM,
            password="p1",
            raw={
                "password": "p1",
                "sni": "anytls.example.com",
                "alpn": ["h2"],
            },
        ),
        NodeRecord(
            name="hy2-1",
            host="hy2.example.com",
            port=8443,
            protocol="hysteria2",
            quality_group=QUALITY_MEDIUM,
            password="p2",
            raw={
                "password": "p2",
                "sni": "hy2.example.com",
                "obfs": "salamander",
                "obfs_password": "obfs-pass",
            },
        ),
        NodeRecord(
            name="tuic-1",
            host="tuic.example.com",
            port=9443,
            protocol="tuic",
            quality_group=QUALITY_MEDIUM,
            username="uuid-1",
            password="p3",
            raw={
                "uuid": "uuid-1",
                "password": "p3",
                "sni": "tuic.example.com",
                "congestion_controller": "bbr",
                "udp_relay_mode": "native",
            },
        ),
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]

    clash_text, clash_skipped = build_clash_config(nodes, rules)
    clash_provider_text, clash_provider_skipped = build_clash_provider_config(nodes, "medium")
    sr_text, sr_skipped = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf",
    )
    sr_nodes_text, sr_nodes_skipped = build_shadowrocket_nodes_subscription(nodes)
    surge_text, surge_skipped = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
    )

    assert clash_skipped == []
    assert clash_provider_skipped == []
    assert sr_skipped == []
    assert sr_nodes_skipped == []
    assert surge_skipped == []

    clash_payload = yaml.safe_load(clash_provider_text)
    types = {str(item.get("type", "")) for item in clash_payload.get("proxies", [])}
    assert "anytls" in types
    assert "hysteria2" in types
    assert "tuic" in types
    assert "proxy-providers" in yaml.safe_load(clash_text)

    assert "[Proxy]" in sr_text
    decoded_sr_nodes = base64.b64decode(sr_nodes_text.encode("ascii")).decode("utf-8")
    assert "anytls://p1@anytls.example.com:443" in decoded_sr_nodes
    assert "hysteria2://p2@hy2.example.com:8443" in decoded_sr_nodes
    assert "tuic://uuid-1:p3@tuic.example.com:9443" in decoded_sr_nodes

    assert "anytls, anytls.example.com, 443" in surge_text
    assert "hysteria2, hy2.example.com, 8443" in surge_text
    assert "tuic-v5, tuic.example.com, 9443" in surge_text
    assert "skip-cert-verify=false" in surge_text
    assert "obfs-password=obfs-pass" in surge_text
    assert "congestion-controller=bbr" in surge_text
    assert "udp-relay-mode=native" in surge_text


def test_build_configs_render_vless_extensions_and_tuic_v4_token() -> None:
    nodes = [
        NodeRecord(
            name="vless-1",
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
                    "short-id": "short",
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
                "udp_relay_mode": "native",
                "reduce_rtt": True,
            },
        ),
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]

    clash_text, clash_skipped = build_clash_config(nodes, rules)
    clash_provider_text, clash_provider_skipped = build_clash_provider_config(nodes, "medium")
    sr_nodes_text, sr_nodes_skipped = build_shadowrocket_nodes_subscription(nodes)
    surge_text, surge_skipped = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
    )

    assert clash_skipped == []
    assert clash_provider_skipped == []
    assert "tuic-v4" in sr_nodes_skipped
    assert "vless-1" in surge_skipped
    assert "tuic-v4" not in surge_skipped

    clash_provider_payload = yaml.safe_load(clash_provider_text)
    proxies = {item["name"]: item for item in clash_provider_payload.get("proxies", [])}
    assert proxies["vless-1"]["flow"] == "xtls-rprx-vision"
    assert proxies["vless-1"]["packet-encoding"] == "packetaddr"
    assert proxies["vless-1"]["reality-opts"] == {
        "public-key": "pub-key",
        "short-id": "short",
    }
    assert proxies["tuic-v4"]["token"] == "token-v4"
    assert proxies["tuic-v4"]["reduce-rtt"] is True

    decoded_sr_nodes = base64.b64decode(sr_nodes_text.encode("ascii")).decode("utf-8")
    assert "vless://uuid-vless@vless.example.com:443" in decoded_sr_nodes
    assert "tuic-v4" not in decoded_sr_nodes

    assert "token=token-v4" in surge_text
    assert "reduce-rtt=true" in surge_text


def test_build_configs_skip_mixed_tuic_v4_v5_credentials() -> None:
    nodes = [
        NodeRecord(
            name="tuic-mixed",
            host="tuic.example.com",
            port=9443,
            protocol="tuic",
            quality_group=QUALITY_MEDIUM,
            username="uuid-1",
            password="p1",
            raw={
                "token": "token-v4",
                "uuid": "uuid-1",
                "password": "p1",
            },
        )
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]

    _, clash_skipped = build_clash_config(nodes, rules)
    _, sr_skipped = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf",
    )
    _, surge_skipped = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
    )

    assert clash_skipped == ["tuic-mixed"]
    assert sr_skipped == ["tuic-mixed"]
    assert surge_skipped == ["tuic-mixed"]


def test_build_configs_skip_new_protocol_when_required_fields_missing() -> None:
    nodes = [
        NodeRecord(
            name="anytls-missing-pass",
            host="a.example.com",
            port=443,
            protocol="anytls",
            quality_group=QUALITY_MEDIUM,
            raw={},
        ),
        NodeRecord(
            name="tuic-missing-uuid",
            host="t.example.com",
            port=9443,
            protocol="tuic",
            quality_group=QUALITY_MEDIUM,
            password="p3",
            raw={"password": "p3"},
        ),
        NodeRecord(
            name="hy2-valid",
            host="h2.example.com",
            port=8443,
            protocol="hysteria2",
            quality_group=QUALITY_MEDIUM,
            password="p2",
            raw={"password": "p2"},
        ),
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]

    _, clash_skipped = build_clash_config(nodes, rules)
    _, sr_skipped = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf",
    )
    _, surge_skipped = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
    )

    for skipped in (clash_skipped, sr_skipped, surge_skipped):
        assert "anytls-missing-pass" in skipped
        assert "tuic-missing-uuid" in skipped
        assert "hy2-valid" not in skipped


def test_clash_provider_config_exports_only_requested_quality_group() -> None:
    nodes = [
        NodeRecord(name="p1", host="a.example.com", port=443, protocol="http", quality_group=QUALITY_HIGH_PREMIUM),
        NodeRecord(name="p2", host="b.example.com", port=443, protocol="http", quality_group=QUALITY_MEDIUM),
    ]
    provider_text, skipped = build_clash_provider_config(nodes, "medium")
    assert skipped == []
    payload = yaml.safe_load(provider_text)
    assert [item["name"] for item in payload["proxies"]] == ["p2"]


def test_clash_provider_config_applies_udp_defaults_and_explicit_overrides() -> None:
    nodes = [
        NodeRecord(
            name="ss-auto",
            host="ss.example.com",
            port=443,
            protocol="ss",
            quality_group=QUALITY_MEDIUM,
            password="p1",
            raw={"cipher": "aes-128-gcm", "password": "p1"},
        ),
        NodeRecord(
            name="anytls-default",
            host="anytls.example.com",
            port=443,
            protocol="anytls",
            quality_group=QUALITY_MEDIUM,
            password="p2",
            raw={"password": "p2"},
        ),
        NodeRecord(
            name="socks-default",
            host="socks.example.com",
            port=1080,
            protocol="socks5",
            quality_group=QUALITY_MEDIUM,
        ),
        NodeRecord(
            name="trojan-explicit-false",
            host="trojan.example.com",
            port=443,
            protocol="trojan",
            quality_group=QUALITY_MEDIUM,
            password="p3",
            raw={"password": "p3", "udp": False},
        ),
        NodeRecord(
            name="anytls-explicit-true",
            host="anytls-udp.example.com",
            port=443,
            protocol="anytls",
            quality_group=QUALITY_MEDIUM,
            password="p4",
            raw={"password": "p4", "udp": True},
        ),
    ]

    provider_text, skipped = build_clash_provider_config(nodes, "medium")

    assert skipped == []
    payload = yaml.safe_load(provider_text)
    by_name = {item["name"]: item for item in payload["proxies"]}
    assert by_name["ss-auto"]["udp"] is True
    assert by_name["anytls-default"]["udp"] is True
    assert by_name["socks-default"]["udp"] is True
    assert by_name["trojan-explicit-false"]["udp"] is False
    assert by_name["anytls-explicit-true"]["udp"] is True


def test_clash_provider_config_can_disable_udp_defaults_globally() -> None:
    nodes = [
        NodeRecord(
            name="ss-auto",
            host="ss.example.com",
            port=443,
            protocol="ss",
            quality_group=QUALITY_MEDIUM,
            password="p1",
            raw={"cipher": "aes-128-gcm", "password": "p1"},
        ),
    ]

    provider_text, skipped = build_clash_provider_config(
        nodes,
        "medium",
        udp_default_enabled=False,
    )

    assert skipped == []
    payload = yaml.safe_load(provider_text)
    assert payload["proxies"][0]["udp"] is False


def test_clash_provider_config_preserves_ss_plugin_fields() -> None:
    nodes = [
        NodeRecord(
            name="ss-plugin",
            host="ss.example.com",
            port=443,
            protocol="ss",
            quality_group=QUALITY_MEDIUM,
            password="p1",
            raw={
                "cipher": "aes-128-gcm",
                "password": "p1",
                "plugin": "obfs",
                "plugin-opts": {
                    "mode": "http",
                    "host": "plugin.example.com",
                },
            },
        ),
    ]

    provider_text, skipped = build_clash_provider_config(nodes, "medium")

    assert skipped == []
    payload = yaml.safe_load(provider_text)
    assert payload["proxies"][0]["plugin"] == "obfs"
    assert payload["proxies"][0]["plugin-opts"] == {
        "mode": "http",
        "host": "plugin.example.com",
    }


def test_build_clash_export_bundle_preserves_ss_plugin_fields_in_provider() -> None:
    nodes = [
        NodeRecord(
            name="medium-ss-plugin",
            host="medium.example.com",
            port=443,
            protocol="ss",
            quality_group=QUALITY_MEDIUM,
            password="p1",
            raw={
                "cipher": "aes-128-gcm",
                "password": "p1",
                "plugin": "obfs",
                "plugin-opts": {
                    "mode": "http",
                    "host": "plugin.example.com",
                },
            },
        ),
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]

    bundle = build_clash_export_bundle(
        nodes,
        rules,
        device_name="Mac",
        device_key="mac",
        subscription_token="tok1",
        generated_at="2026-03-10T01:10:49+08:00",
    )

    medium_provider = yaml.safe_load(bundle["files"]["providers/medium.yaml"])
    assert medium_provider["proxies"][0]["plugin"] == "obfs"
    assert medium_provider["proxies"][0]["plugin-opts"] == {
        "mode": "http",
        "host": "plugin.example.com",
    }


def test_build_clash_export_bundle_uses_file_providers_and_strips_render_warnings() -> None:
    nodes = [
        NodeRecord(
            name="premium-1",
            host="premium.example.com",
            port=443,
            protocol="ss",
            quality_group=QUALITY_HIGH_PREMIUM,
            password="p1",
            raw={"cipher": "aes-128-gcm", "password": "p1"},
        ),
        NodeRecord(
            name="medium-1",
            host="medium.example.com",
            port=443,
            protocol="anytls",
            quality_group=QUALITY_MEDIUM,
            password="p2",
            raw={"password": "p2"},
        ),
    ]
    rules = [
        "DOMAIN,103.224.182.210,低质量大流量",
        "IP-CIDR,103.224.182.210/32,高质量-高倍率,no-resolve",
    ]

    bundle = build_clash_export_bundle(
        nodes,
        rules,
        device_name="Mac",
        device_key="mac",
        subscription_token="tok1",
        generated_at="2026-03-10T01:10:49+08:00",
    )

    assert sorted(bundle["files"]) == sorted(path for path in CLASH_BUNDLE_FILES if path != "AUDIT.md")
    clash_payload = yaml.safe_load(bundle["files"]["clash.yaml"])
    assert clash_payload["proxy-providers"]["high-premium"] == {
        "type": "file",
        "path": "./providers/high-premium.yaml",
        "proxy": "DIRECT",
    }
    assert clash_payload["proxy-providers"]["medium"] == {
        "type": "file",
        "path": "./providers/medium.yaml",
        "proxy": "DIRECT",
    }
    assert clash_payload["proxy-providers"]["chain-home"] == {
        "type": "file",
        "path": "./providers/chain-home.yaml",
        "proxy": "DIRECT",
    }
    assert "render-warnings" not in clash_payload
    assert clash_payload["mixed-port"] == 7890
    use_providers = {
        provider_key
        for item in clash_payload["proxy-groups"]
        for provider_key in list(item.get("use") or [])
    }
    assert use_providers
    assert use_providers <= set(clash_payload["proxy-providers"])
    medium_provider = yaml.safe_load(bundle["files"]["providers/medium.yaml"])
    assert medium_provider["proxies"][0]["udp"] is True
    premium_provider = yaml.safe_load(bundle["files"]["providers/high-premium.yaml"])
    assert premium_provider["proxies"][0]["udp"] is True
    chain_provider = yaml.safe_load(bundle["files"]["providers/chain-home.yaml"])
    assert chain_provider["proxies"] == []
    manifest = yaml.safe_load(bundle["files"]["manifest.json"])
    assert manifest["kernel_target"] == "mihomo-meta"
    assert "Mihomo / Clash Meta only" in manifest["compatibility_note"]
    assert "compatibility: Mihomo / Clash Meta only" in bundle["files"]["README.txt"]

    audit_md = build_clash_audit_markdown(bundle, profile="lazycat", base_url="http://test")
    assert "render-warnings stripped: yes" in audit_md
    assert "file-provider paths consistent: yes" in audit_md
    assert "mixed-port present: yes" in audit_md
    assert "UDP explicit on supported proxies: yes" in audit_md
    assert "group health-check coverage present: yes" in audit_md
    assert "use-groups covered by group or provider health-check: yes" in audit_md
    assert "residual CIDR overlap count: 0" in audit_md


def test_high_quality_names_render_consistently_across_clients() -> None:
    nodes = [
        NodeRecord(
            name="[机场A] 🇺🇸 美国 · 双线 · 10x · 广港 IEPL",
            host="hq.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_HIGH_PREMIUM,
        ),
    ]
    rules = ["DOMAIN-SUFFIX,openai.com,高质量-高倍率"]

    provider_text, provider_skipped = build_clash_provider_config(nodes, "high-premium")
    sr_text, sr_skipped = build_shadowrocket_config(
        nodes,
        rules,
        "http://test/sub/device/t1/shadowrocket.conf",
    )
    sr_nodes_text, sr_nodes_skipped = build_shadowrocket_nodes_subscription(nodes)
    surge_text, surge_skipped = build_surge_config(
        nodes,
        rules,
        "http://test/sub/device/t1/surge.conf",
    )

    assert provider_skipped == []
    assert sr_skipped == []
    assert sr_nodes_skipped == []
    assert surge_skipped == []

    provider_payload = yaml.safe_load(provider_text)
    assert provider_payload["proxies"][0]["name"] == "[机场A] 🇺🇸 美国 · 双线 · 10x · 广港 IEPL"
    assert "[Proxy]" in sr_text
    assert "[Proxy Group]" in sr_text
    node_line = base64.b64decode(sr_nodes_text).decode("utf-8")
    assert unquote(node_line.split("#", 1)[1]) == "高质量-高倍率 | [机场A] 🇺🇸 美国 · 双线 · 10x · 广港 IEPL"
    assert "[机场A] 🇺🇸 美国 · 双线 · 10x · 广港 IEPL = http, hq.example.com, 443" in surge_text


def test_build_device_import_links_contains_surge_fields() -> None:
    links = build_device_import_links("http://test", "Mac", "tok1")
    assert re.fullmatch(r"http://test/sub/device/tok1/shadowrocket-[a-f0-9]{16}\.conf", links["shadowrocket_url"])
    assert links["shadowrocket_nodes_url"] == "http://test/sub/device/tok1/shadowrocket-nodes.txt"
    assert "shadowrocket_legacy_url" not in links
    assert links["shadowrocket_scheme"] == "shadowrocket://config/add/" + links["shadowrocket_url"]
    assert links["surge_url"] == "http://test/sub/device/tok1/surge.conf"
    assert links["surge_mac_overlay_url"] == "http://test/sub/device/tok1/surge-mac-overlay.conf"
    assert links["clash_url"] == "http://test/sub/device/tok1/clash.yaml"
    assert links["surge_scheme"].startswith("surge:///install-config?url=")
    assert "name=SubHub%20for%20Mac" in links["clash_scheme"]
    assert "?name=" not in links["shadowrocket_scheme"]
    assert "name=SubHub%20for%20Mac" in links["surge_scheme"]
    assert "profile%3D" not in links["clash_scheme"]
    assert "flavor%3D" not in links["clash_scheme"]
    assert "profile%3D" not in links["shadowrocket_scheme"]
    assert "flavor%3D" not in links["shadowrocket_scheme"]
    assert "profile%3D" not in links["surge_scheme"]
    assert "flavor%3D" not in links["surge_scheme"]
    assert links["surge_mac_overlay_scheme"].startswith("surge:///install-config?url=")


def test_shadowrocket_nodes_subscription_exports_base64_uri_lines() -> None:
    nodes = [
        NodeRecord(
            name="n1",
            host="a.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_HIGH_PREMIUM,
        ),
        NodeRecord(
            name="n1",
            host="b.example.com",
            port=443,
            protocol="trojan",
            quality_group=QUALITY_HIGH_PREMIUM,
            password="secret",
            raw={"password": "secret", "sni": "b.example.com"},
        ),
    ]
    encoded, skipped = build_shadowrocket_nodes_subscription(nodes)
    assert skipped == []
    decoded = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
    assert (
        "%E9%AB%98%E8%B4%A8%E9%87%8F-%E9%AB%98%E5%80%8D%E7%8E%87%20%7C%20n1"
        in decoded
    )
    assert (
        "%E9%AB%98%E8%B4%A8%E9%87%8F-%E9%AB%98%E5%80%8D%E7%8E%87%20%7C%20n1%20%282%29"
        in decoded
    )
    assert "http://a.example.com:443#" in decoded
    assert "trojan://secret@b.example.com:443" in decoded


def test_shadowrocket_nodes_subscription_encodes_ss_obfs_plugin_query() -> None:
    nodes = [
        NodeRecord(
            name="ss-obfs",
            host="ss.example.com",
            port=443,
            protocol="ss",
            quality_group=QUALITY_MEDIUM,
            password="p1",
            raw={
                "cipher": "aes-128-gcm",
                "password": "p1",
                "plugin": "obfs",
                "plugin-opts": {
                    "mode": "http",
                    "host": "plugin.example.com",
                    "path": "/shadowrocket-check",
                },
            },
        ),
    ]

    encoded, skipped = build_shadowrocket_nodes_subscription(nodes)

    assert skipped == []
    decoded = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
    parsed = urlparse(decoded.strip())
    assert parsed.scheme == "ss"
    assert parsed.path == "/"
    assert parse_qs(parsed.query) == {
        "plugin": [
            "obfs-local;obfs=http;obfs-host=plugin.example.com;obfs-uri=/shadowrocket-check"
        ]
    }


def test_shadowrocket_nodes_subscription_wraps_ipv6_authority_hosts() -> None:
    nodes = [
        NodeRecord(
            name="ipv6-socks",
            host="2409:8754:1410:8014:0:2101:0:100a",
            port=16562,
            protocol="socks5",
            quality_group=QUALITY_MEDIUM,
            username="9288a9ab",
        ),
        NodeRecord(
            name="ipv6-trojan",
            host="2001:db8::9",
            port=443,
            protocol="trojan",
            quality_group=QUALITY_HIGH_PREMIUM,
            password="secret",
            raw={"password": "secret"},
        ),
    ]

    encoded, skipped = build_shadowrocket_nodes_subscription(nodes)

    assert skipped == []
    decoded = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
    assert "socks5://9288a9ab@[2409:8754:1410:8014:0:2101:0:100a]:16562" in decoded
    assert "trojan://secret@[2001:db8::9]:443" in decoded
    parsed = [urlparse(line) for line in decoded.splitlines()]
    assert parsed[0].hostname == "2409:8754:1410:8014:0:2101:0:100a"
    assert parsed[0].port == 16562
    assert parsed[1].hostname == "2001:db8::9"
    assert parsed[1].port == 443


def test_subscription_display_name_normalizes_device_names() -> None:
    assert build_subscription_display_name("Mac") == "SubHub for Mac"
    assert build_subscription_display_name("Mac mini") == "SubHub for Mac mini"
    assert build_subscription_display_name(" Lzcbox ") == "SubHub for Lzcbox"
    assert build_subscription_display_name("") == "SubHub"
    assert build_subscription_display_name("Mac.yaml") == "SubHub for Mac"


def test_shadowrocket_subscription_name_is_stable() -> None:
    assert build_shadowrocket_subscription_name("Mac mini") == "SubHub for Mac mini"


def test_shadowrocket_nodes_subscription_excludes_chain_home_nodes() -> None:
    medium = NodeRecord(
        name="medium-front",
        host="front.example.com",
        port=443,
        protocol="http",
        quality_group=QUALITY_MEDIUM,
    )
    chain = NodeRecord(
        name="链式家宽 | 家宽1",
        host="rear.example.com",
        port=1080,
        protocol="socks5",
        quality_group=QUALITY_CHAIN_HOME,
        raw={"chain_home": True, "chain_rear_target": "rear.example.com:1080"},
    )
    encoded, skipped = build_shadowrocket_nodes_subscription([medium, chain])
    decoded = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
    assert skipped == []
    assert "front.example.com" in decoded
    assert "rear.example.com" not in decoded
