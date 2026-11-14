"""Build replica data files from inventory/<app>.json + tokens/<app>.json.
Run: ./.venv/bin/python design/client-ui-replica/replica/build_data.py
Only layout numbers that inventory does not carry (status time, scroll offset, tab bar) live here."""
import json, os, pathlib, re
ROOT = pathlib.Path(__file__).resolve().parent.parent
inv = lambda app: json.loads((ROOT / f"inventory/{app}.json").read_text())
tok = lambda app: json.loads((ROOT / f"tokens/{app}.json").read_text())

def rows_from(group, value_override=None):
    out = []
    for r in group["rows"]:
        ctl = r["control"]
        d = {"label": r["label"], "subhub": r.get("subhub_zh"), "maps_to": r.get("maps_to")}
        if ctl in ("disclosure",):
            d["accessory"] = "chevron"
            v = r.get("value")
            if v:
                d["detail"] = v.split(" · ")[0]
        elif ctl == "toggle":
            v = str(r.get("value", ""))
            d["accessory"] = "switch"; d["on"] = v.startswith("开")
            m = re.search(r"副标题「(.+?)」", v)
            if m:
                d["sub"] = m.group(1)
        elif ctl == "popup":
            d["accessory"] = "updown"
            d["detail"] = str(r.get("value", "")).replace("⌃⌄", "").strip()
        elif ctl == "button":
            d["style"] = "danger"
        out.append(d)
    return out

def shadowrocket_config_edit():
    s = next(x for x in inv("shadowrocket")["screens"] if x["id"] == "config-edit")
    t = tok("shadowrocket")
    groups = [{"rows": rows_from(g)} for g in s["groups"]]
    return {
        "app": "shadowrocket", "screen": s["id"], "theme": "shadowrocket",
        "reference": "../screens/shadowrocket/config-edit_1.png",
        "nav": {"left": "back", "title": s["title"], "right": "plus"},
        "status": {"time": "01:35", "battery": "80"},
        "content_top": t["layout"]["group"]["first_group_top_pt"], "row_h": t["layout"]["row"]["height_pt"],
        "group_gap": t["layout"]["group"]["gap_between_groups_pt"],
        "groups": groups,
        "tabbar": {"x": t["layout"]["tab_bar"]["x_pt"], "selected": 1,
                   "items": [{"icon": "home", "label": "首页"}, {"icon": "folder", "label": "配置"},
                             {"icon": "activity", "label": "数据"}, {"icon": "gear", "label": "设置"}]},
    }

def surge_more_advanced(scroll=0, shot="more-advanced_1"):
    """Surge 首页 › 通用 › 更多设置（高级）。几何来自 tokens/surge.json，2026-11-11 复测。"""
    s = next(x for x in inv("surge")["screens"] if x["id"] == "more-advanced")
    t = tok("surge")["layout"]
    groups = []
    for g in s["groups"]:
        rows = rows_from(g)
        for r in rows:
            if r.get("sub"):
                r["h"] = t["row"]["height_with_subtitle_pt"]
        groups.append({"header": g.get("header"), "footer": g.get("footer"), "rows": rows})
    # 卡片间距：上一张卡片底到下一张卡片顶。前一组有 footer 时更大（footer 占 3 行 / 1 行）。
    groups[1]["gap_before"] = t["group"]["gap_card_to_next_card_with_header_pt"]
    for i in range(2, len(groups)):
        foot = groups[i-1].get("footer") or ""
        units = sum(1 if ord(ch) > 0x2E80 else 0.55 for ch in foot)
        lines = -(-int(units * 10) // 255)   # 13 pt 字，宽 329 pt ≈ 25.5 个汉字宽
        groups[i]["gap_before"] = t["group"]["gap_after_footer_pt"][str(lines)] if foot else t["group"]["gap_card_to_next_card_with_header_pt"]
    return {
        "app": "surge", "screen": "more-advanced" + ("" if scroll == 0 else "-scrolled"), "theme": "ios26",
        "reference": f"../screens/surge/{shot}.png",
        "nav": {"left": "close", "title": s["title"], "right": "check", "center_y": t["nav_bar"]["button_center_y_pt"],
                "material": t["nav_bar"]["scrolled_material"] if scroll else None},
        "sheet": {"top": t["sheet"]["top_pt"], "radius": t["sheet"]["corner_radius_pt"]},
        "status": {"time": "01:55", "battery": "80"},
        "content_top": t["group"]["first_card_top_pt"] - scroll, "row_h": t["row"]["height_pt"],
        "header_offset": t["group"]["header_center_above_card_pt"], "footer_offset": t["group"]["footer_top_below_card_pt"],
        "groups": groups,
    }

def clash_profile_global():
    """Clash（代替 Clash Mi）配置中心 › 当前配置 ⓘ › 全局配置。几何来自 tokens/clash.json。"""
    s = next(x for x in inv("clash")["screens"] if x["id"] == "profile-global")
    t = tok("clash")["layout"]
    groups = [{"header": g.get("header"), "footer": g.get("footer"), "rows": rows_from(g)} for g in s["groups"]]
    for r in (row for g in groups for row in g["rows"]):
        if r.get("accessory") == "chevron" and r.get("detail") is None:
            pass
    # popup 行在 inventory 里有的带 ⌃⌄、有的没写；全局配置页里 popup 一律是蓝色值 + ⌃⌄
    for g, src in zip(groups, s["groups"]):
        for r, sr in zip(g["rows"], src["rows"]):
            if sr["control"] == "popup":
                r["accessory"] = "updown"; r["detail"] = str(sr.get("value", "")).replace("⌃⌄", "").strip()
    fs = t["floating_search"]
    floating = [{**f, "geom": {"x": fs["x_pt"], "y": fs["y_pt"], "icon_x": fs["icon_x_pt"][0], "text_left": fs["text_left_pt"]}}
                for f in s.get("floating", [])]
    sh = t["sheet"]
    return {
        "app": "clash", "screen": "profile-global", "theme": "ios26 theme-clash",
        "reference": "../screens/clash/profile-global_1.png",
        "nav": {"left": "back", "title": s["title"], "center_y": t["nav_bar"]["button_center_y_pt"]},
        "sheet": {"top": sh["top_pt"], "radius": sh["corner_radius_pt"],
                  "back": {"top": sh["back_sheet"]["top_pt"], "x": sh["back_sheet"]["x_pt"],
                           "radius": sh["back_sheet"]["corner_radius_pt"], "color": sh["back_sheet"]["color"]}},
        "status": {"time": "02:15", "battery": "80"},
        "content_top": t["group"]["first_card_top_pt"], "row_h": t["row"]["height_pt"],
        "group_gap": t["group"]["gap_card_to_next_card_with_header_pt"],
        "header_offset": t["group"]["header_center_above_card_pt"], "footer_offset": 8.6,
        "groups": groups, "floating": floating,
    }

def clash_mi_core_settings():
    """Clash Mi 首页 › 核心设置。几何来自 tokens/clash-mi.json。"""
    s = next(x for x in inv("clash-mi")["screens"] if x["id"] == "core-settings")
    t = tok("clash-mi")["layout"]
    groups = []
    for g in s["groups"]:
        rows = []
        for r in g["rows"]:
            v = str(r.get("value") or "")
            d = {"label": r["label"], "subhub": r.get("subhub_zh"), "maps_to": r.get("maps_to"), "info": r.get("info_icon", False)}
            c = r["control"]
            if c == "textfield":
                d["field"] = v.split("（")[0].strip(); d["placeholder"] = "占位" in v
                if r["label"] == "Pprof Address":
                    d["field_x"] = t["row"]["field_pt"]["x_wide"]
            elif c == "popup":
                d["detail"] = v.replace("▾", "").strip(); d["accessory"] = "caret"; d["small"] = True
            elif c == "disclosure":
                d["accessory"] = "chevron"
                if v:
                    d["detail"] = v.replace("›", "").strip(); d["small"] = True
            rows.append(d)
        groups.append({"rows": rows})
    n = t["nav_bar"]
    # Secret 的值在参考截图里已涂黑（窗口像素 300,412–600,460）；复刻图在同一位置画黑块，便于逐像素比较
    red = [[(300 - 8) / 1.5, (412 - 38) / 1.5, (600 - 8) / 1.5, (460 - 38) / 1.5]]
    return {
        "app": "clash-mi", "screen": "core-settings", "theme": "clashmi",
        "reference": "../screens/clash-mi/core-settings_1.png",
        "nav": {"flat": True, "left": "flatback", "left_box": n["back_glyph_pt"][:2], "title": s["title"],
                "right": "doc", "right_box": n["right_icon_pt"][:2], "center_y": n["title_center_y_pt"]},
        "status": {"time": "09:50", "battery": "80", "crumb": "App Store"},
        "content_top": t["group"]["first_card_top_pt"], "row_h": t["row"]["pitch_pt"], "group_gap": t["group"]["gap_pt"] - (t["row"]["pitch_pt"] - t["row"]["height_pt"]),   # row_h 是含分隔线的行距，卡片最后一行没有分隔线
        "scroll_bottom": t["scroll_bottom_pt"], "groups": groups, "redactions": red,
        "group_margin_pt": t["group"]["card_x_pt"][0],
    }

out = pathlib.Path(os.environ.get("UI_REPLICA_DATA_OUT", ROOT / "replica/data")); out.mkdir(parents=True, exist_ok=True)
for fn in [shadowrocket_config_edit, surge_more_advanced,
           lambda: surge_more_advanced(scroll=373.7, shot="more-advanced_2"), clash_profile_global, clash_mi_core_settings]:
    d = fn()
    (out / f"{d['app']}-{d['screen']}.js").write_text("window.REPLICA=" + json.dumps(d, ensure_ascii=False, indent=1) + ";\n")
    print("wrote", d["app"], d["screen"])
