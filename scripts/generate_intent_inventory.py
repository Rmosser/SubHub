#!/usr/bin/env python3
"""Generate the design inventory from the executable projection registry."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "app/services/intent_registry.json"
OUTPUT = ROOT / "docs/design-docs/intent-inventory.md"


def render_inventory() -> str:
    registry = json.loads(REGISTRY.read_text())
    lines = ["# 意图投影登记表", "", "由 `scripts/generate_intent_inventory.py` 从 `app/services/intent_registry.json` 生成。修改 scripts/intent_registry_spec.json 后，先运行 scripts/build_intent_registry.py，再生成本表。", "", "证据基线：用户指定 proxy-config-writer 0.3.0；Surge iOS 5.23.0、Shadowrocket 2.2.93、Mihomo v1.19.33。文献章节号与实验编号保留 Skill 的证据等级；缺少证据的映射不升级为已确认。", ""]
    for title, key in (("Profile 设置（含专家字段和镜像 key）", "settings"), ("分流声明和上下文", "routing")):
        rows=registry[key]
        counts=Counter(r["classification"] for r in rows)
        lines.extend(["## "+title,"",f"共 {len(rows)} 项；"+"、".join(f"{name} {counts[name]}" for name in ("shared","adapted","blocked","standalone","metadata"))+"。","", "| 字段 | 意图与归类理由 | 分类 | Mihomo | Surge | Shadowrocket |", "| --- | --- | --- | --- | --- | --- |"])
        for row in rows:
            columns=[]
            for target in ("clash","surge","shadowrocket"):
                projection=row["projections"][target]
                evidence="；".join("["+e["tag"]+"] "+(e.get("id") or e.get("gap") or ((e.get("reference") or "")+" §"+e.get("section", e.get("symbol", "")))) for e in projection["evidence"])
                note=projection["syntax"]+"；"+projection["status"]+"；"+evidence
                if projection["diagnostic_code"]: note+="；`"+projection["diagnostic_code"]+"`："+projection["consequence"]
                columns.append(note.replace("|","\\|"))
            lines.append("| `"+row["id"]+"` | "+row["intent"]+"；"+row["reason"]+" | "+row["classification"]+" | "+" | ".join(columns)+" |")
        lines.append("")
    lines.extend(["## 版本敏感字段", "", "版本依据记录在各设置的 `version_gates`。本阶段保留历史输出，不新增版本拒绝或 409；未指定客户端版本时不能把输出视为已证明能在任意版本工作。后续版本门控若会删字段或改变流量，须作为单独批准的行为变更。", "", "| 字段 | 门槛 |", "| --- | --- |"])
    for row in registry["settings"]:
        if row["version_gates"]: lines.append("| `"+row["id"]+"` | `"+json.dumps(row["version_gates"],ensure_ascii=False)+"` |")
    lines.extend(["", "## 跨域诊断定义", "", "| 代码 | 白话消息模板 | 证据 |", "| --- | --- | --- |"])
    for item in registry["diagnostics"].values():
        evidence = "；".join(e.get("id") or e.get("gap") or str(e.get("reference")) + " §" + e.get("section", "") for e in item["evidence"])
        lines.append("| `"+item["code"]+"` | "+item["message"]+" | "+evidence+" |")
    return "\n".join(lines)+"\n"


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    text=render_inventory()
    if args.check:
        return int(not OUTPUT.exists() or OUTPUT.read_text()!=text)
    OUTPUT.write_text(text)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
