"""Client compiler regressions; all data is synthetic and provider checks are opt-in."""
import pytest
from fastapi import HTTPException

from app.routes.management import _normalize_manual_category_rules, ManualCategoryRulePayload


def test_manual_category_rejects_unknown_rule_type():
    with pytest.raises(HTTPException) as exc:
        _normalize_manual_category_rules([ManualCategoryRulePayload(rule_type="BOGUS", value="example.com")])
    assert exc.value.status_code == 400

import base64
import os
import re
import subprocess
from pathlib import Path
from dataclasses import replace

import yaml

from app.models import NodeRecord, PolicyRuleEntry, QUALITY_MEDIUM
from app.services import subscription_builder as builder
from app.services.lazycat_profile import validate_lazycat_profile_settings_for_write
from app.services.source_fetcher import _METHOD_USER_AGENTS, _CLASH_USER_AGENTS
from app.services.subscription_country_rules import detect_node_country, country_regex, known_country_regex

KEY = base64.b64encode(bytes(range(32))).decode()
UUID = "11111111-2222-4333-8444-555555555555"
URL = "https://sub.example.com/sub/device/fake/default/shadowrocket.conf"


def fake_node(name="USA-01", protocol="ss", **raw):
    if protocol == "ss":
        raw = {"cipher": "aes-128-gcm", **raw}
    return NodeRecord(name=name, host="node.example.com", port=443, protocol=protocol,
                      username=UUID, password="fake-password", quality_group=QUALITY_MEDIUM, raw=raw)


def clash(nodes=None, rules=None, settings=None, **kwargs):
    text, skipped, warnings = builder.build_clash_profile_artifacts(
        [fake_node()] if nodes is None else nodes, rules or [], profile="lazycat",
        profile_settings=settings, provider_base_url="https://sub.example.com", subscription_token="fake",
        **kwargs,
    )
    return yaml.safe_load(text), skipped, warnings


@pytest.mark.parametrize("name,country", [
    ("USA-01", "美国"), ("United States 02", "美国"), ("US01", "美国"),
    ("US_01", "美国"), ("中文US中文", "美国"), ("Japan 01", "日本"),
    ("Busan 01", "其他"), ("aUSA-01", "其他"), ("USAwest", "其他"),
    ("美国 01", "美国"), ("🇺🇸 美国 01", "美国"), ("🇯🇵 Japan", "日本"),
    # Bare flags had no alias in the original compiler; keep that behavior.
    ("🇺🇸 01", "其他"),
])
def test_01_country_filters_match_python_classifier(name, country):
    assert detect_node_country(name) == country
    assert bool(re.search(known_country_regex(), name)) == (country != "其他")
    if country != "其他":
        assert re.search(country_regex(country), name)


def test_01_country_groups_three_clients_use_same_buckets():
    nodes = [fake_node(name) for name in ("USA-01", "United States 02", "Japan 01", "Busan 01")]
    payload, _, _ = clash(nodes)
    groups = {g["name"]: g for g in payload["proxy-groups"]}
    assert groups["中等质量·美国"]["filter"].startswith("(?i)")
    assert groups["中等质量·其他"]["exclude-filter"] == known_country_regex()
    for render in (builder.build_shadowrocket_config, builder.build_surge_config):
        text, _ = render(nodes, [], URL)
        us = next(line for line in text.splitlines() if line.startswith("中等质量·美国 ="))
        assert "USA-01" in us and "United States 02" in us and "Busan 01" not in us


def test_02_wireguard_family_strings_udp_and_extra_diagnostic():
    node = fake_node(protocol="wireguard", **{"private-key": KEY, "public-key": KEY,
        "address": ["fd00::2/128", "10.8.0.2/32", "10.8.0.3"], "ip6": ["fd00::3"]})
    proxy = builder._clash_proxy(node)
    assert proxy["ip"] == "10.8.0.2" and proxy["ipv6"] == "fd00::2"
    assert "ip6" not in proxy and proxy["udp"] is True
    assert builder.derive_protocol_diagnostics([node], [], target="clash")[0].code == "clash-wireguard-addresses-dropped"
    assert builder._clash_proxy(replace(node, raw={**node.raw, "udp": False}))["udp"] is False


@pytest.mark.parametrize("key", ["ip", "address", "ip6", "ipv6"])
def test_02_wireguard_input_aliases(key):
    proxy = builder._clash_proxy(fake_node(protocol="wireguard", **{"private-key": KEY, "public-key": KEY, key: ["10.8.0.2", "fd00::2"]}))
    assert proxy["ip"] == "10.8.0.2" and proxy["ipv6"] == "fd00::2"


def test_03_22_fail_closed_groups_single_health_owner_and_download_path():
    payload, _, warnings = clash()
    assert "render-warnings" not in payload
    assert warnings  # management diagnostics remain available
    for group in payload["proxy-groups"]:
        if group.get("use") or group.get("exclude-filter"):
            assert group["empty-fallback"] == "REJECT"
    for section in ("proxy-providers", "rule-providers"):
        for provider in payload[section].values():
            assert provider["proxy"] == "DIRECT"
            assert "health-check" not in provider
    _, blockers = builder._clash_provider_health_check_findings(payload["proxy-providers"], payload["proxy-groups"])
    assert blockers == []
    broken = [{**g, "url": ""} for g in payload["proxy-groups"]]
    assert builder._clash_provider_health_check_findings(payload["proxy-providers"], broken)[1]


def test_04_cache_path_stable_revision_url_changes_and_scenarios_isolated():
    before, _, _ = clash()
    after, _, _ = clash([fake_node("USA-new")])
    left, right = before["proxy-providers"]["medium"], after["proxy-providers"]["medium"]
    assert left["path"] == right["path"] and left["url"] != right["url"]
    a, _, _ = clash(provider_url_builder=lambda key, rev: f"https://sub.example.com/default/{key}?rev={rev}")
    b, _, _ = clash(provider_url_builder=lambda key, rev: f"https://sub.example.com/travel/{key}?rev={rev}")
    assert a["proxy-providers"]["medium"]["path"] != b["proxy-providers"]["medium"]["path"]
    assert "fake" not in left["path"]
    assert builder._clash_rule_provider_cache_path("fake", "asset", revision="a") == builder._clash_rule_provider_cache_path("fake", "asset", revision="b")


def test_05_surge_vmess_aead_and_legacy_refusal():
    node = fake_node(protocol="vmess", uuid=UUID, cipher="auto")
    text, skipped = builder.build_surge_config([node], [], URL)
    assert skipped == [] and "vmess-aead=true" in text and "encrypt-method=auto" not in text
    artifact = builder.build_surge_profile_artifacts([replace(node, raw={**node.raw, "alterId": 32})], [], URL)
    assert artifact.skipped == [node.name]
    assert any("legacy alterId" in w.message for w in artifact.diagnostics)


def test_06_08_surge_tuic_versions_and_rocket_version():
    v5 = fake_node(protocol="tuic", uuid=UUID, password="fake-password", version=5)
    v4 = replace(v5, username="", password="", raw={"token": "fake-token", "version": 4})
    for node, kind in ((v4, "tuic"), (v5, "tuic-v5")):
        text, skipped = builder.build_surge_config([node], [], URL)
        assert skipped == [] and f" = {kind}, node.example.com" in text
    text, skipped = builder.build_shadowrocket_config([v5], [], URL)
    assert skipped == [] and "version=5" in text and "tuic-v5," not in text


def test_07_surge_wireguard_proxy_reference_section_and_missing_dns():
    node = fake_node("WG", "wireguard", **{"private-key": KEY, "public-key": KEY,
        "ip": ["10.8.0.2", "fd00::2"], "dns": ["10.8.0.1"], "mtu": 1280})
    text, skipped = builder.build_surge_config([node], [], URL)
    assert skipped == [] and "WG = wireguard, section-name=WG" in text
    assert "[WireGuard WG]" in text and "self-ip = 10.8.0.2" in text and "self-ip-v6 = fd00::2" in text
    assert "peer = (public-key = " in text and "endpoint = node.example.com:443)" in text
    assert "dns-server = 10.8.0.1" in text and "mtu = 1280" in text
    artifact = builder.build_surge_profile_artifacts([replace(node, raw={k:v for k,v in node.raw.items() if k != "dns"})], [], URL)
    assert artifact.skipped == ["WG"] and any("source DNS is required" in w.message for w in artifact.diagnostics)


@pytest.mark.parametrize("key", ["clash_dns_nameserver", "clash_dns_default_nameserver", "clash_dns_proxy_server_nameserver"])
def test_09_empty_dns_write_rejected_legacy_render_restored(key):
    for empty in ([], "", [" "]):
        with pytest.raises(ValueError):
            validate_lazycat_profile_settings_for_write({key: empty})
    payload, _, warnings = clash(settings={key: []})
    assert payload["dns"][key.removeprefix("clash_dns_").replace("_", "-")]
    assert any(w.code == "clash-dns-empty-defaulted" and w.target == key for w in warnings)


def test_09_empty_optional_general_lines_omitted():
    settings = {"surge_always_real_ip": [], "surge_tun_excluded_routes": [], "surge_dns_server": [],
                "surge_encrypted_dns_server": [], "shadowrocket_always_real_ip": [], "shadowrocket_tun_excluded_routes": []}
    for render in (builder.build_surge_config, builder.build_shadowrocket_config):
        text, _ = render([fake_node()], [], URL, profile="lazycat", profile_settings=settings)
        assert not re.search(r"^\S+\s*=\s*$", text, re.M)


def test_10_rule_dialects_assets_preserve_resolution_parameters():
    entries = [PolicyRuleEntry("medium", t, v, source_kind="custom") for t,v in [
        ("DST-PORT", "8443"), ("IP-CIDR", "198.51.100.0/24"), ("IP-CIDR6", "2001:db8::/32"),
        ("IP-ASN", "64500"), ("GEOIP", "CN"), ("GEOSITE", "cn"), ("SRC-IP-CIDR", "10.0.0.0/8")]]
    ir = builder.build_policy_ir([fake_node()], [], rule_entries=entries)
    artifact = builder.build_surge_profile_artifacts(ir.nodes, [], URL, policy_ir=ir)
    rules = "\n".join(artifact.rule_sets.values())
    assert "DEST-PORT,8443" in rules and "DST-PORT" not in rules
    assert "GEOSITE" not in rules and "SRC-IP-CIDR" not in rules
    assert sum(w.code == "surge-rule-unsupported" for w in artifact.diagnostics) == 2
    for line in rules.splitlines():
        if line.startswith(("IP-CIDR,", "IP-CIDR6,", "IP-ASN,")):
            assert not line.endswith(",no-resolve")
        if line.startswith("GEOIP,"):
            assert line == "GEOIP,CN"
    lowered, warnings = builder._lower_policy_entries_for_client([
        PolicyRuleEntry("REJECT-DICT", "DEST-PORT", "8443")], client="clash")
    assert lowered[0].rule_type == "DST-PORT" and lowered[0].target_contract_id == "REJECT"
    assert warnings[0].code == "clash-reject-downgraded"
    rocket, _ = builder.build_shadowrocket_config(ir.nodes, [], URL, policy_ir=ir)
    assert "GEOIP,CN,中等质量\n" in rocket
    assert "IP-ASN,64500,中等质量\n" in rocket
    direct, _ = builder._lower_policy_entries_for_client([PolicyRuleEntry("DIRECT", "GEOIP", "CN")], client="shadowrocket")
    assert direct[0].to_line(target_name="DIRECT") == "GEOIP,CN,DIRECT"


@pytest.mark.parametrize("client", ["clash", "surge", "shadowrocket"])
def test_round2_no_resolve_matches_45b792d(client):
    # Captured from 45b792d; no git or historical renderer needed in CI.
    predicates = [
        ("IP-CIDR", "198.51.100.0/24", []),
        ("IP-CIDR6", "2001:db8::/32", []),
        ("IP-ASN", "64500", []),
        ("GEOIP", "CN", []),
        ("IP-CIDR", "203.0.113.0/24", ["no-resolve"]),
        ("IP-CIDR6", "2001:db9::/32", ["no-resolve"]),
        ("IP-ASN", "64501", ["no-resolve"]),
        ("GEOIP", "US", ["no-resolve"]),
        ("AND", "((IP-CIDR,192.0.2.1/32))", []),
        ("OR", "((IP-CIDR6,2001:dba::/32),(IP-ASN,64502,no-resolve))", []),
        ("NOT", "((IP-CIDR,192.0.2.2/32,no-resolve))", []),
    ]
    expected = [
        "IP-CIDR,198.51.100.0/24",
        "IP-CIDR6,2001:db8::/32",
        "IP-ASN,64500",
        "GEOIP,CN",
        "IP-CIDR,203.0.113.0/24,no-resolve",
        "IP-CIDR6,2001:db9::/32,no-resolve",
        "IP-ASN,64501,no-resolve",
        "GEOIP,US,no-resolve",
        "AND,((IP-CIDR,192.0.2.1/32))",
        "OR,((IP-CIDR6,2001:dba::/32),(IP-ASN,64502,no-resolve))",
        "NOT,((IP-CIDR,192.0.2.2/32,no-resolve))",
    ]
    if client == "clash":
        expected[:2] = ["IP-CIDR,198.51.100.0/24,no-resolve", "IP-CIDR6,2001:db8::/32,no-resolve"]
    entries = [PolicyRuleEntry("action-direct", t, v, extras=x, source_kind="custom") for t, v, x in predicates]
    ir = builder.build_policy_ir([fake_node()], [], rule_entries=entries, default_contract_id="action-direct")
    if client == "surge":
        artifact = builder.build_surge_profile_artifacts(ir.nodes, [], URL, policy_ir=ir)
        actual = "\n".join(artifact.rule_sets.values()).splitlines()
    else:
        if client == "clash":
            payload, _, _ = clash(policy_ir=ir, render_mode="export")
            rules = [line for line in payload["rules"] if not line.startswith(("NETWORK,UDP,", "MATCH,"))]
        else:
            text, _ = builder.build_shadowrocket_config(ir.nodes, [], URL, policy_ir=ir)
            rules = text.split("[Rule]\n")[1].strip().splitlines()[:-1]
        actual = []
        for line in rules:
            parts = builder._split_rule_parts(line)
            assert parts[2] == "DIRECT"
            actual.append(",".join([*parts[:2], *parts[3:]]))
    assert sorted(line for line in actual if line) == sorted(expected)


@pytest.mark.parametrize("client", ["clash", "surge", "shadowrocket"])
@pytest.mark.parametrize("kind,value", [("UID", "1000"), ("AND", "((UID,1000),(DOMAIN,example.com))")])
def test_round2_uid_unknown_target_refused_with_migration(client, kind, value):
    entries, warnings = builder._lower_policy_entries_for_client([PolicyRuleEntry("medium", kind, value)], client=client)
    assert entries == []
    assert warnings[0].code == f"{client}-rule-unsupported"
    assert warnings[0].bucket == "refused"
    assert "target OS is unknown" in warnings[0].message
    assert "migrate" in warnings[0].message and "Stored rules are unchanged" in warnings[0].message


@pytest.mark.parametrize("target", ["REJECT-DROP", "REJECT-NO-DROP", "REJECT-TINYGIF"])
def test_round2_native_reject_complete_rendering(target):
    from app.storage.sqlite_repo import _default_route_contracts

    rules = [f"DOMAIN,ads.example.com,{target}"]
    ir = builder.build_policy_ir([fake_node()], rules, contracts=_default_route_contracts(), default_contract_id="medium")
    artifact = builder.build_surge_profile_artifacts(ir.nodes, rules, URL, policy_ir=ir)
    assert artifact.blocked is False and artifact.blockers == []
    assert any(line.startswith("DOMAIN-SET,") and line.endswith(f",{target}") for line in artifact.main_conf.splitlines())
    assert "ads.example.com\n" in artifact.domain_sets.values()
    assert not any(w.code == "surge-reject-downgraded" for w in artifact.diagnostics)
    text, _ = builder.build_shadowrocket_config(ir.nodes, rules, URL, policy_ir=ir)
    assert f"DOMAIN,ads.example.com,{target}\n" in text
    payload, _, warnings = clash(rules=rules, policy_ir=ir, render_mode="export")
    expected = target if target == "REJECT-DROP" else "REJECT"
    assert f"DOMAIN,ads.example.com,{expected}" in payload["rules"]
    assert not builder.build_clash_blocked_detail(ir)["blockers"]
    assert any(w.code == "clash-reject-downgraded" for w in warnings) == (expected != target)


@pytest.fixture
def round2_device(client, monkeypatch):
    from app.models import DeviceSubscription, StandardSource

    services = client.app.state.services

    async def no_refresh(force=False):
        return services.hub_service.runtime

    monkeypatch.setattr(services.hub_service, "refresh", no_refresh)
    # A Linux-looking label is not proof of the consuming kernel's OS.
    services.repo.save_device_subscription(DeviceSubscription(
        id="round2", device_key="linux", device_name="Linux", token="round2-fake", enabled=True))
    services.repo.save_standard_source(StandardSource(
        id="round2", name="Synthetic", quality_group=QUALITY_MEDIUM,
        ingest_kind="manual_nodes", manual_nodes_text="synthetic", enabled=True))
    services.repo.save_standard_node_cache("round2", [replace(fake_node(), source_id="round2", source_type="standard")])
    return services


def test_round2_legacy_uid_http_export_and_diagnostics(client, round2_device, tmp_path):
    import io
    import zipfile
    from app.models import CustomRule

    assert client.post("/api/rules/categories/manual", json={"name": "legacy-uid", "default_policy": "direct"}).status_code == 200
    round2_device.repo.save_custom_rule(CustomRule(
        id="legacy-uid", rule_type="UID", value="1000", category_name="legacy-uid", target_group=""))
    response = client.get("/api/devices/round2-fake/export/clash-bundle.zip")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extractall(tmp_path / "bundle")
        assert "UID," not in archive.read("clash.yaml").decode()
        audit = archive.read("AUDIT.md").decode()
        assert "clash-rule-unsupported" in audit and "UID" in audit and "migrate" in audit
    for target in ("clash", "surge", "shadowrocket"):
        preview = client.get(f"/api/devices/round2-fake/preview-summary?target={target}")
        assert preview.status_code == 200
        assert any(w["code"] == f"{target}-rule-unsupported" and "migrate" in w["message"]
                   for w in preview.json()["summary"]["warnings"])
    assert any(r.id == "legacy-uid" and r.rule_type == "UID" for r in round2_device.repo.list_custom_rules())
    binary = os.environ.get("MIHOMO_BIN")
    if binary:
        bundle = tmp_path / "bundle"
        parsed = subprocess.run([binary, "-t", "-d", str(bundle), "-f", str(bundle / "clash.yaml")], capture_output=True, text=True, timeout=20)
        assert parsed.returncode == 0, parsed.stdout + parsed.stderr


@pytest.mark.parametrize("target", ["REJECT-DROP", "REJECT-NO-DROP", "REJECT-TINYGIF"])
def test_round2_native_reject_http_no_409(client, round2_device, monkeypatch, target):
    rules = [f"DOMAIN,ads.example.com,{target}"]
    ir = builder.build_policy_ir([fake_node()], rules, contracts=round2_device.repo.list_route_contracts(), default_contract_id="medium")
    original = builder.build_surge_profile_artifacts

    def render(*args, **kwargs):
        # Exercise the real HTTP blocker boundary with a native rule in PolicyIR.
        kwargs["policy_ir"] = ir
        return original(*args, **kwargs)

    monkeypatch.setattr("app.routes.subscription.build_surge_profile_artifacts", render)
    response = client.get("/sub/device/round2-fake/default/surge.conf")
    assert response.status_code == 200, response.text
    assert f",{target}\n" in response.text


@pytest.mark.skipif(not os.environ.get("MIHOMO_BIN"), reason="MIHOMO_BIN is not configured")
def test_round2_domain_ip_condition_routes_to_policy_after_startup(tmp_path):
    import http.server
    import json
    import socket
    import struct
    import threading
    import time
    import urllib.request

    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    hits = []
    served = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith("/probe"):
                hits.append(self.path)
                body = "DIRECT"
            else:
                key = self.path.rsplit("/", 1)[-1].split("?")[0].removesuffix(".yaml")
                body = served.get(key, "")
            self.send_response(200 if body else 404)
            self.end_headers()
            self.wfile.write(body.encode())

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.bind(("127.0.0.1", 0))
    dns.settimeout(0.1)
    stopped = threading.Event()

    def resolve():
        while not stopped.is_set():
            try:
                packet, peer = dns.recvfrom(4096)
            except TimeoutError:
                continue
            pos = 12
            while packet[pos]:
                pos += 1 + packet[pos]
            pos += 1
            qtype = struct.unpack("!H", packet[pos:pos + 2])[0]
            answer = (b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 0, 4) + socket.inet_aton("127.0.0.1")) if qtype == 1 else b""
            dns.sendto(packet[:2] + struct.pack("!HHHHH", 0x8180, 1, bool(answer), 0, 0) + packet[12:pos + 4] + answer, peer)

    thread = threading.Thread(target=resolve, daemon=True)
    thread.start()
    proc = None
    try:
        nodes = [replace(fake_node("Proxy"), host="127.0.0.1", port=1)]
        ir = builder.build_policy_ir(nodes, [], rule_entries=[
            PolicyRuleEntry("medium", "AND", "((IP-CIDR,127.0.0.1/32))", source_kind="system")], default_contract_id="action-direct")
        resolver = f"udp://127.0.0.1:{dns.getsockname()[1]}"
        text, _, _ = builder.build_clash_profile_artifacts(nodes, [], policy_ir=ir, profile="lazycat", profile_settings={
            "clash_dns_nameserver": [resolver], "clash_dns_default_nameserver": ["127.0.0.1"],
            "clash_dns_proxy_server_nameserver": [resolver], "clash_dns_fallback": [],
            "clash_dns_respect_rules": False, "clash_dns_listen": f"127.0.0.1:{free_port()}",
        }, provider_base_url=f"http://127.0.0.1:{server.server_port}", subscription_token="fake", subscription_public_id="fake")
        cfg = yaml.safe_load(text)
        assert cfg["rules"][-1] == "MATCH,兜底代理"
        # The fallback group itself resolves to DIRECT via the primitive action.
        assert next(g for g in cfg["proxy-groups"] if g["name"] == "兜底代理")["proxies"] == ["DIRECT"]
        cfg["rules"].insert(0, "DOMAIN,control.example.com,DIRECT")
        cfg["mixed-port"] = free_port()
        cfg["external-controller"] = f"127.0.0.1:{free_port()}"
        served.update({key: builder.build_clash_provider_config(nodes, key)[0] for key in cfg["proxy-providers"]})
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
        binary = os.environ["MIHOMO_BIN"]
        with (tmp_path / "runtime.log").open("w") as log:
            proc = subprocess.Popen([binary, "-d", str(tmp_path), "-f", str(path)], stdout=log, stderr=subprocess.STDOUT)
            start = time.monotonic()
            deadline = start + 10
            while True:
                try:
                    with urllib.request.urlopen(f"http://{cfg['external-controller']}/version", timeout=0.5) as response:
                        json.load(response)
                    break
                except OSError:
                    assert time.monotonic() < deadline, "Mihomo controller did not start"
                    time.sleep(0.05)
            for mark in (15, 35):
                time.sleep(max(0, start + mark - time.monotonic()))
                for host, probe in (("control.example.com", f"/probe-control-{mark}"), (f"route-{mark}.example.com", f"/probe-policy-{mark}")):
                    with socket.create_connection(("127.0.0.1", cfg["mixed-port"]), timeout=2) as sock:
                        sock.settimeout(3)
                        sock.sendall(f"GET http://{host}:{server.server_port}{probe} HTTP/1.1\r\nHost: {host}:{server.server_port}\r\nConnection: close\r\n\r\n".encode())
                        try:
                            status = sock.recv(256)
                        except TimeoutError:
                            status = b"timeout"
                    if host == "control.example.com":
                        assert b"200 OK" in status and probe in hits
                    else:
                        assert (b"502" in status or status == b"timeout") and probe not in hits
                log.flush()
                route_log = (tmp_path / "runtime.log").read_text()
                assert any(f"route-{mark}.example.com:{server.server_port}" in line and "dial 中等质量 (match AND/" in line for line in route_log.splitlines())
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        server.shutdown()
        server.server_close()
        stopped.set()
        thread.join(timeout=1)
        dns.close()


@pytest.mark.parametrize("cipher", ["bf-cfb", "camellia-128-cfb", "camellia-192-cfb", "camellia-256-cfb", "cast5-cfb", "des-cfb", "idea-cfb", "rc2-cfb", "seed-cfb"])
def test_11_removed_surge_ss_cipher_skipped_with_reason(cipher):
    artifact = builder.build_surge_profile_artifacts([fake_node(cipher=cipher)], [], URL)
    assert artifact.skipped == ["USA-01"] and any("removed stream cipher" in w.message for w in artifact.diagnostics)


@pytest.mark.parametrize("protocol", ["vmess", "vless", "trojan"])
def test_12_13_inline_ws_tls_uses_verified_fields(protocol):
    node = fake_node(protocol=protocol, uuid=UUID, tls=True, sni="tls.example.com", network="ws",
                     **{"ws-opts":{"path":"/ws","headers":{"Host":"front.example.com"}}, "udp":True})
    text, skipped = builder.build_shadowrocket_config([node], [], URL)
    line = next(line for line in text.splitlines() if line.startswith("USA-01 ="))
    assert skipped == [] and "peer=tls.example.com" in line and "sni=" not in line
    assert "obfs=websocket, obfs-uri=/ws, obfs-host=front.example.com" in line and "udp=1" in line
    if protocol in {"vmess", "vless"}:
        assert f"password={UUID}" in line and "username=" not in line and "tls=true" in line
    if protocol == "vmess":
        assert "alterId=0, method=auto" in line


def test_12_13_reality_wireguard_and_unverified_keys_diagnosed():
    node = fake_node(protocol="vless", uuid=UUID, tls=True, flow="xtls-rprx-vision",
                     **{"reality-opts":{"public-key":"fake-public-key","short-id":"abcd"}, "client_fingerprint":"chrome"})
    text, skipped = builder.build_shadowrocket_config([node], [], URL)
    assert skipped == [] and "publicKey=fake-public-key, shortId=abcd" in text and "flow=xtls-rprx-vision" in text
    assert "client_fingerprint=" not in text and "shadowrocket-unverified-fields-omitted" in text
    wg = fake_node("WG", "wireguard", **{"private-key":KEY,"public-key":KEY,"ip":"10.8.0.2","dns":["10.8.0.1"],"mtu":1280})
    text, skipped = builder.build_shadowrocket_config([wg], [], URL)
    assert skipped == [] and "privateKey=" in text and "publicKey=" in text and "ip=10.8.0.2, mtu=1280, dns=10.8.0.1" in text
    plugin = fake_node(plugin="obfs-local", **{"plugin-opts":{"mode":"http","host":"front.example.com"}})
    assert builder._shadowrocket_inline_unsupported_reason(plugin)


def test_14_chain_field_preserved_with_warning():
    from app.models import QUALITY_CHAIN_HOME
    node = replace(fake_node(protocol="socks5"), quality_group=QUALITY_CHAIN_HOME, raw={"chain_home":True})
    text, _ = builder.build_shadowrocket_config([fake_node("Front"), node], [], URL)
    assert "forwarding-proxy=" in text and "shadowrocket-forwarding-proxy-pending-validation" in text
    assert "residential proxy may be contacted directly" in text


@pytest.mark.parametrize("enabled", [True, False])
def test_12_15_udp_flags_follow_node_and_profile_settings(enabled):
    nodes = [fake_node(), fake_node("SOCKS", "socks5")]
    for renderer,field in ((builder.build_surge_config, f"udp-relay={str(enabled).lower()}"),
                           (builder.build_shadowrocket_config, f"udp={int(enabled)}")):
        text, _ = renderer(nodes, [], URL, profile="lazycat", profile_settings={"clash_udp_default_enabled":enabled})
        assert text.count(field) == 2
    text, _ = builder.build_surge_config(nodes, [], URL)
    assert "proxy-test-url = https://cp.cloudflare.com/generate_204" in text
    assert "udp-policy-not-supported-behaviour = REJECT" in text
    assert not re.search(r"^.* = (?:url-test|fallback|smart),.*\burl=", text, re.M)


def test_17_named_scenario_links_safe_stable_and_raw_scheme():
    a = builder.build_device_import_links("https://sub.example.com", "private name", "fake", scenario_slug="家庭")
    b = builder.build_device_import_links("https://sub.example.com", "private name", "fake", scenario_slug="外出")
    assert a["shadowrocket_url"] != b["shadowrocket_url"]
    assert re.fullmatch(r"shadowrocket-[a-f0-9]{16}\.conf", a["shadowrocket_url"].rsplit("/",1)[1])
    assert a["shadowrocket_scheme"] == "shadowrocket://config/add/" + a["shadowrocket_url"]
    assert "private" not in a["shadowrocket_url"]


def test_18_rocket_casefold_names_and_group_references():
    nodes=[fake_node("US-A"),fake_node("us-a"),fake_node("US-A (2)")]
    text, _ = builder.build_shadowrocket_config(nodes, [], URL)
    proxy_section=text.split("[Proxy]\n")[1].split("[Proxy Group]")[0]
    names=[line.split(" = ")[0] for line in proxy_section.splitlines() if " = " in line]
    assert len({name.casefold() for name in names}) == len(names) == 3
    us = next(line for line in text.splitlines() if line.startswith("中等质量·美国 ="))
    assert all(name in us for name in names)


def test_19_20_mitm_nonstandard_port_and_map_local_retained_but_omitted():
    settings={"shadowrocket_mitm_hostname":["api.example.com:8443"],"shadowrocket_map_local":["^https://api.example.com/ data-type=text data=x"],"shadowrocket_ipv6":False}
    validate_lazycat_profile_settings_for_write(settings)
    with pytest.raises(ValueError):
        validate_lazycat_profile_settings_for_write({"shadowrocket_mitm_hostname":["*"]})
    text,_ = builder.build_shadowrocket_config([fake_node()],[],URL,profile="lazycat",profile_settings=settings)
    assert "hostname = api.example.com:8443" in text and "[Map Local]" not in text
    assert "full system trust" in text and "2.2.80" not in text and "443 only" not in text
    codes={w.code for w in builder.derive_shadowrocket_profile_diagnostics(settings)}
    assert {"shadowrocket-map-local-intercept-only","shadowrocket-ipv6-disable-ineffective"} <= codes


def test_21_clash_mi_guide_linked_and_covers_import_risks():
    root=Path(__file__).resolve().parents[1]
    guide=root/'docs/operations/clash-mi-import.md'
    text=guide.read_text()
    for phrase in ("启用备用下载通道", "内置-不覆写", "当前配置", "IPv6", "断开再连接"):
        assert phrase in text
    assert "docs/operations/clash-mi-import.md" in (root/'docs/index.md').read_text()


def test_22_dns_lazy_tun_hijack_and_udp_guard_preserve_explicit_direct():
    payload,_,warnings=clash(settings={"clash_tun_enable":True,"clash_tun_dns_hijack":[],"clash_udp_default_enabled":False})
    assert payload['dns']['fallback-lazy-query'] is True
    assert payload['tun']['dns-hijack'] == ['any:53','tcp://any:53']
    assert any(w.code == "clash-tun-dns-hijack-defaulted" for w in warnings)
    rules=builder._fail_closed_clash_udp_rules(["DOMAIN,direct.example.com,DIRECT", "DOMAIN,proxy.example.com,Proxy", "MATCH,Proxy"])
    assert rules == ["DOMAIN,direct.example.com,DIRECT", "DOMAIN,proxy.example.com,Proxy", "AND,((DOMAIN,proxy.example.com),(NETWORK,UDP)),REJECT", "NETWORK,UDP,Proxy", "NETWORK,UDP,REJECT", "MATCH,Proxy"]


def test_23_version_metadata_and_fetcher_ua_formats():
    from app.services.lazycat_profile import normalize_lazycat_profile_settings
    ir=builder.build_policy_ir([fake_node()],[])
    for client,version in (("clash","1.19.28"),("surge",{"min_ios":"5.23.0","min_macos":"6.0.0"})):
        result=builder._enrich_policy_ir_for_target(ir,target=client,profile="lazycat",normalized_settings=normalize_lazycat_profile_settings(None))
        assert result.metadata['version_constraints']['mihomo' if client=='clash' else 'surge'] == version
    assert _METHOD_USER_AGENTS['surge'] == 'Surge iOS/3867 SurgeCore/6010000'
    assert _METHOD_USER_AGENTS['shadowrocket'].startswith('Shadowrocket/3488 CFNetwork/')
    assert _METHOD_USER_AGENTS['clash'] == _CLASH_USER_AGENTS[0] == 'ClashforWindows/0.20.39'


def protocol_cases():
    return [
        fake_node('ss'), fake_node('ss-obfs',plugin='obfs',**{'plugin-opts':{'mode':'http','host':'front.example.com'}}),
        fake_node('vmess','vmess',uuid=UUID), fake_node('vmess-ws','vmess',uuid=UUID,tls=True,network='ws',**{'ws-opts':{'path':'/ws'}}),
        fake_node('vless','vless',uuid=UUID), fake_node('vless-ws','vless',uuid=UUID,tls=True,network='ws',**{'ws-opts':{'path':'/ws'}}),
        fake_node('reality','vless',uuid=UUID,tls=True,**{'client-fingerprint':'chrome','reality-opts':{'public-key':'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA','short-id':'abcd'}}),
        fake_node('trojan','trojan'), fake_node('trojan-ws','trojan',network='ws',**{'ws-opts':{'path':'/ws'}}),
        fake_node('hy2','hysteria2'), fake_node('tuic','tuic',uuid=UUID,password='fake-password',version=5),
        fake_node('anytls','anytls'), fake_node('socks5','socks5'), fake_node('http','http'),
        fake_node('WG','wireguard',**{'private-key':KEY,'public-key':KEY,'ip':['10.8.0.2','fd00::2']}),
    ]


@pytest.mark.parametrize('node',protocol_cases(),ids=lambda node:node.name)
def test_provider_protocol_shape_without_binary(node):
    content,skipped=builder.build_clash_provider_config([node],'medium')
    proxies=yaml.safe_load(content)['proxies']
    assert skipped == [] and len(proxies)==1
    assert proxies[0]['type']==node.protocol
    assert isinstance(proxies[0]['port'],int)
    if node.protocol=='wireguard':
        assert isinstance(proxies[0]['ip'],str) and isinstance(proxies[0]['ipv6'],str)


@pytest.mark.skipif(not os.environ.get('MIHOMO_BIN'),reason='set MIHOMO_BIN to run the local parser integration')
@pytest.mark.parametrize('node',protocol_cases(),ids=lambda node:node.name)
def test_mihomo_provider_nodes_individually_parse(node,tmp_path):
    content,_=builder.build_clash_provider_config([node],'medium')
    config=yaml.safe_load(content)
    config['rules']=['MATCH,REJECT']
    path=tmp_path/'config.yaml';path.write_text(yaml.safe_dump(config))
    result=subprocess.run([os.environ['MIHOMO_BIN'],'-t','-d',str(tmp_path),'-f',str(path)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.skipif(not os.environ.get('MIHOMO_BIN'),reason='set MIHOMO_BIN for main config parser validation')
def test_mihomo_empty_legacy_dns_and_regexp2_parse(tmp_path):
    payload,_,_=clash([fake_node(name) for name in ('USA-01','United States 02','Japan 01','Busan 01')], rules=['DEST-PORT,8443,REJECT-DICT','AND,((DOMAIN,example.com),(DEST-PORT,443)),REJECT-DROP'],render_mode='export',settings={key:[] for key in ('clash_dns_nameserver','clash_dns_default_nameserver','clash_dns_proxy_server_nameserver')})
    path=tmp_path/'config.yaml';path.write_text(yaml.safe_dump(payload,allow_unicode=True))
    result=subprocess.run([os.environ['MIHOMO_BIN'],'-t','-d',str(tmp_path),'-f',str(path)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr


def test_legacy_global_mitm_is_omitted_and_diagnosed():
    settings={"shadowrocket_mitm_hostname":["*"],"surge_mitm_hostname":["*"]}
    text,_=builder.build_shadowrocket_config([fake_node()],[],URL,profile="lazycat",profile_settings=settings)
    assert "hostname = *" not in text and "shadowrocket-mitm-global-refused" in text
    surge=builder.build_surge_profile_artifacts([fake_node()],[],URL,profile="lazycat",profile_settings=settings)
    assert "hostname = *" not in surge.main_conf and any(w.code=="surge-mitm-global-refused" for w in surge.diagnostics)


def test_node_udp_relay_alias_is_respected():
    node=fake_node(**{"udp-relay":False})
    text,_=builder.build_surge_config([node],[],URL)
    assert "udp-relay=false" in text
    text,_=builder.build_shadowrocket_config([node],[],URL)
    assert "udp=0" in text


def test_logical_rule_dialects_preserve_nested_predicates():
    entry=PolicyRuleEntry("medium","AND","(DST-PORT,8443)")
    lowered,_=builder._lower_policy_entries_for_client([entry],client="surge")
    assert lowered[0].value=="((DEST-PORT,8443))"
    lowered,_=builder._lower_policy_entries_for_client([replace(entry,value="((DEST-PORT,8443),(DOMAIN,example.com))")],client="clash")
    assert lowered[0].value=="((DST-PORT,8443),(DOMAIN,example.com))"


@pytest.mark.parametrize("target", ["REJECT-NO-DROP", "REJECT-TINYGIF", "REJECT-DICT", "REJECT-ARRAY", "REJECT-200", "REJECT-IMG", "REJECT-VIDEO", "REJECT-DROP"])
def test_10_mihomo_reject_variants_are_lowered_without_fake_groups(target):
    payload,_,warnings=clash(rules=[f"DEST-PORT,8443,{target}"])
    assert all(not group['name'].startswith('REJECT') for group in payload['proxy-groups'])
    policy='REJECT-DROP' if target=='REJECT-DROP' else 'REJECT'
    assert any(rule.endswith(','+policy) for rule in payload['rules'] if rule.startswith('RULE-SET,'))
    if policy != target:
        assert any(w.code=='clash-reject-downgraded' for w in warnings)


def test_18_generated_group_names_reserved_case_insensitively():
    nodes=[fake_node('中等质量·美国'),fake_node('REJECT-DICT')]
    text,_=builder.build_shadowrocket_config(nodes,[],URL)
    assert '中等质量·美国 (2) = ss,' in text and 'REJECT-DICT (2) = ss,' in text


def test_rule_lowering_does_not_rewrite_regex_payload_or_silently_approximate_protocol():
    value=r'^https://example.com/(NETWORK,UDP|DEST-PORT,443)'
    entries,warnings=builder._lower_policy_entries_for_client([PolicyRuleEntry('medium','URL-REGEX',value)],client='surge')
    assert entries[0].value==value and warnings==[]
    entries,warnings=builder._lower_policy_entries_for_client([PolicyRuleEntry('medium','PROTOCOL','STUN')],client='clash')
    assert entries==[] and warnings[0].bucket=='refused'
    entries,warnings=builder._lower_policy_entries_for_client([PolicyRuleEntry('medium','PROTOCOL','udp')],client='clash')
    assert entries[0].rule_type=='NETWORK' and entries[0].value=='UDP' and warnings==[]


def test_version_metadata_preserves_stricter_floor():
    assert builder._version_floor('1.19.33','1.19.28')=='1.19.33'
    assert builder._version_floor('1.19.21','1.19.28')=='1.19.28'
