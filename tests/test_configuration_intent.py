from __future__ import annotations

import ast
from dataclasses import fields
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from app import models
from app.services.configuration_intent import (
    ConfigurationIntent, TARGETS, derive_configuration_intent, intent_registry,
    ip_resolution_for_rule, project_configuration_intent, project_ip_match_options,
    routing_intent_diagnostics,
)
from app.services.lazycat_profile import LAZYCAT_PROFILE_SETTING_KEYS, normalize_lazycat_profile_settings
from app.services.profile_capabilities import profile_capabilities_payload
from app.services.profile_editor_schema import profile_editor_schema_payload
from app.services import subscription_builder as b
from scripts.compare_intent_outputs import render_case

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/intent-output-cases.json").read_text())


def test_inventory_covers_every_schema_capability_expert_and_storage_field():
    registry = intent_registry()
    rows = registry["settings"]
    keys = [r["id"] for r in rows]
    assert len(keys) == len(set(keys))
    assert set(keys) == set(LAZYCAT_PROFILE_SETTING_KEYS)
    schema = profile_editor_schema_payload()
    assert {c["family_id"] for c in schema["cards"]} == {r["family"] for r in rows}
    for c in schema["cards"]:
        assert set(c["field_keys"]) <= set(keys)
        assert {v["key"] for v in c["input_schema"]} <= set(keys)
    cap = profile_capabilities_payload()
    assert set(cap["expert_field_keys"]) <= set(keys)
    for group in cap["groups"]:
        for capability in group["capabilities"]:
            for subfield in capability["subfields"]:
                assert {v["key"] for v in subfield["clients"].values() if v.get("key")} <= set(keys)
    for r in [*rows, *registry["routing"]]:
        assert r["classification"] in {"shared", "adapted", "blocked", "standalone", "metadata"}
        assert set(r["projections"]) == set(TARGETS)
        assert r["intent"] and r["reason"]
        for projection in r["projections"].values():
            assert projection["syntax"] and projection["evidence"]
            for evidence in projection["evidence"]:
                assert evidence["tag"]
                assert evidence.get("gap") or evidence.get("symbol") or evidence.get("id") or evidence.get("section") or evidence.get("row")
            if projection["status"] in {"unsupported", "pending_validation"}:
                assert projection["diagnostic_code"].startswith("intent-")
                assert projection["consequence"] and "请" in projection["consequence"]


def test_inventory_covers_routing_domain_fields_and_ir_without_implicit_new_fields():
    keys = [r["id"] for r in intent_registry()["routing"]]
    fields_registered = {r.get("field", r["id"]) for r in intent_registry()["routing"]}
    assert len(keys) == len(set(keys))
    for cls in (models.PolicyRuleEntry, models.RouteContract, models.BusinessGroup,
                models.ServiceCatalogEntry, models.RuleCategory, models.CustomRule,
                models.ProcessRuleTemplate, models.ExternalProxyProgramTemplate):
        assert {f"{cls.__name__}.{f.name}" for f in fields(cls)} <= fields_registered
    # Collection names map to their own fully covered record types above.
    record_collections = {"business_groups", "rule_entries", "contracts", "catalog_bindings", "process_rules", "external_proxy_programs", "rule_lines"}
    assert {"PolicyIR."+f.name for f in fields(models.PolicyIR) if f.name not in record_collections} <= fields_registered
    assert {"PolicyIR.system_rules", "PolicyIR.ip_resolution"} <= fields_registered


def test_corpus_covers_all_cards_fields_families_and_modes():
    schema = profile_editor_schema_payload()
    assert {c["id"] for c in schema["cards"]} == {c["card"] for c in CASES if "card" in c}
    assert set(LAZYCAT_PROFILE_SETTING_KEYS) <= {k for c in CASES for k in c["settings"]}
    assert {c["profile"] for c in CASES} == {"", "lazycat", "raw"}
    assert {c["preset"] for c in CASES if "preset" in c} == set(models.DEVICE_STRATEGY_PRESETS)
    assert {c["strategy"] for c in CASES if "strategy" in c} == set(models.CONTRACT_STRATEGIES)
    assert sum("fixture" in c for c in CASES) >= 17


def test_snapshot_is_detached_roundtrippable_and_preserves_diverged_shared_values():
    policy = b.build_policy_ir([], ["IP-CIDR,192.0.2.0/24,DIRECT"])
    settings = {"surge_ipv6": False, "clash_ipv6": True, "tun_excluded_routes": ["192.0.2.0/24"], "surge_tun_excluded_routes": ["198.51.100.0/24"]}
    expected = normalize_lazycat_profile_settings(settings)
    desired = derive_configuration_intent(policy, settings, profile="lazycat", compiled_rules=b._compiled_policy_rule_entries(policy)[0])
    encoded = json.dumps(desired.to_dict(), ensure_ascii=False)
    restored = ConfigurationIntent.from_dict(json.loads(encoded))
    assert restored == desired
    settings["tun_excluded_routes"].append("203.0.113.0/24")
    policy.rule_lines.clear()
    for target in TARGETS:
        projected = project_configuration_intent(desired, target)
        assert projected.settings == expected
        assert projected.policy.rule_lines == ["IP-CIDR,192.0.2.0/24,DIRECT"]
        projected.policy.rule_lines.clear()
        assert project_configuration_intent(desired, target).policy.rule_lines
        assert not any(w.code == "intent-legacy-shared-value-diverged" for w in projected.diagnostics)
    assert desired.ip_resolution[0].clash == "never"
    assert desired.ip_resolution[0].surge == "client-default"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_all_artifact_bytes_repeat_without_observation_or_llm(monkeypatch, case):
    def forbidden(*args, **kwargs):
        raise AssertionError("renderer attempted an environment observation")
    monkeypatch.setattr(b, "_local_host_target_aliases", forbidden)
    first = render_case(case)
    assert first == render_case(case)
    assert all(isinstance(content, str) for content in first.values())
    assert not any("intent-" in content for content in first.values())


def test_frozen_intent_controls_all_three_renderers_instead_of_legacy_arguments():
    policy = b.build_policy_ir([], ["DOMAIN,approved.example.com,DIRECT"])
    desired = derive_configuration_intent(policy, {"surge_loglevel": "verbose"}, profile="lazycat")
    for target, renderer in (("clash", b.build_clash_profile_artifacts), ("surge", b.build_surge_profile_artifacts), ("shadowrocket", b.build_shadowrocket_profile_artifacts)):
        args = ([], ["DOMAIN,unapproved.example.com,DIRECT"]) + (() if target == "clash" else ("https://sub.example.com/config",))
        result = renderer(*args, profile_settings={"surge_loglevel": "warning"}, intent=desired)
        text = result[0] if target == "clash" else result.main_conf if target == "surge" else result.content
        assert "unapproved.example.com" not in text
        if target == "clash":
            asset = b.build_clash_rule_provider_config([], [], "catalog-rules-direct", intent=desired)
            assert "DOMAIN,approved.example.com" in asset
        elif target == "surge":
            assert any("approved.example.com" in asset for asset in result.domain_sets.values())
        else:
            assert "approved.example.com" in text
        if target == "surge":
            assert "loglevel = verbose" in text


@pytest.mark.parametrize("target", TARGETS)
def test_all_registered_setting_limits_reach_structured_diagnostics(target):
    defaults = normalize_lazycat_profile_settings(None)
    samples = {k:v for c in CASES if c["id"].startswith("field-") for k,v in c["settings"].items()}
    policy = b.build_policy_ir([], [])
    for row in intent_registry()["settings"]:
        p = row["projections"][target]
        if not p["diagnostic_code"]:
            continue
        key = row["id"]
        settings = {key:samples[key]}
        assert normalize_lazycat_profile_settings(settings)[key] != defaults[key], key
        projected = project_configuration_intent(derive_configuration_intent(policy, settings, profile="lazycat"), target)
        codes = {d.code for d in projected.diagnostics}
        assert p["diagnostic_code"] in codes, (key, target)
        diagnostic = next(d for d in projected.diagnostics if d.code == p["diagnostic_code"])
        assert diagnostic.severity == "warning"
        buckets = models.RendererDiagnostics()
        buckets.extend(projected.diagnostics)
        assert diagnostic.to_dict() in buckets.to_dict()[diagnostic.bucket]




@pytest.mark.parametrize("kind", ["IP-CIDR", "IP-CIDR6", "GEOIP", "IP-ASN", "AND"])
@pytest.mark.parametrize("extras", [[], ["no-resolve"]])
def test_dns_intent_preserves_per_client_defaults_and_explicit_source_options(kind, extras):
    entry = models.PolicyRuleEntry("medium", kind, "synthetic", extras)
    resolution = ip_resolution_for_rule(entry, 0)
    assert resolution.surge == resolution.shadowrocket == ("never" if extras else "client-default")
    for target in TARGETS:
        assert project_ip_match_options(resolution, target=target) == (["no-resolve"] if target=="clash" and kind in {"IP-CIDR","IP-CIDR6"} else extras)


def test_ip_only_warning_is_conditional_and_ignores_mixed_and_system_categories():
    entries = [models.PolicyRuleEntry("medium","IP-CIDR","192.0.2.0/24",category_name="Only IP"), models.PolicyRuleEntry("medium","DOMAIN","example.com",category_name="Mixed"), models.PolicyRuleEntry("medium","IP-ASN","13335",category_name="Mixed"), models.PolicyRuleEntry("action-direct","IP-CIDR","10.0.0.0/8",["no-resolve"],source_kind="system",category_name="System")]
    for target in TARGETS:
        warnings = routing_intent_diagnostics(entries,target=target,default_action="direct")
        assert [w.target for w in warnings if w.code == "intent-ip-only-category-direct-fallback"] == ["Only IP"]
        assert not any(w.code == "intent-ip-only-category-direct-fallback" for w in routing_intent_diagnostics(entries,target=target,default_action="proxy"))


def test_render_modules_do_not_import_llm_clock_or_random_sources():
    for filename in ("configuration_intent.py", "subscription_builder.py"):
        tree = ast.parse((ROOT / "app/services" / filename).read_text())
        imports = [n.module or "" for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)] + [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        assert not any(any(part in module for part in ("llm", "openai", "anthropic", "random", "datetime")) for module in imports)


@pytest.mark.skipif(not os.environ.get("MIHOMO_BIN"), reason="MIHOMO_BIN not configured")
@pytest.mark.parametrize("case_id", ["rules-ip-literal", "src-ip-custom-plain", "src-ip-catalog-other"])
def test_real_mihomo_accepts_intent_projection(case_id, tmp_path):
    case = next(c for c in CASES if c["id"] == case_id)
    # Avoid geodata dependencies; these probes validate locally generated config
    # plus all five provider files, never download a production subscription.
    case = {**case, "settings": {**case["settings"], "clash_dns_fallback": []}}
    artifacts = render_case(case)
    for name, content in artifacts.items():
        if name.startswith("bundle/"):
            p=tmp_path/name.removeprefix("bundle/")
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(content)
    result = subprocess.run([os.environ["MIHOMO_BIN"],"-t","-d",str(tmp_path),"-f",str(tmp_path/"clash.yaml")],capture_output=True,text=True,timeout=20)
    assert result.returncode == 0, result.stdout+result.stderr
    assert "download" not in (result.stdout+result.stderr).lower()
    # Validate the exact online main file too, with every generated asset
    # prepositioned at its declared path. No URL or generated byte is edited.
    online = yaml.safe_load(artifacts["clash.yaml"])
    for section, prefix in (("proxy-providers", "providers/"), ("rule-providers", "clash/rules/")):
        for key, payload in (online.get(section) or {}).items():
            name = prefix+key+(".yaml" if section=="proxy-providers" else ".txt")
            destination = tmp_path/payload["path"]
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_text(artifacts[name])
    (tmp_path/"online.yaml").write_text(artifacts["clash.yaml"])
    result = subprocess.run([os.environ["MIHOMO_BIN"],"-t","-d",str(tmp_path),"-f",str(tmp_path/"online.yaml")],capture_output=True,text=True,timeout=20)
    assert result.returncode == 0, result.stdout+result.stderr
    assert "download" not in (result.stdout+result.stderr).lower()


def test_document_inventory_is_generated_from_registry():
    from scripts.generate_intent_inventory import render_inventory
    assert (ROOT / "docs/design-docs/intent-inventory.md").read_text() == render_inventory()


def test_skill_evidence_ids_and_sections_exist_when_local_source_is_available():
    skill_dir = os.environ.get("PROXY_CONFIG_WRITER_SKILL_DIR")
    if not skill_dir:
        pytest.skip("PROXY_CONFIG_WRITER_SKILL_DIR not set; external Skill content verification requires the supplied evidence source")
    root = Path(skill_dir)
    assert root.is_dir()
    refs = [e for row in [*intent_registry()["settings"],*intent_registry()["routing"]] for p in row["projections"].values() for e in p["evidence"]]
    for evidence in refs:
        if not evidence.get("reference") or not evidence["reference"].endswith(".md"):
            continue
        content = (root/"references"/evidence["reference"]).read_text()
        if evidence.get("id"):
            assert "- "+evidence["id"]+" " in content, evidence
        elif "section" in evidence:
            section = evidence["section"]
            assert any(line.startswith("## "+section+".") or line.startswith("## "+section+" ") or line=="## "+section for line in content.splitlines()), evidence
