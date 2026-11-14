"""Independent semantic regressions from the two round-one reviews."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

from app.models import BusinessGroup, NodeRecord, PolicyRuleEntry, RouteContract
from app.services import subscription_builder as b
from app.services.configuration_intent import (
    derive_configuration_intent,
    project_configuration_intent,
    intent_registry,
)
from scripts.build_intent_registry import build_registry, validate_equivalence


def node():
    return NodeRecord(
        "Synthetic",
        "node.example",
        443,
        "ss",
        password="synthetic",
        quality_group="中等质量",
        raw={"cipher": "aes-128-gcm"},
    )


def policy(entries=()):
    return b.build_policy_ir(
        [node()],
        [],
        rule_entries=list(entries),
        contracts=[],
        default_contract_id="action-direct",
    )


def artifacts(ir, settings=None):
    kw = dict(policy_ir=ir, profile="lazycat", profile_settings=settings)
    c = b.build_clash_profile_artifacts([], [], render_mode="export", **kw)
    s = b.build_surge_profile_artifacts([], [], "https://sub.example/s.conf", **kw)
    r = b.build_shadowrocket_profile_artifacts(
        [], [], "https://sub.example/r.conf", **kw
    )
    return {
        "clash": c[0],
        "surge": s.main_conf
        + "".join(s.rule_sets.values())
        + "".join(s.domain_sets.values()),
        "shadowrocket": r.content,
    }, {"clash": c[2], "surge": s.diagnostics, "shadowrocket": r.diagnostics}


def test_equivalence_evidence_rejects_a_blocked_to_shared_mutation():
    registry = build_registry()
    validate_equivalence(registry)
    next(r for r in registry["settings"] if r["id"] == "tun_excluded_routes")[
        "classification"
    ] = "shared"
    with pytest.raises(ValueError, match="tun_excluded_routes"):
        validate_equivalence(registry)


def test_registry_is_parsed_once_and_recursively_immutable():
    assert intent_registry() is intent_registry()
    with pytest.raises(TypeError):
        intent_registry()["settings"][0]["classification"] = "shared"


def test_load_balance_output_and_pending_warning_are_both_present():
    ir = b.build_policy_ir(
        [node()],
        [],
        contracts=[
            RouteContract(
                "medium",
                "中等质量",
                strategy_type="load-balance",
                primary_pools=["medium"],
            )
        ],
        default_contract_id="medium",
    )
    a = b.build_shadowrocket_profile_artifacts(
        [], [], "https://sub.example/r.conf", policy_ir=ir
    )
    assert "中等质量 = load-balance, 中等质量·自动, REJECT, persistent=1" in a.content
    warning = next(
        w
        for w in a.diagnostics
        if w.code == "intent-contract-load-balance-shadowrocket-pending-validation"
    )
    assert (
        warning.target == "中等质量"
        and "会话" in warning.message
        and "persistent=1" in warning.message
    )
    assert warning.severity == "warning" and "intent-" not in a.content


@pytest.mark.parametrize("kind", ["IP-CIDR", "IP-CIDR6", "SRC-IP-CIDR"])
def test_frozen_ip_policy_controls_main_and_rule_asset(kind):
    value = "2001:db8::/32" if kind == "IP-CIDR6" else "203.0.113.0/24"
    ir = policy([PolicyRuleEntry("action-direct", kind, value, ["extended-matching"])])
    original = derive_configuration_intent(ir, None, profile="")
    changed = replace(
        original,
        ip_resolution=tuple(
            replace(p, clash="client-default") for p in original.ip_resolution
        ),
    )
    for desired, expected in ((original, True), (changed, False)):
        main, _, warnings = b.build_clash_profile_artifacts(
            [], [], intent=desired, render_mode="export"
        )
        if not expected:
            assert not any(
                w.code == "intent-ip-dns-client-default-differs" for w in warnings
            )
        line = next(
            line
            for line in yaml.safe_load(main)["rules"]
            if line.startswith(kind + ",")
        )
        assert ("no-resolve" in line) == expected
        asset = b.build_clash_rule_provider_config(
            [], [], "catalog-rules-direct", intent=desired
        )
        assert ("no-resolve" in asset) == expected
        assert (
            "extended-matching" not in line
        )  # baseline's option replacement is retained


@pytest.mark.parametrize("extras", [[], ["extended-matching"], ["no-resolve"]])
@pytest.mark.parametrize("source", ["custom", "catalog", "system"])
def test_src_ip_baseline_options_and_udp_guards(extras, source):
    ir = policy(
        [
            PolicyRuleEntry(
                "medium", "SRC-IP-CIDR", "10.9.0.0/16", extras, source_kind=source
            )
        ]
    )
    # Use a real proxy target so derived UDP rejection guards are present.
    ir.contracts = [
        RouteContract("medium", "Synthetic Proxy", primary_pools=["medium"])
    ]
    ir.business_groups = [
        BusinessGroup("Synthetic Proxy", pool_names=["中等质量"]),
        BusinessGroup(ir.default_group_name),
    ]
    text, _, _ = b.build_clash_profile_artifacts(
        [], [], policy_ir=ir, render_mode="export"
    )
    rules = yaml.safe_load(text)["rules"]
    assert any(
        line.startswith("SRC-IP-CIDR,10.9.0.0/16,") and line.endswith(",no-resolve")
        for line in rules
    )
    assert any(
        "AND,((SRC-IP-CIDR,10.9.0.0/16,no-resolve),(NETWORK,UDP)),REJECT" == line
        for line in rules
    )
    asset = (
        b.build_clash_rule_provider_config(
            [],
            [],
            ("manual" if source == "custom" else source) + "-rules-medium",
            policy_ir=ir,
        )
        if source != "system"
        else ""
    )
    if asset:
        assert asset == "SRC-IP-CIDR,10.9.0.0/16,no-resolve\n"


@pytest.mark.parametrize("via_lines", [False, True])
def test_derivation_compiles_and_binds_dns_to_identity(via_lines):
    entries = [
        PolicyRuleEntry("action-direct", "DOMAIN", "first.example"),
        PolicyRuleEntry("action-direct", "DOMAIN", "first.example"),
        PolicyRuleEntry("action-direct", "IP-CIDR", "203.0.113.0/24", ["no-resolve"]),
        PolicyRuleEntry("action-direct", "IP-CIDR", "198.51.100.0/24"),
        PolicyRuleEntry(
            "action-reject", "DOMAIN", "first.example", source_kind="custom"
        ),
    ]
    ir = policy(entries)
    if via_lines:
        ir.rule_lines = [e.to_line() for e in entries]
        ir.rule_entries = []
    desired = derive_configuration_intent(ir, None, profile="")
    compiled = b._compiled_policy_rule_entries(ir)[0]
    verified = derive_configuration_intent(
        ir, None, profile="", compiled_rules=compiled
    )
    assert desired == verified
    with pytest.raises(ValueError, match="compiled_rules"):
        derive_configuration_intent(
            ir, None, profile="", compiled_rules=list(reversed(compiled))
        )
    for target in ("clash", "surge", "shadowrocket"):
        projection = project_configuration_intent(desired, target)
        forward = projection.project_rules(compiled)
        backward = projection.project_rules(list(reversed(compiled)))
        assert {e.value: tuple(e.extras) for e in forward} == {
            e.value: tuple(e.extras) for e in backward
        }
        assert next(e for e in forward if e.value == "first.example").extras == []
        assert next(e for e in forward if e.value == "203.0.113.0/24").extras == [
            "no-resolve"
        ]
        if target != "clash":
            assert next(e for e in forward if e.value == "198.51.100.0/24").extras == []


@pytest.mark.parametrize("value", [float("inf"), float("nan"), float("1.0e+999")])
def test_nonfinite_source_extras_render_four_outputs(value):
    n = node()
    n.raw["arbitrary-upstream-extra"] = value
    ir = b.build_policy_ir([n], [])
    text, warnings = artifacts(ir)
    assert all("node.example" in v or k == "clash" for k, v in text.items())
    assert yaml.safe_load(b.build_clash_provider_config([n], "medium")[0])["proxies"]
    assert b.build_shadowrocket_nodes_subscription([n])[0]


@pytest.mark.parametrize("target", ["clash", "surge", "shadowrocket"])
def test_udp_switch_real_node_binding_and_behavior_warning(target):
    outputs = []
    for enabled in (True, False):
        ir = b.build_policy_ir([node()], [])
        text, diagnostics = artifacts(ir, {"clash_udp_default_enabled": enabled})
        if target == "clash":
            provider = b.build_clash_provider_config(
                [node()], "medium", udp_default_enabled=enabled
            )[0]
            assert yaml.safe_load(provider)["proxies"][0]["udp"] is enabled
        else:
            assert (
                "udp-relay=" + str(enabled).lower()
                if target == "surge"
                else "udp=" + str(int(enabled))
            ) in text[target]
        warning = next(
            w
            for w in diagnostics[target]
            if w.target == "clash_udp_default_enabled" and w.code.startswith("intent-")
        )
        assert "不会应用" not in warning.message
        assert "请" in warning.message
        if target == "shadowrocket":
            assert all(
                word in warning.message
                for word in ("VMess TCP", "Trojan TCP/WS", "直连")
            )
        outputs.append(text[target])
    if target != "clash":
        assert outputs[0] != outputs[1]


def test_route_clock_changes_only_signed_expiry_and_signature(client, monkeypatch):
    from tests.test_api_devices_and_subscriptions import _shadowrocket_diagnostics_repo
    from app.models import CustomRule
    import app.services.subscription_urls as urls

    repo = _shadowrocket_diagnostics_repo(client, monkeypatch)
    repo.save_custom_rule(
        CustomRule("rule", "DOMAIN", "clock.example", "action-direct")
    )

    def fetch(stamp):
        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return stamp

        monkeypatch.setattr(urls, "datetime", Frozen)
        client.app.state.services.hub_service._clear_artifact_caches()
        return [
            client.get("/sub/device/synthetic-diagnostics/default/" + name).text
            for name in (
                "clash.yaml",
                "surge.conf",
                "shadowrocket.conf",
                "shadowrocket-nodes.txt",
            )
        ]

    first = fetch(datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert first == fetch(datetime(2026, 11, 1, tzinfo=timezone.utc))
    later = fetch(datetime(2026, 11, 2, 0, 0, 7, tzinfo=timezone.utc))

    def strip(s):
        return re.sub(r"(exp|sig)=[^&\s,]+", r"\1=<frozen>", s)

    assert [strip(s) for s in first] == [strip(s) for s in later]
    assert first[0] != later[0] and first[1] != later[1]
    assert first[2:] == later[2:]


def test_compiled_registry_and_inventory_are_reproducible():
    subprocess.run(
        [sys.executable, "scripts/build_intent_registry.py", "--check"], check=True
    )


CASES = json.loads(
    (Path(__file__).parent / "fixtures/intent-output-cases.json").read_text()
)
SAMPLES = {
    k: v
    for c in CASES
    if c["id"].startswith("field-")
    for k, v in c["settings"].items()
}


@pytest.mark.parametrize("key", sorted(SAMPLES))
def test_setting_binding_matches_actual_device_bytes(key):
    row = next(r for r in intent_registry()["settings"] if r["id"] == key)
    contexts = [
        {},
        {
            "clash_dns_enhanced_mode": "fake-ip",
            "clash_tun_enable": True,
            "clash_sniffer_enable": True,
        },
        {
            "surge_mitm_hostname": ["mitm.example"],
            "shadowrocket_mitm_hostname": ["mitm.example"],
            "surge_http_api": "127.0.0.1:6171",
        },
    ]
    affected = set()
    for ctx in contexts:
        if key in ctx:
            continue
        ir = b.build_policy_ir(
            [node()],
            ["DOMAIN,example.org,中等质量"],
            contracts=[RouteContract("medium", "中等质量", primary_pools=["medium"])],
            default_contract_id="medium",
        )

        def render(settings):
            kw = dict(profile="lazycat", profile_settings=settings, policy_ir=ir)
            c = b.build_clash_profile_artifacts(
                [],
                [],
                provider_base_url="https://sub.example",
                subscription_token="synthetic",
                **kw,
            )[0]
            s = b.build_surge_profile_artifacts(
                [], [], "https://sub.example/s.conf", **kw
            )
            r = b.build_shadowrocket_profile_artifacts(
                [], [], "https://sub.example/r.conf", **kw
            ).content
            return {
                "clash": c,
                "surge": s.main_conf
                + "".join(s.rule_sets.values())
                + "".join(s.domain_sets.values()),
                "shadowrocket": r,
            }

        old, new = render(ctx), render({**ctx, key: SAMPLES[key]})
        affected |= {t for t in old if old[t] != new[t]}
    expected = {
        t for t, p in row["projections"].items() if p.get("binding") is not None
    }
    assert affected == expected, (key, affected, expected)
    for target in expected:
        assert row["projections"][target]["status"] in {
            "supported",
            "pending_validation",
            "unsupported",
        }


def test_management_metadata_is_not_a_projection_or_equivalence_claim():
    rows = {r.get("field", r["id"]): r for r in intent_registry()["routing"]}
    for key in (
        "RouteContract.updated_at",
        "RouteContract.description",
        "RouteContract.llm_routing_intent",
        "RuleCategory.rule_count",
    ):
        assert rows[key]["classification"] == "metadata"
    for row in rows.values():
        if row["classification"] == "metadata":
            assert all(
                p["status"] == "not_projected" and not p["diagnostic_code"]
                for p in row["projections"].values()
            )
    for key in (
        "tun_excluded_routes",
        "surge_tun_excluded_routes",
        "shadowrocket_tun_excluded_routes",
    ):
        assert (
            next(r for r in intent_registry()["settings"] if r["id"] == key)[
                "classification"
            ]
            == "blocked"
        )


def test_rule_capability_matrix_records_native_gaps_and_direct_evidence():
    rows = {
        r.get("value"): r
        for r in intent_registry()["routing"]
        if r.get("field") == "PolicyRuleEntry.rule_type"
    }
    for kind in ("USER-AGENT", "URL-REGEX", "SUBNET", "HOSTNAME-TYPE"):
        assert rows[kind]["projections"]["clash"]["status"] == "unsupported"
    for target in ("surge", "shadowrocket"):
        assert rows["SRC-IP-CIDR"]["projections"][target]["status"] == "unsupported"
    for target, code in (("surge", "E-S-154"), ("shadowrocket", "E-R-150")):
        evidence = rows["DOMAIN"]["projections"][target]["evidence"]
        assert any(e.get("id") == code and e["tag"] == "实机验证" for e in evidence)
    assert rows["SUBNET"]["classification"] == "standalone"
    assert rows["UID"]["projections"]["clash"]["status"] == "pending_validation"


@pytest.mark.parametrize("value", ["not-a-network", "10.2.3.4"])
def test_legacy_invalid_rule_warning_preserves_source_text(value):
    _, _, warnings = b.build_clash_profile_artifacts(
        [], [], policy_ir=policy([PolicyRuleEntry("action-direct", "IP-CIDR", value)])
    )
    source_warnings = [
        w
        for w in warnings
        if w.code in {"clash-rule-dropped-invalid", "clash-cidr-autofixed"}
    ]
    assert source_warnings
    for w in source_warnings:
        assert value in w.message and ",no-resolve" not in w.message


def test_incomplete_settings_do_not_become_explicit_legacy_settings():
    _, _, warnings = b.build_clash_profile_artifacts(
        [], [], profile="lazycat", profile_settings={}
    )
    assert not any(
        w.code == "clash-always-real-ip-pending-validation" for w in warnings
    )
    _, _, warnings = b.build_clash_profile_artifacts(
        [],
        [],
        profile="lazycat",
        profile_settings={"clash_always_real_ip": ["*.example.com"]},
    )
    assert any(w.code == "clash-always-real-ip-pending-validation" for w in warnings)
