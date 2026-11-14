"""Build the 配置与场景 read-map screen data for the frontend.

inventory/<app>.json (UI tree) + tokens/<app>.json (geometry) + readmap/binds/<app>.json (bind / explain / paper)
  + readmap/about/<app>.json (what each control does; `@…` keys are the app's own chrome: 启动, tabs, nav buttons)
  -> frontend/src/pages/Profile/readmap/data/<app>.json

Every row and every piece of chrome the phone draws answers a tap, so each one needs words: an explain, an
about or a paper (rows), or an `@…` entry (chrome). A missing one fails the build.

Run: ./.venv/bin/python design/client-ui-replica/readmap/build_readmap.py
Only structure is carried over. Values captured from the reference phones are dropped: the page shows
values parsed from the live render-preview content, and nothing for rows SubHub does not write."""
import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT.parent.parent
OUT = REPO / "frontend/src/pages/Profile/readmap/data"
APPS = ["shadowrocket", "surge", "clash-mi"]
REL = {"writes": "w", "partial": "p", "none": "n", "device": "d", "unverified": "u", "na": ""}
LAYER = {"profile": "p", "app": "a", "action": "x"}
THEME = {"shadowrocket": "shadowrocket", "surge": "ios26", "clash-mi": "clashmi"}
TABS = {
    "shadowrocket": [{"icon": "home", "label": "首页"}, {"icon": "folder", "label": "配置"},
                     {"icon": "activity", "label": "数据"}, {"icon": "gear", "label": "设置"}],
}
TAB_OF_ROOT = {"shadowrocket": {"tab-home": 0, "tab-config": 1}}
# Names the reference screenshots carried from the owner's phone. {file} / {name} resolve at runtime from the
# rendered config (managed URL basename), so the page never shows someone's local file names.
LABEL_FIX = {
    "surge": {"title": {"home-general": "{name}", "home-capture": "{name}", "home-modify": "{name}"}, "row": {}},
    "shadowrocket": {
        "title": {"config-edit": "{file}"},
        "row": {"tab-home#0.0": "连接", "tab-home#1.0": "{name}", "tab-config#1.0": "{file}"},
        "drop": ["tab-config#1.1"],
    },
}


def clean_label(s: str) -> str:
    s = re.sub(r"（[^）]*）", "", s)
    s = re.sub(r"\s*[ⓘ›⌄]\s*$", "", s)
    return s.strip()


def clean_footer(s: str) -> str:
    """Footers are the screen's own words, parentheses included; only the transcriber's notes go."""
    s = re.sub(r"（(?:脚注|截断)[^）]*）", "", s)
    return s.strip()


# The lit state already says "SubHub wrote this"; drop sentences' bare restatements of it.
_WRITTEN = re.compile(
    r"[，,]\s*(?:[^，,。：]{0,6}?(?:由|全由|都是)\s*)?SubHub\s*(?:逐条|按(?:来源|节点|条目|配置|分组|规则|地址))?写入(?:的)?"
    r"(?:[，,]\s*(?:这里)?默认打码)?(?=。?$)"
)


def clean_explain(s: str) -> str:
    out = _WRITTEN.sub("", s)
    return out if out.endswith("。") else out + "。"


def accessory(ctl: str, app: str):
    if ctl in ("disclosure", "disclosure-group", "link", "menu"):
        return "chevron"
    if ctl in ("toggle", "toggle-row"):
        return "switch"
    if ctl == "popup":
        return "caret" if app == "clash-mi" else "updown"
    if ctl == "radio":
        return "radio"
    return None


def nav_of(app: str, inv_nav: dict, is_root: bool, sheet: bool):
    left_t, right_t = inv_nav.get("left", "") or "", inv_nav.get("right", "") or ""
    if is_root:
        left = "scan" if app == "shadowrocket" else None
    elif "✕" in left_t:
        left = "close"
    else:
        left = "flatback" if app == "clash-mi" else "back"
    right = None
    if "✓" in right_t:
        right = "check" if app == "surge" else "tick"
    elif "保存" in right_t:
        right = "save"
    elif "☁" in right_t and "+" in right_t:
        right = "cloudplus"
    elif "+" in right_t:
        right = "plus"
    elif "📄" in right_t:
        right = "doc"
    return {"left": left, "right": right}


# Text fields drawn bare, with no label beside them: the value (or the placeholder) fills the field.
SOLO = {"surge": {"more-advanced-latency#0.0", "more-advanced-latency#1.0"}}
_PLACEHOLDER = re.compile(r"^空（占位(?:「(.+?)」)?）")


def solo_field(app: str, rid: str, r: dict):
    """(solo, placeholder) for a textfield row. Surge marks bare fields as 「空（占位…）」 in the inventory."""
    if r["control"] != "textfield" or app != "surge":
        return None
    m = _PLACEHOLDER.match(r.get("value") or "")
    if m:
        return m.group(1) or clean_label(r["label"])
    if rid in SOLO.get(app, set()):
        return clean_label(r["label"])
    return None


LEAVES = {"back", "close", "flatback"}
SURGE_HOME_CHROME = ["profile", "start", "bar:home", "bar:tools", "bar:more"]
SR_TOOLS = ["tool:route", "tool:refresh", "tool:more"]


def shell_ids(app: str, out: dict) -> list:
    """The app's own chrome drawn on a screen (must match phoneKit.ts): each id answers a tap with an explanation."""
    ids = []
    for kind in (out["nav"].get("left"), out["nav"].get("right")):
        if kind == "cloudplus":
            ids += ["nav:cloud", "nav:plus"]
        elif kind and kind not in LEAVES:
            ids.append(f"nav:{kind}")
    if app == "surge" and out.get("segment"):
        ids += SURGE_HOME_CHROME
    if app in TABS and "tab" in out:
        rooted = set(TAB_OF_ROOT.get(app, {}).values())
        ids += [f"tab:{t['icon']}" for i, t in enumerate(TABS[app]) if i not in rooted]
    if app == "shadowrocket" and out["id"] == "tab-home":
        ids += SR_TOOLS
    return ids


def geometry(app: str, tok: dict) -> dict:
    t = tok["layout"]
    if app == "shadowrocket":
        return {"content_top": t["group"]["first_group_top_pt"], "row_h": t["row"]["height_pt"],
                "group_gap": t["group"]["gap_between_groups_pt"], "nav_cy": t["nav_bar"]["button_center_y_pt"],
                "tabbar": {"x": t["tab_bar"]["x_pt"]}}
    if app == "surge":
        return {"content_top": t["group"]["first_card_top_pt"] - 40, "row_h": t["row"]["height_pt"],
                "row_h_sub": t["row"]["height_with_subtitle_pt"],
                "group_gap": t["group"]["gap_card_to_next_card_with_header_pt"] - 30,
                "nav_cy": t["nav_bar"]["button_center_y_pt"],
                "sheet": {"top": t["sheet"]["top_pt"], "radius": t["sheet"]["corner_radius_pt"]}}
    g, r = t["group"], t["row"]
    return {"content_top": g["first_card_top_pt"], "row_h": r["pitch_pt"], "group_gap": g["gap_pt"],
            "nav_cy": t["nav_bar"]["title_center_y_pt"], "group_margin": g["card_x_pt"][0]}


def build(app: str) -> dict:
    inv = json.loads((ROOT / f"inventory/{app}.json").read_text())
    tok = json.loads((ROOT / f"tokens/{app}.json").read_text())
    binds = json.loads((ROOT / f"readmap/binds/{app}.json").read_text())
    # What each control does on the phone, for rows SubHub does not write (readmap/about/<app>.json).
    about_file = ROOT / f"readmap/about/{app}.json"
    about = json.loads(about_file.read_text()) if about_file.exists() else {}
    inv_screens = {s["id"]: s for s in inv["screens"]}
    by_row = {r["row"]: r for r in binds["rows"]}
    dropped = {d for r in binds["rows"] for d in r.get("drop", [])}
    geo = geometry(app, tok)
    screens = {}
    missing = []
    wanted = {s["id"]: s for s in binds["screens"]}
    # `to` links: inventory links that stay inside the wanted set, plus each wanted screen's `via` row.
    via_to = {s["via"]: s["id"] for s in binds["screens"] if s.get("via") and "#" in s["via"]}
    for sid, meta in wanted.items():
        src = inv_screens.get(sid)
        if src is None:
            sys.exit(f"{app}: screen {sid} missing from inventory")
        is_root = meta.get("parent") is None
        sheet = "✕" in ((src.get("nav") or {}).get("left") or "") and not is_root
        groups = []
        for gi, g in enumerate(src["groups"]):
            rows = []
            for ri, r in enumerate(g["rows"]):
                rid = f"{sid}#{gi}.{ri}"
                if rid in dropped or rid in LABEL_FIX.get(app, {}).get("drop", []):
                    continue
                b = by_row.get(rid, {})
                ctl = r["control"]
                to = via_to.get(rid) or (r.get("to") if r.get("to") in wanted else None)
                row = {"id": rid, "label": LABEL_FIX.get(app, {}).get("row", {}).get(rid) or clean_label(r["label"]), "ctl": ctl,
                       "rel": REL.get(r.get("subhub"), "")}
                if LAYER.get(r.get("layer")):
                    row["layer"] = LAYER[r["layer"]]
                if about.get(rid):
                    row["about"] = about[rid]
                acc = accessory(ctl, app)
                if to:
                    row["to"] = to
                    acc = acc or "chevron"
                if acc:
                    row["acc"] = acc
                if r.get("info_icon"):
                    row["info"] = True
                if row["label"].startswith("<") or ctl == "placeholder":
                    row["ph"] = True
                ph = solo_field(app, rid, r)
                if ph is not None:
                    row["solo"] = True
                    row["placeholder"] = ph
                if ctl == "placeholder":
                    row["empty_only"] = True
                for k in ("bind", "explain", "paper", "override", "fixed"):
                    if k in b:
                        row[k] = clean_explain(b[k]) if k == "explain" and b[k] else b[k]
                if wanted.get(to, {}).get("deferred"):
                    row.pop("to", None)
                rows.append(row)
            if rows or g.get("header"):
                grp = {k: f(v) for k, v, f in (("header", g.get("header"), clean_label), ("footer", g.get("footer"), clean_footer)) if v and f(v)}
                grp["rows"] = rows
                groups.append(grp)
        fix = LABEL_FIX.get(app, {})
        title = fix.get("title", {}).get(sid) or clean_label(meta.get("title") or src["title"])
        out = {"id": sid, "title": title, "parent": meta.get("parent"),
               "via": meta.get("via"), "kind": meta.get("kind"), "sheet": sheet,
               "nav": nav_of(app, src.get("nav") or {}, is_root, sheet), "groups": groups}
        if meta.get("deferred"):
            out["deferred"] = True
        if app in TABS and sid in TAB_OF_ROOT.get(app, {}):
            out["tab"] = TAB_OF_ROOT[app][sid]
        if (meta.get("via") or "").startswith("segment:") or (is_root and app == "surge"):
            out["segment"] = True
        # The app's own chrome on this screen: `@<id>@<screen>` in about/<app>.json wins over `@<id>`.
        shell = {}
        for cid in shell_ids(app, out):
            text = about.get(f"@{cid}@{sid}") or about.get(f"@{cid}")
            if not text:
                missing.append(f"{sid}: chrome @{cid}")
            else:
                shell[cid] = text
        if shell:
            out["shell"] = shell
        screens[sid] = out
    # Screens whose entry row is missing (config-script-new has via null): add a list template row to the parent.
    for sid, meta in wanted.items():
        if meta.get("parent") and not meta.get("via") and not meta.get("deferred"):
            parent = screens[meta["parent"]]
            item_bind = next((by_row[k]["bind"] for k in by_row if k.startswith(sid + "#")), None)
            if item_bind:
                tpl = {"kind": "list", "ini": item_bind.get("ini"), "line": item_bind.get("line"), "label_part": "name"}
                rid = f"{meta['parent']}#t.0"
                parent["groups"].append({"rows": [{"id": rid, "label": "", "ctl": "disclosure", "rel": "w", "to": sid,
                                                   "acc": "chevron", "bind": {k: v for k, v in tpl.items() if v},
                                                   "explain": by_row.get(f"{sid}#0.0", {}).get("explain")}]})
                screens[sid]["via"] = rid
    # A tap on any row that does not push a screen selects it and explains it; it must have words to show.
    for sid, out in screens.items():
        if out.get("deferred"):
            continue
        for g in out["groups"]:
            for row in g["rows"]:
                if not row.get("to") and not (row.get("explain") or row.get("about") or row.get("paper")):
                    missing.append(f"{sid}: row {row['id']} 「{row['label']}」")
    if missing:
        sys.exit(f"{app}: nothing to say for {len(missing)} drawn control(s); add an explain (binds) or about (about/{app}.json):\n  "
                 + "\n  ".join(missing))
    return {"client": app, "target": binds["target"], "format": binds["format"], "theme": THEME[app],
            "root": binds["root"], "roots": binds.get("roots") or [binds["root"]], "geometry": geo,
            "tabs": TABS.get(app), "screens": screens}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for app in APPS:
        d = build(app)
        text = json.dumps(d, ensure_ascii=False, indent=1) + "\n"
        (OUT / f"{app}.json").write_text(text)
        rows = sum(len(g["rows"]) for s in d["screens"].values() for g in s["groups"])
        bound = sum(1 for s in d["screens"].values() for g in s["groups"] for r in g["rows"] if "bind" in r)
        print(f"wrote {app}: {len(d['screens'])} screens, {rows} rows, {bound} bound")


if __name__ == "__main__":
    main()
