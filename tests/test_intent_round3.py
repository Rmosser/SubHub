"""Independent regressions for the remaining registry and diagnostic defects."""
from __future__ import annotations

import ast
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import date
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import models
from app.services import configuration_intent as intent
from app.services import subscription_builder as builder
from app.services.hub_service import HubService
from app.services.rule_catalog import RuleCatalog, _RULE_TYPES
from scripts.build_intent_registry import build_registry
from tests.test_intent_round2 import artifacts, node, policy


TARGETS = ("clash", "surge", "shadowrocket")
CLIENT_NAMES = {
    "clash": ("clash", "mihomo", "clash mi"),
    "surge": ("surge",),
    "shadowrocket": ("shadowrocket", "rocket"),
}
INPUT_SEMANTICS = (
    "CustomRule.created_at",
    "RouteContract.owner_scenario_id",
    "ProcessRuleTemplate.migration_warning",
    "ExternalProxyProgramTemplate.migration_warning",
)


def test_projection_messages_name_only_the_target_client():
    for row in [*intent.intent_registry()["settings"], *intent.intent_registry()["routing"]]:
        for target, projection in row["projections"].items():
            message = projection["consequence"].lower()
            for other, names in CLIENT_NAMES.items():
                if other != target:
                    assert not any(name in message for name in names), (row["id"], target, message)
            phrase = f"本项没有可证明等价的 {target} 投影。"
            if row in intent.intent_registry()["settings"] and projection["status"] == "unsupported":
                assert phrase in message, (row["id"], target)
            # An unsupported Map Local binding only changes legacy warning
            # comments; it does not output an executable native Map Local rule.
            if projection["status"] != "unsupported":
                assert "本项没有可证明等价的" not in message, (row["id"], target)


def _assert_rule_type_coverage(registry):
    # Read the real Surge accept-list rather than copying a second list here.
    tree = ast.parse(inspect.getsource(builder._lower_policy_entries_for_client))
    surge_assignment = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "surge_types" for t in n.targets)
    )
    surge_types = {n.value for n in ast.walk(surge_assignment.value) if isinstance(n, ast.Constant)}
    accepted = builder._CLASH_KNOWN_RULE_TYPES | builder._SURGE_MAC_ONLY_RULE_TYPES | surge_types | _RULE_TYPES
    registered = {r["value"] for r in registry["routing"] if r.get("field") == "PolicyRuleEntry.rule_type"}
    # Catch-all is expressed by PolicyIR.default_contract_id, not a predicate.
    assert accepted - {"MATCH", "FINAL"} <= registered


def test_rule_types_cover_every_renderer_accept_list_and_reject_omissions():
    registry = build_registry()
    _assert_rule_type_coverage(registry)
    for kind in ("DSCP", "SUB-RULE"):
        mutated = deepcopy(registry)
        mutated["routing"] = [r for r in mutated["routing"] if r.get("value") != kind]
        with pytest.raises(AssertionError):
            _assert_rule_type_coverage(mutated)


@pytest.mark.parametrize("kind,value", [("DSCP", "46"), ("SUB-RULE", "(DOMAIN,probe.example)")])
def test_native_rule_gaps_have_specific_structured_warnings(kind, value):
    ir = policy([models.PolicyRuleEntry("action-direct", kind, value, category_name="Gap probe")])
    _, diagnostics = artifacts(ir)
    for target in ("surge", "shadowrocket"):
        warning = next(w for w in diagnostics[target] if w.code == f"intent-rule-{kind.lower()}-{target}-unsupported")
        assert kind in warning.message
        assert warning.target == "Gap probe"
        assert warning.severity == "warning"


def test_group_warnings_only_cover_unproven_native_semantics():
    ir = builder.build_policy_ir(
        [node()], [], contracts=[
            models.RouteContract("a", "Failover A", strategy_type="failover", primary_pools=["medium"]),
            models.RouteContract("b", "Balance B", strategy_type="load-balance", primary_pools=["medium"]),
            models.RouteContract("c", "Select C", primary_pools=["medium"]),
        ], default_contract_id="a",
    )
    _, diagnostics = artifacts(ir)
    for target in TARGETS:
        assert not any(w.code.startswith("intent-contract-failover-") for w in diagnostics[target])
        load = [w for w in diagnostics[target] if w.code.startswith("intent-contract-load-balance-")]
        assert len(load) == (1 if target == "shadowrocket" else 0)
        strict = next(w for w in diagnostics[target] if w.code == f"intent-contract-strict-{target}-pending-validation")
        assert strict.target == "Select C"
    assert load[0].target == "Balance B"


def test_routing_evidence_gap_names_and_counts_actual_declarations():
    entries = [models.PolicyRuleEntry("action-direct", "DOMAIN", f"item{i}.example") for i in range(5)]
    _, diagnostics = artifacts(policy(entries))
    for target in TARGETS:
        gap = next(w for w in diagnostics[target] if w.code == f"intent-routing-evidence-gap-{target}")
        assert gap.target != "分流声明"
        assert "6 项" in gap.message  # five predicates and the default business group
        assert all(f"item{i}.example" in gap.message for i in range(3))
        assert "item3.example" not in gap.message


async def _observe_input(field, value, tmp_path):
    """Use the actual hub input compiler, with synthetic repository records."""
    contract = models.RouteContract("a", "Proxy A", primary_pools=["medium"])
    other = models.RouteContract("b", "Proxy B", primary_pools=["medium"])
    category = models.RuleCategory("Synthetic", contract.primary_legacy_group())
    binding = models.ServiceCatalogEntry("Synthetic", contract_id="a")
    group = models.BusinessGroup("Proxy A", pool_names=["中等质量"])
    pin_group = {"group_name": "Synthetic", "mode": "standard", "sort_order": 0}
    process = models.ProcessRuleTemplate("p", "a", "Proxy A", "PROCESS-NAME", "Browser")
    external = models.ExternalProxyProgramTemplate("e", "a", "Proxy A", "/synthetic/tool", [], 17891, "Local Tool")
    objects = {"RouteContract": contract, "RuleCategory": category, "ServiceCatalogEntry": binding,
               "BusinessGroup": group, "PinGroup": pin_group, "ProcessRuleTemplate": process,
               "ExternalProxyProgramTemplate": external}
    root, key = field.split(".")
    custom = []
    if root == "CustomRule":
        # Real repository ordering is essential: direct PolicyIR mutation would
        # conceal the created_at counterexample caught by the independent review.
        from app.config import Settings
        from app.storage.sqlite_repo import SqliteRepo
        repo = SqliteRepo(Settings(
            app_name="Synthetic", app_base_url="https://sub.example", storage_root=str(tmp_path),
            refresh_interval_minutes=60, request_timeout_seconds=1, verify_tls=True,
            github_api_base="https://invalid.example", github_raw_base="https://invalid.example",
            rule_catalog_refresh_hours=24, manage_api_require_login=True,
            max_snapshots_per_account=2, account_crawl_parallelism=1,
        ))
        try:
            repo.save_custom_rule(models.CustomRule("a", "DOMAIN", "same.example", target_contract_id="a", created_at=value))
            repo.save_custom_rule(models.CustomRule("b", "DOMAIN", "same.example", target_contract_id="b", created_at="2026-11-02"))
            custom = repo.list_custom_rules()
        finally:
            repo.close()
    elif root == "PinGroup":
        pin_group[key] = value
    else:
        setattr(objects[root], key, value)

    async def entries(**kwargs):
        return [{"line": "DOMAIN,synthetic.example,Proxy A", "source_kind": "catalog", "category_name": "Synthetic"}]

    repo = SimpleNamespace(
        # Same ownership predicate as SqliteRepo.list_route_contracts. The
        # dedicated metadata_probe rechecks the actual SQLite scope query.
        list_route_contracts=lambda *args: [c for c in (contract, other) if not c.owner_scenario_id],
        list_scenario_route_contract_views=lambda *args: [],
        list_service_catalog_entries=lambda: [binding],
        list_pin_groups=lambda: [pin_group],
        list_custom_rules=lambda: custom,
        get_default_general_profile=lambda: None,
        get_runtime_setting=lambda key: None,
        list_rule_cache=lambda name: [],
    )
    hub = object.__new__(HubService)
    hub.repo = repo
    hub.rule_catalog = SimpleNamespace(
        list_categories=lambda: [category], get_targeted_rule_entries=entries,
        normalize_output_rule_line=RuleCatalog.normalize_output_rule_line,
    )
    hub._load_process_rules = lambda *args, **kwargs: [process]
    hub._load_external_proxy_programs = lambda *args, **kwargs: [external]
    hub._device_strategy_preset_for_token = lambda _: "balanced"
    ir = await hub._build_policy_ir_from_nodes("synthetic", [node()])
    if root == "BusinessGroup":
        ir.business_groups = [group]
    output, diagnostics = artifacts(ir)
    return output, {t: [w.to_dict() for w in diagnostics[t]] for t in TARGETS}, hub._summarize_surge_mac_overlay([process], [external]).to_dict()


METADATA_VALUES = {
    "RouteContract.description": ("old", "new"),
    "RouteContract.editable": (True, False),
    "RouteContract.is_system": (False, True),
    "RouteContract.llm_routing_intent": ("old", "new"),
    "RouteContract.updated_at": ("2026-11-01", "2026-11-03"),
    "BusinessGroup.created_by_system": (False, True),
    "ServiceCatalogEntry.source": ("migrated", "manual"),
    "ServiceCatalogEntry.updated_at": ("2026-11-01", "2026-11-03"),
    "RuleCategory.rule_count": (0, 42),
    "RuleCategory.custom_rule_count": (0, 42),
    "RuleCategory.updated_at": ("2026-11-01", "2026-11-03"),
    "RuleCategory.locked": (False, True),
    "RuleCategory.system_default_locked": (False, True),
    "RuleCategory.lock_source": ("", "manual"),
    "PinGroup.description": ("old", "new"),
    "PinGroup.sort_order": (0, 42),
    "PinGroup.updated_at": ("2026-11-01", "2026-11-03"),
    "CustomRule.created_at": ("2026-11-01", "2026-11-03"),
    "RouteContract.owner_scenario_id": ("", "other-scenario"),
    "ProcessRuleTemplate.migration_warning": ("", "needs_rebind"),
    "ExternalProxyProgramTemplate.migration_warning": ("", "needs_rebind"),
}


def test_every_metadata_field_has_an_independent_flip_fixture():
    metadata = {r["id"] for r in intent.intent_registry()["routing"] if r["classification"] == "metadata"}
    assert metadata == METADATA_VALUES.keys() - set(INPUT_SEMANTICS)


@pytest.mark.parametrize("field", sorted(METADATA_VALUES))
def test_metadata_flip_checks_device_bytes_and_management_diagnostics(field, tmp_path):
    old, new = METADATA_VALUES[field]
    before = asyncio.run(_observe_input(field, old, tmp_path / "before"))
    after = asyncio.run(_observe_input(field, new, tmp_path / "after"))
    row = next(r for r in intent.intent_registry()["routing"] if r["id"] == field)
    if row["classification"] == "metadata":
        assert before == after, field
    else:
        assert field in INPUT_SEMANTICS
        assert before != after, field


@pytest.mark.parametrize("field", INPUT_SEMANTICS)
def test_reclassifying_an_input_semantic_as_metadata_fails_actual_flip(field, tmp_path):
    registry = build_registry()
    row = next(r for r in registry["routing"] if r["id"] == field)
    assert row["classification"] == "blocked"
    row["classification"] = "metadata"
    before = asyncio.run(_observe_input(field, METADATA_VALUES[field][0], tmp_path / "before"))
    after = asyncio.run(_observe_input(field, METADATA_VALUES[field][1], tmp_path / "after"))
    with pytest.raises(AssertionError):
        assert before == after, field


def test_non_json_snapshot_error_explains_the_storage_boundary():
    for value, name in ((date(2026, 12, 31), "date"), (b"synthetic", "bytes")):
        ir = policy()
        ir.nodes[0].raw["upstream-extra"] = value
        with pytest.raises(TypeError, match=f"Unsupported intent value: {name}"):
            intent.derive_configuration_intent(ir, None, profile="lazycat")


def test_rules_without_ip_policies_do_not_hash_identities(monkeypatch):
    def forbidden(*args):
        raise AssertionError("non-IP rules must not compute identities")

    monkeypatch.setattr(intent, "rule_identity", forbidden)
    artifacts(policy([models.PolicyRuleEntry("action-direct", "DOMAIN-SUFFIX", f"item{i}.example") for i in range(20)]))


def test_ip_identity_is_computed_once_and_projection_snapshots_decode_once(monkeypatch):
    original = intent.rule_identity
    calls = []

    def counted(entry):
        calls.append(entry.value)
        return original(entry)

    monkeypatch.setattr(intent, "rule_identity", counted)
    desired = intent.derive_configuration_intent(policy([models.PolicyRuleEntry("action-direct", "IP-CIDR", "192.0.2.0/24")]), None, profile="lazycat")
    assert calls == ["192.0.2.0/24"]
    for target in TARGETS:
        projection = intent.project_configuration_intent(desired, target)
        entries, warnings = projection.compiled_rules()
        assert projection.compiled_rules()[0] is entries
        projection.project_rules(entries)
        intent.routing_intent_diagnostics(entries, target=target, default_action="direct", projection=projection)
    assert calls == ["192.0.2.0/24"]


def test_blocked_supported_spec_is_rejected_instead_of_silently_rewritten(monkeypatch, tmp_path):
    from scripts import build_intent_registry as generator

    spec = json.loads(generator.SPEC.read_text())
    row = next(r for r in spec["settings"] if r["id"] == "tun_excluded_routes")
    row["targets"]["clash"]["status"] = "supported"
    mutated = tmp_path / "spec.json"
    mutated.write_text(json.dumps(spec))
    monkeypatch.setattr(generator, "SPEC", mutated)
    with pytest.raises(ValueError, match="blocked specification cannot claim supported clash"):
        generator.build_registry()


@pytest.mark.parametrize("value,code,message", [
    ("not-a-network", "clash-rule-dropped-invalid", "Skipped invalid Clash CIDR rule: IP-CIDR,not-a-network,DIRECT"),
    ("10.2.3.4", "clash-cidr-autofixed", "Normalized Clash CIDR rule IP-CIDR,10.2.3.4,DIRECT to 10.2.3.4/32"),
])
def test_legacy_warning_quotes_the_original_rule_text(value, code, message):
    ir = policy([models.PolicyRuleEntry("action-direct", "IP-CIDR", value)])
    warnings = builder.build_clash_profile_artifacts([], [], policy_ir=ir)[2]
    assert [w.message for w in warnings if w.code == code] == [message]


def test_legacy_rule_text_table_is_not_built_without_matching_warning(monkeypatch):
    def forbidden(*args):
        raise AssertionError("no matching legacy warning; do not build the rule text table")

    monkeypatch.setattr(builder, "_legacy_rule_text_table", forbidden)
    builder.build_clash_profile_artifacts([], [], policy_ir=policy())
