from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest
import yaml

from app.models import NodeRecord, PolicyRuleEntry, QUALITY_MEDIUM, RouteContract
from app.services.hub_service import HubService
from app.services import subscription_builder as builder
from app.services.subscription_builder import (
    build_clash_audit_markdown,
    build_clash_blocked_detail,
    build_clash_config,
    build_clash_export_bundle,
    build_clash_rule_provider_config,
    build_policy_ir,
    build_shadowrocket_config,
    build_shadowrocket_profile_artifacts,
    build_surge_profile_artifacts,
)


def _node() -> NodeRecord:
    return NodeRecord(name="delivery", host="node.example.com", port=443,
                      protocol="http", quality_group=QUALITY_MEDIUM)


def _sr_rules(text: str) -> list[str]:
    section = text.split("[Rule]\n", 1)[1].split("\n[", 1)[0]
    return [line for line in section.splitlines() if line and not line.startswith("#")]


@pytest.mark.parametrize(("origin", "expected"), [
    ("https://Sub.Example.com.:8443", "DOMAIN,sub.example.com,DIRECT"),
    ("http://192.0.2.8:8080", "IP-CIDR,192.0.2.8/32,DIRECT,no-resolve"),
    ("https://[2001:db8:0::8]:8443", "IP-CIDR6,2001:db8::8/128,DIRECT,no-resolve"),
])
@pytest.mark.parametrize("profile", ["", "lazycat"])
@pytest.mark.parametrize("target", ["REJECT", QUALITY_MEDIUM, "DIRECT", None])
def test_shadowrocket_subscription_fallback_respects_existing_routes(origin, expected, profile, target):
    # E-R-015 / LINT-ROK-109: existing proxy or reject policies stay in charge.
    rules = ["DOMAIN,unrelated.example.com,DIRECT"]
    if target:
        rules.append(expected.replace(",DIRECT", "," + target))
    ir = build_policy_ir([_node()], rules, default_group_name="REJECT")
    baseline = builder._final_rule_lines_with_default(ir, client="shadowrocket")
    text, skipped = build_shadowrocket_config(
        [], [], origin + "/sub/device/fake/default/shadowrocket.conf", profile=profile, policy_ir=ir,
    )
    assert skipped == []
    rendered = _sr_rules(text)
    assert rendered == (baseline if target else [*baseline[:-1], expected, baseline[-1]])
    assert ("[shadowrocket-subscription-host-rejected]" in text) == (target == "REJECT")
    if target == "REJECT":
        assert "Shadowrocket 连接时无法更新这份配置" in text
        assert "改为可用代理或 DIRECT" in text and "断开 VPN 后更新" in text


@pytest.mark.parametrize("final_target", ["DIRECT", QUALITY_MEDIUM])
def test_shadowrocket_no_subscription_exception_when_final_is_not_reject(final_target):
    ir = build_policy_ir([_node()], [], default_group_name=final_target)
    text, _ = build_shadowrocket_config([], [], "https://sub.example.com/sr.conf", policy_ir=ir)
    assert _sr_rules(text) == builder._final_rule_lines_with_default(ir, client="shadowrocket")
    assert "DOMAIN,sub.example.com,DIRECT" not in text


@pytest.mark.parametrize(("host", "rule"), [
    ("sub.example.com", "DOMAIN-SUFFIX,example.com,REJECT"),
    ("192.0.2.8", "IP-CIDR,192.0.2.0/24,REJECT"),
    ("[2001:db8::8]", "IP-CIDR6,2001:db8::/64,REJECT,no-resolve"),
])
def test_shadowrocket_covering_user_reject_is_preserved_and_diagnosed(host, rule):
    ir = build_policy_ir([_node()], [rule], default_group_name="REJECT")
    text, _ = build_shadowrocket_config([], [], f"https://{host}/sr.conf", policy_ir=ir)
    assert _sr_rules(text) == [rule, "FINAL,REJECT"]
    assert "[shadowrocket-subscription-host-rejected]" in text


def test_shadowrocket_lazycat_system_route_stays_in_place_without_duplicate():
    entries = [builder._policy_rule_entry_from_line(line) for line in HubService._clash_direct_rule_lines()]
    ir = build_policy_ir([_node()], [], rule_entries=entries, default_group_name="REJECT")
    baseline = builder._final_rule_lines_with_default(ir, client="shadowrocket")
    text, _ = build_shadowrocket_config([], [], "https://subhub.box.heiyu.space/sr.conf", policy_ir=ir)
    assert _sr_rules(text) == baseline
    assert baseline.count("DOMAIN-SUFFIX,heiyu.space,DIRECT") == 1
    assert "DOMAIN,subhub.box.heiyu.space,DIRECT" not in text


@pytest.mark.parametrize("rule", [
    "DOMAIN-KEYWORD,sub,REJECT", "GEOIP,CN,REJECT", "RULE-SET,https://rules.example.com/a.list,REJECT",
    "DOMAIN-SUFFIX,other.example.com,REJECT", "IP-CIDR,192.0.2.0/24,REJECT",
])
def test_shadowrocket_does_not_infer_unknown_or_nonmatching_host_rejects(rule):
    ir = build_policy_ir([_node()], [rule], default_group_name="REJECT")
    text, _ = build_shadowrocket_config([], [], "https://sub.example.com/sr.conf", policy_ir=ir)
    assert _sr_rules(text) == [rule, "DOMAIN,sub.example.com,DIRECT", "FINAL,REJECT"]
    assert "[shadowrocket-subscription-host-rejected]" not in text


@pytest.mark.parametrize("target", [
    "REJECT", "REJECT-DROP", "REJECT-NO-DROP", "REJECT-TINYGIF", "REJECT-DICT",
    "REJECT-ARRAY", "REJECT-200", "REJECT-IMG", "REJECT-VIDEO",
])
def test_shadowrocket_reject_variants_use_only_final_fallback(target):
    # rules-matrix.md §4 / E-R-149: exercise compilation and full rendering.
    ir = build_policy_ir([_node()], [], default_group_name=target)
    artifacts = build_shadowrocket_profile_artifacts([], [], "https://sub.example.com/sr.conf", policy_ir=ir)
    assert _sr_rules(artifacts.content) == ["DOMAIN,sub.example.com,DIRECT", f"FINAL,{target}"]
    assert "shadowrocket-subscription-host-rejected" not in {w.code for w in artifacts.diagnostics}
    artifacts = build_shadowrocket_profile_artifacts(
        [_node()], [f"DOMAIN,sub.example.com,{target}"], "https://sub.example.com/sr.conf",
    )
    assert _sr_rules(artifacts.content)[0] == f"DOMAIN,sub.example.com,{target}"
    assert "shadowrocket-subscription-host-rejected" in {w.code for w in artifacts.diagnostics}


@pytest.mark.parametrize("name", ["REJECT-office", "REJECT-office-lower", "普通路由", "广告拦截"])
@pytest.mark.parametrize("action", ["proxy", "reject"])
@pytest.mark.parametrize("host_rule", [False, True])
def test_shadowrocket_subscription_diagnostics_follow_contract_action(name, action, host_rule):
    contract = RouteContract(id="user-route", display_name=name, routing_action=action,
                             primary_pools=["medium"] if action == "proxy" else [])
    ir = build_policy_ir(
        [_node()], [], contracts=[contract], default_contract_id=contract.id,
        default_group_name=name,
        rule_entries=[PolicyRuleEntry(contract.id, "DOMAIN", "sub.example.com")] if host_rule else [],
    )
    artifacts = build_shadowrocket_profile_artifacts([], [], "https://sub.example.com/sr.conf", policy_ir=ir)
    codes = {w.code for w in artifacts.diagnostics}
    assert ("shadowrocket-subscription-host-rejected" in codes) == (host_rule and action == "reject")
    assert ("DOMAIN,sub.example.com,DIRECT" in _sr_rules(artifacts.content)) == (not host_rule and action == "reject")
    if host_rule:
        assert _sr_rules(artifacts.content)[0] == f"DOMAIN,sub.example.com,{'REJECT' if action == 'reject' else name}"


@pytest.mark.parametrize("client", ["surge", "clash", "shadowrocket"])
def test_rule_lowering_does_not_guess_reject_actions_from_names(client):
    entry = PolicyRuleEntry("REJECT-office", "DOMAIN", "sub.example.com")
    entries, warnings = builder._lower_policy_entries_for_client([entry], client=client)
    assert entries == [entry]
    assert warnings == []


@pytest.mark.parametrize("client", ["clash", "shadowrocket"])
def test_explicit_proxy_action_wins_over_legacy_group_labels(client):
    contract = RouteContract(id="user-route", display_name="广告拦截", routing_action="proxy", primary_pools=["medium"])
    ir = build_policy_ir([_node()], [], contracts=[contract])
    assert builder._client_rule_lines(ir, client=client, compiled_entries=[
        PolicyRuleEntry(contract.id, "DOMAIN", "sub.example.com"),
    ]) == ["DOMAIN,sub.example.com,广告拦截"]


def test_shadowrocket_final_business_group_name_does_not_imply_reject():
    ir = build_policy_ir([_node()], [], default_group_name="REJECT-office")
    artifacts = build_shadowrocket_profile_artifacts([], [], "https://sub.example.com/sr.conf", policy_ir=ir)
    assert _sr_rules(artifacts.content) == ["FINAL,REJECT-office"]
    assert "shadowrocket-subscription-host-rejected" not in {w.code for w in artifacts.diagnostics}


def test_shadowrocket_deduplicates_update_rule_and_retains_remote_sets():
    rules = ["DOMAIN,sub.example.com,DIRECT",
             "RULE-SET,https://rules.example.com/a.list,REJECT,no-resolve",
             "DOMAIN-SET,https://rules.example.com/b.txt,DIRECT"]
    ir = build_policy_ir([_node()], rules, default_group_name="REJECT")
    text, _ = build_shadowrocket_config([], [], "https://sub.example.com/sr.conf", policy_ir=ir)
    assert _sr_rules(text) == builder._final_rule_lines_with_default(ir, client="shadowrocket")
    assert _sr_rules(text).count("DOMAIN,sub.example.com,DIRECT") == 1
    assert set(_sr_rules(text)[:-1]) == set(rules)
    assert "remote-rule-set-dropped" not in text


@pytest.mark.parametrize("managed_url", ["", "https://sub.example.com/sr.conf?rev=1"])
def test_shadowrocket_does_not_emit_update_url(managed_url):
    # E-R-016 / E-R-135: let the client retain the actual fetched URL.
    text, _ = build_shadowrocket_config([_node()], [], managed_url, profile="lazycat")
    assert not any(line.strip().lower().startswith("update-url") for line in text.splitlines())


@pytest.mark.parametrize(("extras", "suffix"), [
    ([], ""), (["no-resolve"], ",no-resolve"),
    (["src", "extended-matching"], ",src,extended-matching"),
    (["DIRECT", "no-resolve", "ignored-policy", "src"], ",no-resolve,src"),
    (["  NO-RESOLVE  ", "REJECT", "extended-matching"], ",  NO-RESOLVE  ,extended-matching"),
])
def test_ruleset_serialization_preserves_only_predicate_options(extras, suffix):
    entry = PolicyRuleEntry("direct", "IP-CIDR", "198.51.100.0/24", extras=extras)
    assert entry.to_ruleset_line() == "IP-CIDR,198.51.100.0/24" + suffix
    assert entry.extras == extras
    assert entry.to_line(target_name="DIRECT") == ",".join([entry.rule_type, entry.value, "DIRECT", *extras])


@pytest.mark.parametrize("options", [[], ["no-resolve"]])
def test_rule_assets_strip_inline_policy_without_changing_no_resolve(options):
    entry = PolicyRuleEntry("direct", "IP-CIDR", "198.51.100.0/24", extras=["REJECT", *options])
    ir = build_policy_ir([_node()], [], rule_entries=[entry])
    surge = build_surge_profile_artifacts([], [], "https://sub.example.com/surge.conf", policy_ir=ir)
    assert surge.rule_sets["ip-rules-direct"] == ",".join([entry.rule_type, entry.value, *options]) + "\n"
    clash = build_clash_rule_provider_config([], [], "catalog-rules-direct", policy_ir=ir)
    # PR 75's existing Mihomo top-level CIDR normalization still adds no-resolve.
    assert clash == "IP-CIDR,198.51.100.0/24,no-resolve\n"


@pytest.mark.parametrize("membership", [
    {"use": ["medium"]}, {"include-all": True}, {"include-all-providers": True},
    {"include-all-proxies": True}, {"exclude-filter": "HK"}, {"exclude-type": "http"},
    {"filter": "HK"},
])
@pytest.mark.parametrize("fallback", [None, "", "  ", "REJECT", "DIRECT"])
def test_blocked_detail_requires_explicit_empty_fallback(membership, fallback):
    group = {"name": "dynamic", "type": "select", **membership}
    if fallback is not None:
        group["empty-fallback"] = fallback
    detail = build_clash_blocked_detail(build_policy_ir([], []), rendered_content=yaml.safe_dump({
        "proxy-groups": [group], "rules": ["MATCH,REJECT"],
    }))
    missing = not fallback or not fallback.strip()
    assert detail["provider_health"]["groups_without_empty_fallback"] == (["dynamic"] if missing else [])
    assert [item["code"] for item in detail["blockers"]] == (
        ["clash-use-group-empty-fallback-missing"] if missing else []
    )


def test_filter_does_not_empty_explicit_members():
    detail = build_clash_blocked_detail(build_policy_ir([], []), rendered_content=yaml.safe_dump({
        "proxy-groups": [{"name": "explicit", "type": "select", "proxies": ["DIRECT"], "filter": "HK"}],
    }))
    assert detail["blockers"] == []


@pytest.mark.parametrize(("provider_check", "group_check", "duplicate", "missing"), [
    (False, True, False, False), (True, False, False, False),
    (True, True, False, False), (False, False, False, True),
])
def test_probe_audit_accepts_either_layer_and_detects_actual_duplicates(provider_check, group_check, duplicate, missing):
    provider = {"type": "file", "path": "./providers/medium.yaml"}
    if provider_check:
        provider["health-check"] = {"enable": True, "url": "https://probe.example.com/204", "interval": 300}
    group = {"name": "auto", "type": "url-test", "use": ["medium"], "empty-fallback": "REJECT"}
    if group_check:
        group.update(url="https://probe.example.com/204", interval=300)
    bundle = {"files": {"clash.yaml": yaml.safe_dump({
        "proxy-providers": {"medium": provider}, "proxy-groups": [group], "rules": ["MATCH,REJECT"],
    })}}
    detail = build_clash_blocked_detail(build_policy_ir([], []), rendered_content=bundle["files"]["clash.yaml"])
    assert detail["provider_health"]["use_groups_with_duplicate_health_check"] == (["auto"] if duplicate else [])
    assert [item["code"] for item in detail["blockers"]] == (["clash-provider-health-check-missing"] if missing else [])
    audit = build_clash_audit_markdown(bundle, profile="lazycat")
    assert f"different-URL duplicate group/provider health-check absent: {'no' if duplicate else 'yes'}" in audit
    assert "empty-fallback present on potentially empty groups: yes" in audit
    group.pop("empty-fallback")
    bundle["files"]["clash.yaml"] = yaml.safe_dump({"proxy-groups": [group]})
    audit = build_clash_audit_markdown(bundle, profile="lazycat")
    assert "empty-fallback present on potentially empty groups: no" in audit
    assert "groups_without_empty_fallback: auto" in audit
    assert "clash-use-group-empty-fallback-missing" in audit


@pytest.mark.parametrize(("provider_url", "group_url", "duplicate"), [
    ("https://probe.example.com/204", "https://probe.example.com/204", False),
    (" HTTPS://PROBE.EXAMPLE.COM:443/204 ", "https://probe.example.com/204", False),
    ("http://probe.example.com:80", "http://PROBE.EXAMPLE.COM/", False),
    ("https://probe.example.com/204#one", "https://probe.example.com/204#two", False),
    ("https://probe.example.com/provider", "https://probe.example.com/group", True),
    ("https://probe.example.com/204?a=1", "https://probe.example.com/204?a=2", True),
    ("https://probe.example.com/Case", "https://probe.example.com/case", True),
    ("invalid-url", "https://probe.example.com/204", False),
    ("https://probe.example.com:invalid/204", "https://probe.example.com/204", False),
    ("", "https://probe.example.com/204", False),
])
@pytest.mark.parametrize("group_type", ["url-test", "fallback", "load-balance", "select"])
def test_probe_audit_reports_only_known_different_urls(provider_url, group_url, duplicate, group_type):
    payload = {
        "proxy-providers": {"p": {"health-check": {"enable": True, "url": provider_url, "interval": 300}}},
        "proxy-groups": [{"name": "auto", "type": group_type, "use": ["p"], "empty-fallback": "REJECT",
                          "url": group_url, "interval": 600}],
    }
    text = yaml.safe_dump(payload)
    details = build_clash_blocked_detail(build_policy_ir([], []), rendered_content=text)
    expected = duplicate and group_type != "select"
    assert details["provider_health"]["use_groups_with_duplicate_health_check"] == (["auto"] if expected else [])
    audit = build_clash_audit_markdown({"files": {"clash.yaml": text}}, profile="lazycat")
    assert f"different-URL duplicate group/provider health-check absent: {'no' if expected else 'yes'}" in audit
    assert "同 URL 或无法静态确定的不报告" in audit


def test_generated_clash_keeps_pr75_group_probes_and_empty_fallback():
    text, _ = build_clash_config([_node()], ["DOMAIN,example.com,中等质量"],
                                 provider_base_url="https://sub.example.com", subscription_token="fake")
    payload = yaml.safe_load(text)
    groups = [group for group in payload["proxy-groups"] if group.get("use")]
    assert groups
    for group in groups:
        assert group["empty-fallback"] == "REJECT"
        assert group["url"] and group["interval"] == 300
        for key in group["use"]:
            assert "health-check" not in payload["proxy-providers"][key]
            assert payload["proxy-providers"][key]["proxy"] == "DIRECT"
    detail = build_clash_blocked_detail(build_policy_ir([], []), rendered_content=text)
    assert detail["blockers"] == []
    assert detail["provider_health"]["use_groups_with_duplicate_health_check"] == []


@pytest.mark.skipif(not os.environ.get("MIHOMO_BIN"), reason="MIHOMO_BIN is not configured")
def test_generated_clash_bundle_passes_real_mihomo_parser(tmp_path: Path):
    ir = build_policy_ir([_node()], [], rule_entries=[
        PolicyRuleEntry("direct", "IP-CIDR", "198.51.100.0/24", extras=["REJECT", "no-resolve"]),
    ])
    bundle = build_clash_export_bundle([], [], device_name="delivery", device_key="delivery",
                                       subscription_token="fake", policy_ir=ir)
    for name, content in bundle["files"].items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    result = subprocess.run([os.environ["MIHOMO_BIN"], "-t", "-d", str(tmp_path),
                             "-f", str(tmp_path / "clash.yaml")], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
