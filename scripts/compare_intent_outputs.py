#!/usr/bin/env python3
"""Compare synthetic subscription bytes at two refs, without changing checkouts.

Run with ./.venv/bin/python. WORKTREE includes uncommitted candidate changes.
The corpus is frozen from the calling checkout and used on both sides.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/fixtures/intent-output-cases.json"


def render_case(case: dict) -> dict[str, str]:
    """Imports use the selected ref's root, including its synthetic fixtures."""
    import yaml
    from app.models import (
        BusinessGroup, ExternalProxyProgramTemplate, MacOverlayTemplate, PolicyRuleEntry,
        ProcessRuleTemplate, RouteContract,
    )
    from app.services import subscription_builder as b
    from app.services.export_artifacts import attach_clash_bundle_audit
    from app.services.hub_service import HubService
    from app.services.subscription_contracts import CLASH_PROVIDER_KEYS
    from tests.test_proxy_maintenance import fake_node

    nodes = [fake_node(name="USA-synthetic"), fake_node(name="Japan-synthetic", protocol="trojan")]
    if case.get("node_fixture") == "surge":
        from tests.test_surge_capabilities import _surge_nodes
        nodes = _surge_nodes()
    elif case.get("node_fixture") == "empty":
        nodes = []
    entries = [
        PolicyRuleEntry("medium", "DOMAIN-SUFFIX", "example.org", category_name="Domains"),
        PolicyRuleEntry("medium", "IP-CIDR", "192.0.2.0/24", category_name="IP only"),
        PolicyRuleEntry("medium", "IP-CIDR6", "2001:db8::/32", ["no-resolve"], source_kind="custom", category_name="IP only"),
        PolicyRuleEntry("action-direct", "GEOIP", "CN", category_name="Geo"),
        PolicyRuleEntry("medium", "IP-ASN", "13335", category_name="Geo"),
        PolicyRuleEntry("medium", "AND", "((IP-CIDR,198.51.100.0/24),(DST-PORT,443))", category_name="Logical"),
    ]
    kind = case.get("rules_case")
    variants = {
        "ip-literal": [PolicyRuleEntry("medium", "IP-CIDR", "203.0.113.8/32", category_name="IP only")],
        "ip-no-resolve": [PolicyRuleEntry("medium", "IP-ASN", "13335", ["no-resolve"], category_name="IP only")],
        "logical": [entries[-1]],
        "remote": [PolicyRuleEntry("medium", "RULE-SET", "https://example.com/rules.txt"), PolicyRuleEntry("medium", "DOMAIN-SET", "https://example.com/domains.txt")],
        "system-only": [], "empty": [],
        "overlap": [PolicyRuleEntry("medium", "IP-CIDR", "203.0.113.0/24"), PolicyRuleEntry("action-direct", "IP-CIDR", "203.0.113.0/25")],
        "reject-variants": [PolicyRuleEntry("REJECT-TINYGIF", "DOMAIN", "ads.example.org")],
    }
    if kind == "src-ip":
        variants[kind] = [PolicyRuleEntry("medium", "SRC-IP-CIDR", "10.9.0.0/16", case["extras"], source_kind=case["source"], category_name="Source IP")]
    entries = variants.get(kind, entries)
    if case.get("nonfinite"):
        nodes[0].raw["extra-float"] = float(case["nonfinite"])

    if kind != "empty":
        entries = [*[replace(b._policy_rule_entry_from_line(line), source_kind="system") for line in HubService._clash_direct_rule_lines()], *entries]
    contracts = [RouteContract("medium", "Synthetic Proxy", routing_action="proxy", primary_pools=["medium"], strategy_type=case.get("strategy", "strict")),
                 RouteContract("synthetic-default", "Synthetic Default", routing_action=case.get("action", "proxy"), primary_pools=["medium"])]
    process = [ProcessRuleTemplate("p", "medium", "Synthetic Proxy", "PROCESS-NAME", "SyntheticApp")]
    external = [ExternalProxyProgramTemplate("e", "medium", "Synthetic Proxy", "/usr/bin/synthetic-proxy", ["--listen", "17891"], 17891, "Synthetic External")]
    ir = b.build_policy_ir(nodes, [], rule_entries=entries, contracts=contracts,
                           business_groups=[BusinessGroup(c.display_name, pool_names=["中等质量"]) for c in contracts],
                           default_contract_id="synthetic-default", device_strategy_preset=case.get("preset", "balanced"),
                           process_rules=process, external_proxy_programs=external)
    if kind == "manual-provider":
        ir.rule_providers = {"native-inline": {"type": "inline", "behavior": "classical", "payload": ["DOMAIN,manual.example.com"]}}
    settings, profile = case["settings"], case["profile"]
    args = dict(profile=profile, profile_settings=settings, policy_ir=ir)
    base = "https://sub.example.com/sub/device/synthetic/default/"
    clash, _, _ = b.build_clash_profile_artifacts(nodes, [], provider_base_url="https://sub.example.com", subscription_token="synthetic", **args)
    surge = b.build_surge_profile_artifacts(nodes, [], base+"surge.conf", revision="fixed-revision", **args)
    rocket = b.build_shadowrocket_profile_artifacts(nodes, [], base+"shadowrocket.conf", **args)
    result = {"clash.yaml": clash, "surge.conf": surge.main_conf, "shadowrocket.conf": rocket.content,
              "shadowrocket-nodes.txt": b.build_shadowrocket_nodes_subscription(nodes)[0],
              "surge-mac-overlay.conf": b.build_surge_mac_overlay(MacOverlayTemplate(base+"surge-mac-overlay.conf", base+"surge.conf", process, external))}
    result.update({"surge/domain/"+k+".txt": v for k,v in surge.domain_sets.items()})
    result.update({"surge/rules/"+k+".txt": v for k,v in surge.rule_sets.items()})
    for key in CLASH_PROVIDER_KEYS:
        result["providers/"+key+".yaml"] = b.build_clash_provider_config(nodes, key, policy_ir=ir, udp_default_enabled=settings.get("clash_udp_default_enabled", True))[0]
    if kind != "manual-provider":
        for key in (yaml.safe_load(clash).get("rule-providers") or {}):
            result["clash/rules/"+key+".txt"] = b.build_clash_rule_provider_config(nodes, [], key, **args)
    bundle = b.build_clash_export_bundle(nodes, [], device_name="Synthetic", device_key="synthetic", subscription_token="synthetic", generated_at="2026-01-01T00:00:00Z", **args)
    bundle = attach_clash_bundle_audit(bundle, profile=profile, base_url="https://sub.example.com")
    result.update({"bundle/"+k:v for k,v in bundle["files"].items()})
    return result


def render_corpus(root: Path, corpus: Path, output: Path) -> None:
    sys.path.insert(0, str(root))
    # Freeze the observed environment on both refs. Main historically sampled
    # these aliases inside rendering; the candidate receives explicit aliases.
    from app.services import subscription_builder
    subscription_builder._local_host_target_aliases = lambda: {"localhost", "127.0.0.1", "::1"}
    for case in json.loads(corpus.read_text()):
        for name, text in render_case(case).items():
            path = output / case["id"] / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))


def archive_ref(ref: str, destination: Path) -> str:
    sha = subprocess.check_output(["git", "rev-parse", ref], cwd=ROOT, text=True).strip()
    archive = subprocess.check_output(["git", "archive", "--format=tar", sha], cwd=ROOT)
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as data:
        data.extractall(destination, filter="data")
    return sha


def compare(base: Path, candidate: Path) -> dict:
    def files(root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    left, right = files(base), files(candidate)
    names = sorted(left.keys() | right.keys())
    differences = [name for name in names if left.get(name) != right.get(name)]
    return {"files": len(names), "identical": len(names)-len(differences), "differences": differences,
            "baseline_bytes": sum(map(len,left.values())), "candidate_bytes": sum(map(len,right.values())),
            "sha256": {name: hashlib.sha256(right[name]).hexdigest() for name in sorted(right)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--candidate", default="WORKTREE")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--render-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    args = parser.parse_args()
    if args.render_root:
        render_corpus(args.render_root, args.corpus, args.output_dir)
        return 0
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cases = json.loads(args.corpus.read_text())
    refs = {}
    for label, ref, seed in (("baseline", args.base, "7"), ("candidate", args.candidate, "37")):
        root = ROOT if ref == "WORKTREE" else out / (label+"-source")
        refs[label] = {"ref": ref, "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() if ref == "WORKTREE" else archive_ref(ref, root)}
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--render-root", str(root), "--corpus", str(args.corpus.resolve()), "--output-dir", str(out/label)], check=True, cwd=root,
                       env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"})
    result = {"refs": refs, "samples": len(cases), "clients": ["clash", "surge", "shadowrocket"],
              "families": sorted({c["family"] for c in cases if "family" in c}),
              "cards": sorted({c["card"] for c in cases if "card" in c}),
              "existing_fixtures": sum("fixture" in c for c in cases),
              **compare(out/"baseline", out/"candidate")}
    (out/"comparison.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k!="sha256"},ensure_ascii=False,indent=2))
    return bool(result["differences"])


if __name__ == "__main__":
    raise SystemExit(main())
