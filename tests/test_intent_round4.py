from __future__ import annotations

from copy import deepcopy
import hashlib

import pytest

from app import models
from app.models import PolicyRuleEntry
from app.services import configuration_intent as intent
from app.services import subscription_builder as builder
from app.services.lazycat_profile import normalize_lazycat_profile_settings
from scripts.build_intent_registry import build_registry, validate_projection_codes
from tests.test_intent_round2 import SAMPLES, artifacts, node

TARGETS = ("clash", "surge", "shadowrocket")
CLIENT_LABELS = {"clash": "Mihomo", "surge": "Surge", "shadowrocket": "Shadowrocket"}

# The Hub delivery path leaves these PolicyIR fields empty, but internal
# builder callers may still fill them; Surge, for one, renders the DNS.
POLICY_IR_NATIVE_SAMPLES = {
    "dns": {"dns-server": ["192.0.2.53"]},
    "tun": {"enable": True},
    "sniffer": {"enable": True},
    "http_processing": {"url-rewrite": ["^http://synthetic.invalid/a http://synthetic.invalid/b 302"]},
    "rule_providers": {
        "synthetic": {
            "type": "http",
            "behavior": "classical",
            "url": "https://synthetic.invalid/rules.list",
            "path": "./rules/synthetic.list",
            "interval": 3600,
        }
    },
}
POLICY_IR_NATIVE_CODES = {
    "clash": {"intent-policyir-http-processing-clash-unsupported"},
    "surge": {
        "intent-policyir-dns-surge-pending-validation",
        "intent-policyir-tun-surge-pending-validation",
        "intent-policyir-sniffer-surge-unsupported",
        "intent-policyir-rule-providers-surge-unsupported",
        "intent-policyir-http-processing-surge-pending-validation",
    },
    "shadowrocket": {
        "intent-policyir-dns-shadowrocket-pending-validation",
        "intent-policyir-tun-shadowrocket-pending-validation",
        "intent-policyir-sniffer-shadowrocket-unsupported",
        "intent-policyir-rule-providers-shadowrocket-unsupported",
        "intent-policyir-http-processing-shadowrocket-pending-validation",
    },
}


def _policy_with_native_fields():
    policy = builder.build_policy_ir([node()], [], contracts=[], default_contract_id="action-direct")
    for field_name, sample in POLICY_IR_NATIVE_SAMPLES.items():
        setattr(policy, field_name, deepcopy(sample))
    return policy


def test_rule_identity_hashes_the_single_rule_key_definition():
    entries = [
        PolicyRuleEntry(target_contract_id="medium", rule_type="DOMAIN-SUFFIX", value="example.com"),
        PolicyRuleEntry(
            target_contract_id="direct",
            rule_type="IP-CIDR",
            value="192.0.2.0/24",
            extras=["no-resolve"],
        ),
    ]
    for entry in entries:
        key_digest = hashlib.sha256(intent._json(intent._rule_key(entry)).encode()).hexdigest()
        assert intent.rule_identity(entry) == key_digest

    # Pinned digests from before the two field lists were merged: the
    # identity values themselves must not change.
    assert intent.rule_identity(entries[0]) == "98d26364c29fd813c9e96ab7dd2acc8c19e19facc0a64a28c1733d4aceb554de"
    assert intent.rule_identity(entries[1]) == "1bca43b6ee15a6c43512bd29651e336f1d7d14c4ce4204a57bc205bf0b759ab6"


def _strict_policy(count):
    contracts = [
        models.RouteContract(f"s{index}", f"Strict {index}", primary_pools=["medium"])
        for index in range(count)
    ]
    contracts.append(
        models.RouteContract("lb", "Balance LB", strategy_type="load-balance", primary_pools=["medium"])
    )
    return builder.build_policy_ir([node()], [], contracts=contracts, default_contract_id="s0")


def test_strict_contracts_merge_into_one_client_specific_warning():
    _, diagnostics = artifacts(_strict_policy(5))
    messages = {}
    for target in TARGETS:
        code = f"intent-contract-strict-{target}-pending-validation"
        strict = [warning for warning in diagnostics[target] if warning.code == code]
        assert len(strict) == 1, target
        warning = strict[0]
        assert warning.target == "Strict 0、Strict 1、Strict 2"
        assert warning.message.startswith("5 个 strict 契约（示例：Strict 0、Strict 1、Strict 2）")
        assert "Strict 3" not in warning.message
        assert CLIENT_LABELS[target] in warning.message
        assert "fallback" in warning.message
        assert "REJECT 或 DIRECT" in warning.message
        assert "请" in warning.message
        messages[target] = warning.message.split("）", 1)[1]
    # Each client states its own gap instead of one shared sentence.
    assert len(set(messages.values())) == 3


def test_single_strict_contract_is_still_reported_by_name():
    _, diagnostics = artifacts(_strict_policy(1))
    for target in TARGETS:
        code = f"intent-contract-strict-{target}-pending-validation"
        warning = next(item for item in diagnostics[target] if item.code == code)
        assert warning.target == "Strict 0"
        assert warning.message.startswith("1 个 strict 契约（示例：Strict 0）")


def _routing_corpus_diagnostics():
    """Render a synthetic policy that touches every routing diagnostic path."""
    registry = intent.intent_registry()
    rule_types = [row["value"] for row in registry["routing"] if row.get("field") == "PolicyRuleEntry.rule_type"]
    sample_values = {
        "IP-CIDR": "192.0.2.0/24",
        "IP-CIDR6": "2001:db8::/32",
        "GEOIP": "CN",
        "IP-ASN": "13335",
        "DST-PORT": "443",
        "SRC-PORT": "1234",
        "IN-PORT": "7890",
        "SRC-IP-CIDR": "192.0.2.1/32",
        "NETWORK": "udp",
        "UID": "501",
    }
    entries = [
        PolicyRuleEntry("medium", rule_type, sample_values.get(rule_type, "synthetic.example"))
        for rule_type in rule_types
    ]
    contracts = [
        models.RouteContract("medium", "Strict Medium", primary_pools=["medium"]),
        models.RouteContract("lb", "Balance LB", strategy_type="load-balance", primary_pools=["medium"]),
    ]
    # Hub disables objects that need rebinding; mirror that here.
    process_rules = [
        models.ProcessRuleTemplate("p1", "medium", "Strict Medium", "PROCESS-NAME", "Browser"),
        models.ProcessRuleTemplate(
            "p2", "", "Legacy", "PROCESS-NAME", "^Legacy", enabled=False, migration_warning="needs_rebind"
        ),
    ]
    external_programs = [
        models.ExternalProxyProgramTemplate("e1", "medium", "Strict Medium", "/synthetic/tool", [], 17891, "Tool"),
        models.ExternalProxyProgramTemplate(
            "e2", "", "Legacy", "/synthetic/legacy", [], 17892, "Legacy Tool",
            enabled=False, migration_warning="needs_rebind",
        ),
    ]
    proxy_default = builder.build_policy_ir(
        [node()],
        [],
        rule_entries=entries,
        contracts=contracts,
        process_rules=process_rules,
        external_proxy_programs=external_programs,
        default_contract_id="medium",
    )
    # The IP-only fallback warning needs a direct default route.
    direct_default = builder.build_policy_ir(
        [node()],
        [],
        rule_entries=[PolicyRuleEntry("medium", "IP-CIDR", "198.51.100.0/24", category_name="Only IP")],
        contracts=contracts[:1],
        default_contract_id="action-direct",
    )
    fired = {target: set() for target in TARGETS}
    for policy_ir in (proxy_default, direct_default, _policy_with_native_fields()):
        _, diagnostics = artifacts(policy_ir)
        for target in TARGETS:
            fired[target] |= {warning.code for warning in diagnostics[target]}
    return fired


def _setting_corpus_diagnostics():
    """Give every setting a non-default sample under the contexts it depends on."""
    contexts = [
        {},
        {"clash_dns_enhanced_mode": "fake-ip", "clash_tun_enable": True, "clash_sniffer_enable": True},
    ]
    fired = {target: set() for target in TARGETS}
    for key, value in SAMPLES.items():
        for context in contexts:
            settings = normalize_lazycat_profile_settings({**context, key: value})
            for target in TARGETS:
                fired[target] |= {warning.code for warning in intent._setting_diagnostics(settings, target)}
    return fired


def test_every_registered_code_is_emitted_on_its_client():
    registry = intent.intent_registry()
    routing_fired = _routing_corpus_diagnostics()
    setting_fired = _setting_corpus_diagnostics()
    for target in TARGETS:
        for section, fired in (("settings", setting_fired), ("routing", routing_fired)):
            registered = {
                row["projections"][target]["diagnostic_code"]
                for row in registry[section]
                if row["projections"][target]["diagnostic_code"]
            }
            assert registered <= fired[target], (section, target, sorted(registered - fired[target]))
    all_fired = set()
    for fired in (*routing_fired.values(), *setting_fired.values()):
        all_fired |= fired
    table_codes = {item["code"] for item in registry["diagnostics"].values()}
    assert table_codes <= all_fired, sorted(table_codes - all_fired)


def test_registry_validation_rejects_codes_that_cannot_fire():
    registry = build_registry()
    validate_projection_codes(registry)

    foreign = deepcopy(registry)
    row = next(item for item in foreign["routing"] if item["id"] == "RouteContract.strategy_type[failover:surge]")
    row["projections"]["clash"].update(status="unsupported", diagnostic_code="intent-contract-failover-clash-unsupported")
    with pytest.raises(ValueError, match="outside the row scope"):
        validate_projection_codes(foreign)

    # Only the code changes; the status still says not_projected.
    foreign_code = deepcopy(registry)
    row = next(item for item in foreign_code["routing"] if item["id"] == "RouteContract.strategy_type[failover:surge]")
    assert row["projections"]["clash"]["status"] == "not_projected"
    row["projections"]["clash"]["diagnostic_code"] = "intent-routing-evidence-gap-clash"
    with pytest.raises(ValueError, match="outside the row scope"):
        validate_projection_codes(foreign_code)

    mismatched = deepcopy(registry)
    row = next(item for item in mismatched["routing"] if item["id"] == "ProcessRuleTemplate.migration_warning")
    row["projections"]["clash"]["status"] = "pending_validation"
    with pytest.raises(ValueError, match="does not match status"):
        validate_projection_codes(mismatched)


def test_per_client_consequences_state_the_client_situation():
    rows = {row["id"]: row for row in intent.intent_registry()["settings"]}

    def consequence(row_id, target):
        return rows[row_id]["projections"][target]["consequence"]

    assert "不会收到这份本地响应" in consequence("surge_map_local", "clash")
    assert "Mihomo 不支持 Map Local" in consequence("surge_map_local", "clash")
    assert "只拦截、不交付" in consequence("shadowrocket_map_local", "shadowrocket")
    assert "Surge 的 Map Local 设置" in consequence("shadowrocket_map_local", "surge")
    assert "不会写入 Mihomo 配置" in consequence("surge_dns_server", "clash")
    assert "不会写入 Shadowrocket 配置" in consequence("surge_dns_server", "shadowrocket")
    assert "使用 IPv6 地址的节点也不可用" in consequence("clash_ipv6", "clash")
    assert "使用 IPv6 地址的节点仍可连接" in consequence("surge_ipv6", "surge")
    assert "关不掉 IPv6" in consequence("shadowrocket_ipv6", "shadowrocket")
    # The experiments only show off-link IPv6 literals failing; same-subnet
    # literals stay direct, and the Surge run did not set ipv6-vif.
    assert "非同网段的 IPv6 字面量请求失败" in consequence("clash_ipv6", "clash")
    assert "同网段的 IPv6 字面量不经 Clash Mi" in consequence("clash_ipv6", "clash")
    assert "不写 ipv6-vif" in consequence("surge_ipv6", "surge")
    assert "非同网段的 IPv6 字面量请求失败" in consequence("surge_ipv6", "surge")
    assert "同网段的 IPv6 字面量不经 Surge" in consequence("surge_ipv6", "surge")

    registry = intent.intent_registry()
    texts = [item["message"] for item in registry["diagnostics"].values()]
    for section in ("settings", "routing"):
        for row in registry[section]:
            texts.extend(projection["consequence"] for projection in row["projections"].values())
    assert not any("命名空间" in text for text in texts)


def test_policy_ir_native_fields_from_builder_callers_keep_their_codes():
    # The Hub delivery path leaves these fields empty: no warning there.
    hub_policy = builder.build_policy_ir([node()], [], contracts=[], default_contract_id="action-direct")
    _, hub_diagnostics = artifacts(hub_policy)
    for target in TARGETS:
        assert not [warning for warning in hub_diagnostics[target] if warning.code.startswith("intent-policyir-")]

    _, diagnostics = artifacts(_policy_with_native_fields())
    for target in TARGETS:
        codes = {warning.code for warning in diagnostics[target] if warning.code.startswith("intent-policyir-")}
        assert codes == POLICY_IR_NATIVE_CODES[target], target
    assert sum(len(codes) for codes in POLICY_IR_NATIVE_CODES.values()) == 11

    # The field is live on this interface: Surge writes the caller's DNS.
    policy = builder.build_policy_ir([node()], [], contracts=[], default_contract_id="action-direct")
    policy.dns = {"dns-server": ["192.0.2.53"]}
    surge = builder.build_surge_profile_artifacts([], [], "https://sub.example/s.conf", profile="", policy_ir=policy)
    assert "dns-server = 192.0.2.53" in surge.main_conf.splitlines()
    assert "intent-policyir-dns-surge-pending-validation" in {warning.code for warning in surge.diagnostics}


def test_surge_strict_warning_counts_only_contracts_rendered_as_fallback():
    contracts = [
        models.RouteContract("medium", "中等质量", primary_pools=["medium"]),
        models.RouteContract("bulk", "低质量大流量", primary_pools=["bulk"]),
    ]
    policy = builder.build_policy_ir([node()], [], contracts=contracts, default_contract_id="medium")
    outputs, diagnostics = artifacts(policy)
    # The bulk pool has no node, so Surge writes that contract as select, REJECT.
    assert "低质量大流量 = select, REJECT" in outputs["surge"].splitlines()
    surge_code = "intent-contract-strict-surge-pending-validation"
    surge_strict = [warning for warning in diagnostics["surge"] if warning.code == surge_code]
    assert [warning.target for warning in surge_strict] == ["中等质量"]
    assert surge_strict[0].message.startswith("1 个 strict 契约（示例：中等质量）在 Surge 输出为 fallback 组")
    # Mihomo and Shadowrocket render both contracts as fallback groups.
    for target in ("clash", "shadowrocket"):
        code = f"intent-contract-strict-{target}-pending-validation"
        strict = [warning for warning in diagnostics[target] if warning.code == code]
        assert [warning.target for warning in strict] == ["中等质量、低质量大流量"], target

    only_empty = builder.build_policy_ir([node()], [], contracts=contracts[1:], default_contract_id="action-direct")
    _, diagnostics = artifacts(only_empty)
    assert not [warning for warning in diagnostics["surge"] if warning.code == surge_code]
    assert [warning.code for warning in diagnostics["clash"] if "strict" in warning.code] == [
        "intent-contract-strict-clash-pending-validation"
    ]


def test_dropped_mihomo_rule_types_are_named_in_one_warning():
    code = "intent-policyruleentry-rule-type-clash-pending-validation"
    entries = [
        PolicyRuleEntry("action-direct", "UID", "501", category_name="Cat A"),
        PolicyRuleEntry("action-direct", "PASS", "synthetic-pass", category_name="Cat A"),
        PolicyRuleEntry("action-direct", "PASS-RULE", "synthetic-pass-rule", category_name="Cat B"),
        PolicyRuleEntry("action-direct", "REMATCH-NAME", "synthetic-rematch", category_name="Cat B"),
    ]
    policy = builder.build_policy_ir([node()], [], rule_entries=entries, contracts=[], default_contract_id="action-direct")
    outputs, diagnostics = artifacts(policy)
    # The message must match the output: none of these rules reach Mihomo.
    for entry in entries:
        assert f"{entry.rule_type},{entry.value}" not in outputs["clash"]
    dropped = [warning for warning in diagnostics["clash"] if warning.code == code]
    assert len(dropped) == 1
    assert dropped[0].target == "UID、PASS、PASS-RULE"
    assert dropped[0].message.startswith("4 种规则类型（示例：UID、PASS、PASS-RULE）的规则不会写入 Mihomo 配置")
    assert "仍按现有方言输出" not in dropped[0].message

    single = builder.build_policy_ir([node()], [], rule_entries=entries[:1], contracts=[], default_contract_id="action-direct")
    _, diagnostics = artifacts(single)
    warning = next(item for item in diagnostics["clash"] if item.code == code)
    assert warning.target == "UID"
    assert warning.message.startswith("1 种规则类型（示例：UID）")


def test_conflicting_rule_target_quotes_the_original_rule_in_export_mode():
    # The compatibility projection adds no-resolve to the IP rule. The
    # existing warning keeps quoting the rule as stored, like the others.
    entries = [
        PolicyRuleEntry("action-direct", "DOMAIN", "::1", category_name="Cat"),
        PolicyRuleEntry("medium", "IP-CIDR6", "::1/128", category_name="Cat"),
    ]
    contracts = [models.RouteContract("medium", "中等质量", primary_pools=["medium"])]
    policy = builder.build_policy_ir([node()], [], rule_entries=entries, contracts=contracts, default_contract_id="medium")
    _, _, warnings = builder.build_clash_profile_artifacts(
        [], [], profile="lazycat", policy_ir=policy, render_mode="export",
    )
    conflicts = [warning for warning in warnings if warning.code == "conflicting-rule-target"]
    assert [warning.target for warning in conflicts] == ["IP-CIDR6,::1/128,中等质量"]
