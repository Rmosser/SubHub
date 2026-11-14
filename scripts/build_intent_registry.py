#!/usr/bin/env python3
"""Compile the reviewed field/value specifications into the runtime registry."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "scripts/intent_registry_spec.json"
OUTPUT = ROOT / "app/services/intent_registry.json"
GENERIC_CONSEQUENCE = "该项在目标端缺少已证明的等价行为边界；保留原客户端编译，DNS、UDP 和策略选择仍可能不同。请核对这项声明的实际流量行为。"
PROCESS_ROOTS = {"ProcessRuleTemplate", "ExternalProxyProgramTemplate"}
STATUS_CODE_SUFFIXES = {"unsupported": "-unsupported", "pending_validation": "-pending-validation"}
MERGED_TABLE_KEY_PREFIXES = ("strict_contract_", "rule_type_dropped_")


def _family_consequence(spec, family, target):
    consequence = spec["consequences"].get(family, GENERIC_CONSEQUENCE)
    if isinstance(consequence, dict):
        # Each diagnostic is shown for one client. Families whose effect
        # differs per client keep one sentence per client, so the text can
        # state that client's exact situation.
        return consequence[target]
    return consequence


def _table_diagnostic_key(row, target, status):
    """Name the diagnostics-table entry whose code this routing projection uses.

    Runtime reports these projections through dedicated diagnostics instead
    of one warning per row, so the row must carry that diagnostic's code.
    """
    field = row.get("field", "")
    root = field.split(".")[0]
    if root in PROCESS_ROOTS:
        domain = "process" if root == "ProcessRuleTemplate" else "external"
        if target == "surge":
            return domain + "_migration_surge"
        return domain + "_overlay_" + target
    if field == "PolicyIR.ip_resolution":
        return "ip_defaults"
    if field == "RouteContract.strategy_type" and row.get("value") == "strict":
        # Strict contracts are merged into one warning per client.
        return "strict_contract_" + target
    # The standalone rule types left pending on Mihomo are the ones its
    # renderer drops (UID, PASS, PASS-RULE, REMATCH-NAME); runtime merges them
    # into one warning that names the dropped types. Blocked rule types
    # report through the routing evidence gap instead.
    is_standalone_rule_type = field == "PolicyRuleEntry.rule_type" and row["classification"] != "blocked"
    if is_standalone_rule_type and target == "clash" and status == "pending_validation":
        return "rule_type_dropped_clash"
    return None


def build_registry():
    spec = json.loads(SPEC.read_text())
    result = {"version": 2, "settings": [], "routing": [], "diagnostics": spec["diagnostics"]}
    udp = spec["udp_consequences"]
    for section in ("settings", "routing"):
        for source in spec[section]:
            row = {k: deepcopy(v) for k, v in source.items() if k != "targets"}
            projections = {}
            for target, source_p in source["targets"].items():
                p = deepcopy(source_p)
                if row["classification"] == "metadata":
                    p.update(status="not_projected", syntax="管理元数据，不参与设备投影", evidence=[dict(tag="已确认", reference="app/models.py" if not row.get("field", "").startswith("PinGroup.") else "app/storage/sqlite_repo.py", symbol=row.get("field", row["id"]))])
                family = row.get("family", row.get("field", row["id"]).replace(".", "-").replace("_", "-"))
                if row["classification"] == "blocked" and p["status"] == "supported":
                    raise ValueError(f"{row['id']}: blocked specification cannot claim supported {target}")
                code = "" if p["status"] in {"supported", "not_projected"} else f"intent-{family}-{target}-{p['status'].replace('_', '-')}".lower()
                field = row.get("field", "")
                table_key = None
                if section == "routing" and code:
                    table_key = _table_diagnostic_key(row, target, p["status"])
                    if table_key:
                        code = spec["diagnostics"][table_key]["code"]
                    elif field == "RouteContract.strategy_type":
                        status_suffix = p["status"].replace("_", "-")
                        code = f"intent-contract-{row['value']}-{target}-{status_suffix}"
                    elif row["classification"] == "blocked":
                        code = spec["diagnostics"]["routing_gap_"+target]["code"]
                    else:
                        code = f"intent-{family}-{target}-{p['status'].replace('_', '-')}".lower()
                # Only projections that emit a code need a consequence; per-client
                # families do not define text for clients they never warn on.
                message = ""
                if code:
                    message = _family_consequence(spec, row.get("family"), target)
                if row["id"] == "clash_udp_default_enabled":
                    message = "节点没有显式指定 UDP 时：" + udp[target]
                if row["id"] == "clash_tcp_concurrent":
                    message = "此兼容字段不下发，不能据此改变 TCP 并发连接行为；请不要依赖它控制设备连接。"
                if row["id"] == "surge_skip_proxy" and target == "clash":
                    message = "此值确实生成本端 DIRECT 规则和 TUN 排除路由；这不等于绕过系统代理。请核对域名和 IP 的实际去向。"
                if row.get("field") == "RouteContract.strategy_type" and row.get("value") == "load-balance" and target == "shadowrocket":
                    message = "该负载均衡契约在 Shadowrocket 仍输出 persistent=1，但参数和会话粘性未被验证；请求可能采用不同出口分配或同一会话跨节点。请验证会话出口，或审阅后改用 select/fallback。"
                if row.get("field") == "PolicyRuleEntry.rule_type" and code:
                    message = (f"该客户端没有已确认的 {row['value']} 匹配条件；保留既有文件和编译处理，流量可能跳过此条件而命中后续规则或兜底。请改为已确认的条件并核对去向。" if p["status"] == "unsupported" else f"{row['value']} 仍按现有方言输出，但大小写、DNS 和接管路径的边界不能概括为三端等价；请核对该条件实际匹配与后续去向。")
                if code == spec["diagnostics"].get("routing_gap_"+target, {}).get("code"):
                    message = spec["diagnostics"]["routing_gap_"+target]["message"]
                if table_key and table_key.startswith(MERGED_TABLE_KEY_PREFIXES):
                    # These warnings are merged per client and their text lives
                    # with the merged diagnostic, not in a consequence family.
                    message = spec["diagnostics"][table_key]["message"]
                if section == "settings" and p["status"] == "unsupported":
                    message = f"本项没有可证明等价的 {target} 投影。" + message
                p.update(diagnostic_code=code, consequence=message if code else "")
                projections[target] = p
            row["projections"] = projections
            result[section].append(row)
    return result


def validate_equivalence(registry):
    for section in ("settings", "routing"):
        for row in registry[section]:
            if row["classification"] not in {"shared", "adapted"}:
                continue
            for target, p in row["projections"].items():
                if p["status"] != "supported":
                    raise ValueError(f"{row['id']} has unproven {target} equivalence")
                if not p["evidence"] or any(e["tag"] not in {"已确认", "实机验证"} or e.get("gap") for e in p["evidence"]):
                    raise ValueError(f"{row['id']} has insufficient {target} evidence")


def validate_projection_codes(registry):
    """Keep the registry limited to codes that runtime diagnostics can emit."""
    for section in ("settings", "routing"):
        for row in registry[section]:
            owner = row.get("scope")
            for target, projection in row["projections"].items():
                status = projection["status"]
                code = projection["diagnostic_code"]
                # Runtime diagnostics skip rows scoped to another client, so a
                # foreign projection could never emit a code. Check the code
                # as well as the status: either one alone can be edited.
                if owner and target != owner and (status != "not_projected" or code):
                    raise ValueError(
                        f"{row['id']}: {target} is outside the row scope and must be not_projected without a code"
                    )
                for expected_status, suffix in STATUS_CODE_SUFFIXES.items():
                    if code.endswith(suffix) and status != expected_status:
                        raise ValueError(f"{row['id']}: {target} code {code} does not match status {status}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    registry = build_registry()
    validate_equivalence(registry)
    validate_projection_codes(registry)
    content = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        return int(not OUTPUT.exists() or OUTPUT.read_text() != content)
    OUTPUT.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
