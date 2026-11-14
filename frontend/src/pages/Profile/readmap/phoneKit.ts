/* Draws one resolved phone screen. Pure string rendering; selection and light are toggled later
   through classes so a redraw never resets scroll or transitions.
   Three layouts, all measured from the real screens: the iOS grouped list (every settings screen),
   the Surge home cards (通用 / 捕获 / 修改) and the Clash Mi home cards. Whatever the layout, a thing
   the map explains is a `.row` carrying data-key / data-row, so selection, wires and the deck stay
   layout-blind. */
import { ICON, LEAD_ICON, SR_TOOLS, SURGE_ICON, TRAIL_ICON } from "./icons";
import type { ClientMap, RGroup, RRow, RScreen } from "./model";
import { MASK, secretSpans } from "./mask";

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

/** Phone rows never reveal secrets: anything the mask rules catch is replaced outright. */
function safe(v: string | undefined): string | undefined {
  if (v == null) return v;
  const spans = secretSpans(v);
  if (!spans.length) return v;
  let out = "", at = 0;
  for (const sp of spans) { out += v.slice(at, sp.from) + MASK; at = sp.to; }
  return out + v.slice(at);
}

export interface ScreenChrome {
  segments?: { id: string; label: string; on: boolean }[];
  tabs?: { icon: string; label: string; root?: string; on: boolean }[];
}

/* ---------- what each app draws beside a row (display only; the data stays app-neutral) ---------- */

/** Leading icon per row, `${client}:${row id}`. */
const LEAD: Record<string, string> = {
  "shadowrocket:tab-home#0.0": "rocket", "shadowrocket:tab-home#0.1": "wheel", "shadowrocket:tab-home#0.2": "gauge",
  "shadowrocket:tab-home#1.0": "chevdown",
  "shadowrocket:tab-config#0.0": "undo", "shadowrocket:tab-config#0.1": "cloud", "shadowrocket:tab-config#0.2": "wifi",
  "shadowrocket:tab-config#0.3": "braces", "shadowrocket:tab-config#0.4": "flask",
  "clash-mi:home#1.0": "mgear", "clash-mi:home#1.1": "mgear", "clash-mi:home#1.2": "mlog",
  "clash-mi:home#1.3": "msync", "clash-mi:home#1.4": "mhelp", "clash-mi:home#1.5": "minfo",
};
/** Trailing glyph that replaces the accessory, as the real screen draws it. */
const TRAIL: Record<string, string> = {
  "shadowrocket:tab-config#0.0": "chevron", "shadowrocket:tab-config#0.1": "chevron",
  "shadowrocket:tab-config#0.2": "chevron", "shadowrocket:tab-config#0.4": "chevron",
  "shadowrocket:tab-home#0.2": "ctest", "shadowrocket:tab-home#1.0": "info", "shadowrocket:tab-home#1.1": "info",
  "shadowrocket:tab-config#1.0": "info",
  "clash-mi:home#0.2": "plus",
};
/** Rows whose leading slot is the node's round flag. */
const FLAG_ROWS = new Set(["shadowrocket:tab-home#1.1"]);
/** Rows whose value the real screen does not print (the Shadowrocket node group shows no count). */
const NO_DETAIL = new Set(["shadowrocket:tab-home#1.0"]);
/** Surge list rows whose subtitle is a coloured badge (protocol / rule type) and a small black detail. */
const BADGE: Record<string, string> = { "surge:home-proxies#0.0": "#497DFB", "surge:home-rules#1.0": "#5F59F2" };
/** Protocol names as Surge prints them in the badge. */
const PROTO: Record<string, string> = {
  ss: "Shadowsocks", vmess: "VMess", vless: "VLESS", trojan: "Trojan", http: "HTTP", https: "HTTPS", socks5: "SOCKS5",
  "socks5-tls": "SOCKS5 TLS", snell: "Snell", tuic: "TUIC", "tuic-v5": "TUIC", hysteria2: "Hysteria2", wireguard: "WireGuard",
  anytls: "AnyTLS", ssh: "SSH", direct: "DIRECT", reject: "REJECT",
};
/** Surge list rows led by a red minus (an entry you can delete) or a green plus (an add action). */
const MINUS_ROWS = new Set(["surge:home-dns#1.0"]);
/** Segmented controls drawn as a track of options. */
const OPTIONS: Record<string, string[]> = { "clash-mi:home#0.1": ["规则", "全局", "直连"] };
/** Surge home cards: title colour and glyph, keyed by the card title. `ls`: the description's tracking where the
    browser's glyphs run wider than the phone's (数据包捕获: "TCP/UDP/ICMP" is ~5pt wider here; the phone keeps it on one line). */
const SURGE_CARD: Record<string, { c: string; i: string; ls?: string }> = {
  "出站模式": { c: "#4350C3", i: "outbound" }, "DNS": { c: "#79B52E", i: "dns" }, "Surge Ponte": { c: "#D6793C", i: "ponte" },
  "捕获流量": { c: "#D69A32", i: "capture" }, "MitM": { c: "#B2557F", i: "mitm" }, "数据包捕获": { c: "#463E8F", i: "pcap", ls: "-.45px" },
  "HTTP 重写": { c: "#D06838", i: "rewrite" }, "脚本": { c: "#AC4F99", i: "script" }, "模块": { c: "#8040B8", i: "module" },
};

const FLAG_RE = /[\u{1F1E6}-\u{1F1FF}]{2}/u;

/* ---------- pieces ---------- */

function statusbar() {
  return `<div class="statusbar"><div class="time">9:41</div><div class="island"></div><div class="right">
<svg width="20" height="12" viewBox="0 0 20 12"><g fill="currentColor"><rect x="0" y="8" width="3.2" height="4" rx=".8"/><rect x="5.4" y="5.5" width="3.2" height="6.5" rx=".8"/><rect x="10.8" y="3" width="3.2" height="9" rx=".8"/><rect x="16.2" y="0" width="3.2" height="12" rx=".8"/></g></svg>
<svg width="17" height="12" viewBox="0 0 17 12"><path d="M8.5 11.5 5.8 8.4a3.8 3.8 0 0 1 5.4 0zM3.4 6.1a7.2 7.2 0 0 1 10.2 0l1.6-1.7a9.6 9.6 0 0 0-13.4 0zM.1 2.6a12 12 0 0 1 16.8 0" fill="currentColor"/></svg>
<svg width="28" height="13" viewBox="0 0 28 13"><rect x=".5" y=".5" width="24" height="12" rx="3.8" fill="none" stroke="currentColor" opacity=".45"/><rect x="2" y="2" width="16" height="9" rx="2.4" fill="currentColor"/><rect x="25.6" y="4.3" width="1.6" height="4.4" rx=".8" fill="currentColor" opacity=".45"/></svg>
</div></div>`;
}

/** Accessible names for the nav bar buttons. */
const NAV_NAME: Record<string, string> = {
  back: "返回", close: "关闭", flatback: "返回", check: "保存", tick: "保存", save: "保存", plus: "添加", scan: "扫码",
  doc: "查看生成的配置", cloud: "下载",
};
/** The buttons that leave the screen walk the deck; the rest are the app's own actions and explain themselves. */
const LEAVES = new Set(["back", "close", "flatback"]);
/** A piece of the app's own chrome: it picks like a row (`@id`), it never opens anything. */
export function shellAttrs(id: string, name?: string) {
  return `data-shell="${esc(id)}" data-row="@${esc(id)}" data-key="@${esc(id)}"${name ? ` aria-label="${esc(name)}"` : ""}`;
}
function navbtn(client: string, kind: string, side: "left" | "right") {
  const act = LEAVES.has(kind) ? ` data-nav="${side}" aria-label="${NAV_NAME[kind]}"` : ` ${shellAttrs(`nav:${kind}`, NAV_NAME[kind])}`;
  // Clash Mi draws bare glyphs; Surge and Shadowrocket use round glass buttons.
  if (kind === "cloudplus") {
    return `<div class="navflat right cloud" ${shellAttrs("nav:cloud", NAV_NAME.cloud)}>${ICON.mcloud}</div>` +
      `<div class="navflat right" ${shellAttrs("nav:plus", NAV_NAME.plus)}>${ICON.mplus}</div>`;
  }
  if (kind === "save") return `<div class="navbtn text ${side}"${act}>保存</div>`;
  if (kind === "flatback" || kind === "doc" || client === "clash-mi") {
    return `<div class="navflat ${side}"${act}>${ICON[client === "clash-mi" && kind === "plus" ? "mplus" : kind] ?? ""}</div>`;
  }
  const cls = kind === "check" ? "navbtn primary" : "navbtn";
  return `<div class="${cls} ${side}"${act}>${ICON[kind] ?? ""}</div>`;
}

function clean(raw: RRow): RRow {
  return { ...raw, label: safe(raw.label) ?? "", sub: safe(raw.sub), detail: safe(raw.detail), field: safe(raw.field),
    subParts: raw.subParts?.map((p) => safe(p) ?? "") };
}

/** The attributes and classes every explained element carries. */
function hook(r: RRow, extra: string[] = [], named = false) {
  const at = [
    `data-key="${esc(r.key)}"`,
    `data-row="${esc(r.id)}"`,
    r.item != null ? `data-item="${r.item}"` : "",
    r.to ? `data-to="${esc(r.to)}"` : "",
    named ? `aria-label="${esc(r.label)}"` : "",
  ].filter(Boolean).join(" ");
  const cls = ["row", ...extra, r.state, r.paper ? "has-paper" : "", r.secret ? "secret" : ""].filter(Boolean).join(" ");
  return { at, cls };
}

function paperOf(r: RRow) {
  return r.paper ? `<i class="paper" role="note" aria-label="${esc(r.paper)}"></i>`
    : r.paperTrail ? `<i class="paper" role="note" aria-label="里面有一项要在手机上设置"></i>` : "";
}

function accessory(r: RRow, trail?: string) {
  if (trail === "chevron") return ICON.chevron;
  if (trail === "plus") return TRAIL_ICON.plus + ICON.chevron;
  if (trail) return TRAIL_ICON[trail] ?? "";
  if (r.acc === "switch") return `<span class="switch ${r.sw ?? "none"}"></span>`;
  if (r.acc === "chevron") return ICON.chevron;
  if (r.acc === "updown") return ICON.updown;
  if (r.acc === "caret") return ICON.caret;
  if (r.acc === "radio") return `<span class="radio"></span>`;
  return "";
}

function flagOf(label: string) {
  const m = label.match(FLAG_RE);
  return m ? `<span class="lead flag"><span>${m[0]}</span></span>` : `<span class="lead flag none">${LEAD_ICON.globe}</span>`;
}

/** A standard list row (any app); leading / trailing glyphs follow the real screen. */
function row(client: string, raw: RRow, extra: string[] = []) {
  const r = clean(raw);
  const k = `${client}:${r.id}`;
  const action = client === "surge" && r.ctl === "action";
  const solo = client === "surge" && r.solo;
  const lead = FLAG_ROWS.has(k) ? flagOf(r.label)
    : LEAD[k] ? `<span class="lead">${LEAD_ICON[LEAD[k]] ?? ""}</span>`
    : MINUS_ROWS.has(k) && r.item != null ? `<span class="lead sign minus">${ICON.minusc}</span>`
    : action ? `<span class="lead sign plus">${ICON.plusc}</span>` : "";
  const badge = BADGE[k] && r.subParts?.length ? r.subParts : null;
  const { at, cls } = hook(r, [...extra, r.sub || badge ? "has-sub" : "", lead ? "has-lead" : "", action ? "action" : "",
    solo ? "solo" : "", badge ? "has-badge" : ""].filter(Boolean));
  if (solo) {
    // A bare text field: the value sits where the placeholder was.
    const v = r.field ?? r.detail;
    return `<div class="${cls}" ${at}><span class="label${v ? "" : " ph"}">${esc(v ?? r.placeholder ?? r.label)}</span>${paperOf(r)}</div>`;
  }
  let right = "";
  if (r.field != null) right += `<span class="field">${esc(r.field)}</span>`;
  if (r.detail != null && !NO_DETAIL.has(k)) right += `<span class="detail">${esc(r.detail)}</span>`;
  right += r.ctl === "segmented" && r.state === "lit" ? ICON.rowcheck : accessory(r, TRAIL[k]);
  const info = r.info ? ICON.info : "";
  let sub = r.sub ? `<span class="sub">${esc(r.sub)}</span>` : "";
  if (badge) {
    const [kind, ...rest] = badge;
    const name = k === "surge:home-proxies#0.0" ? PROTO[kind.toLowerCase()] ?? kind : kind;
    sub = `<span class="sub badged"><i class="badge" style="--badge:${BADGE[k]}">${esc(name)}</i>${rest.length ? `<span>${esc(rest.join(" "))}</span>` : ""}</span>`;
  }
  return `<div class="${cls}" ${at}>${lead}${info}<span class="label${r.ph ? " ph" : ""}">${esc(r.label)}${sub}</span>${right}${paperOf(r)}</div>`;
}

function listBody(map: ClientMap, s: RScreen, seg: string) {
  const tools = map.client === "shadowrocket" && s.id === "tab-home";
  return seg + s.groups.map((grp, gi) => {
    const lead = tools && gi === 1 ? `<div class="srtools">${SR_TOOLS.map((t) => `<span class="srtool" ${shellAttrs(`tool:${t.id}`, t.name)}>${t.svg}</span>`).join("")}</div>` : "";
    return `<section class="gblock${lead ? " has-tools" : ""}">${lead}${grp.header ? `<div class="gheader">${esc(grp.header)}</div>` : ""}` +
      (grp.rows.length ? `<div class="group">${grp.rows.map((r) => row(map.client, r)).join("")}</div>` : "") +
      `${grp.footer ? `<div class="gfooter">${esc(grp.footer)}</div>` : ""}</section>`;
  }).join("");
}

/* ---------- Surge home: one card per feature ---------- */

function surgeCard(grp: RGroup) {
  const look = SURGE_CARD[grp.header ?? ""] ?? { c: "#111", i: "" };
  const rows = grp.rows.map(clean);
  // The feature switch sits in the card's title bar; the title itself is that row.
  const head = rows[0]?.ctl === "toggle" && rows[0].label === grp.header ? rows.shift()! : null;
  const checks = rows.filter((r) => r.ctl === "segmented");
  const chips = rows.filter((r) => r.ctl === "button" || r.ctl === "menu");
  const links = rows.filter((r) => r.ctl === "link");
  const rest = rows.filter((r) => !checks.includes(r) && !chips.includes(r) && !links.includes(r));
  const title = `<span class="sicon">${SURGE_ICON[look.i] ?? ""}</span><span class="stitle">${esc(grp.header ?? "")}</span>`;
  let html = "";
  if (grp.header || head) {
    if (head) {
      const { at, cls } = hook(head, ["shead"]);
      html += `<div class="${cls}" ${at}>${title}<span class="switch ${head.sw ?? "none"}"></span>${paperOf(head)}</div>`;
    } else {
      html += `<div class="shead plain">${title}</div>`;
    }
  }
  // Stopgap kept on purpose: one card tightens its tracking (others use the CSS -.25px) so its line breaks where the phone's does.
  if (grp.footer) html += `<p class="sdesc"${look.ls ? ` style="letter-spacing:${look.ls}"` : ""}>${esc(grp.footer)}</p>`;
  if (checks.length) {
    html += `<div class="schecks">${checks.map((r) => {
      const { at, cls } = hook(r, ["scheck"]);
      return `<div class="${cls}" ${at}><span class="smark">${SURGE_ICON.check}</span><span class="label">${esc(r.label)}</span>${paperOf(r)}</div>`;
    }).join("")}</div>`;
  }
  if (rest.length) html += `<div class="group">${rest.map((r) => row("surge", r)).join("")}</div>`;
  if (chips.length) {
    html += `<div class="schips">${chips.map((r) => {
      const { at, cls } = hook(r, ["schip"]);
      return `<div class="${cls}" ${at}><span class="label">${esc(r.label)}</span>${paperOf(r)}</div>`;
    }).join("")}</div>`;
  }
  const card = html ? `<section class="scard" style="--card-c:${look.c}">${html}</section>` : "";
  const link = links.map((r) => {
    const { at, cls } = hook(r, ["slink"]);
    return `<div class="${cls}" ${at}><span class="label">${esc(r.label)}</span>${ICON.chevron}${paperOf(r)}</div>`;
  }).join("");
  return card + link;
}

function surgeHome(s: RScreen, chrome: ScreenChrome) {
  const tabs = (chrome.segments ?? []).map((x) =>
    `<span class="stab${x.on ? " on" : ""}" data-root="${esc(x.id)}"${x.on ? ' aria-current="page"' : ""}>${esc(x.label)}</span>`).join("");
  const head = `<div class="navbar shome"><div class="sname" ${shellAttrs("profile", `切换配置：${s.title}`)}><span class="slogo">${SURGE_ICON.logo}</span>` +
    `<span class="sprofile">${esc(s.title)}</span><span class="sdown">${SURGE_ICON.down}</span></div>` +
    `<div class="sstart" ${shellAttrs("start", "启动")}>启动</div><div class="stabs">${tabs}</div></div>`;
  const bar = `<div class="sbar"><div class="sbtab on" ${shellAttrs("bar:home", "首页")}>${SURGE_ICON.tabhome}<span>首页</span></div>` +
    `<div class="sbtab" ${shellAttrs("bar:tools", "工具")}>${SURGE_ICON.tabtools}<span>工具</span></div>` +
    `<div class="sbtab" ${shellAttrs("bar:more", "更多")}>${SURGE_ICON.tabmore}<span>更多</span></div></div>`;
  return { head, body: s.groups.map(surgeCard).join(""), bar };
}

/* ---------- Clash Mi home: connection card + settings card ---------- */

function clashHome(s: RScreen) {
  return s.groups.map((grp) => `<section class="cmcard">${grp.rows.map((raw) => {
    const r = clean(raw);
    const k = `clash-mi:${r.id}`;
    if (r.ctl === "toggle") {
      const { at, cls } = hook(r, ["cmconn"]);
      return `<div class="${cls}" ${at}><i class="cmdot"></i><span class="label">${esc(r.label)}</span><span class="switch ${r.sw ?? "none"}"></span>${paperOf(r)}</div>`;
    }
    if (r.ctl === "segmented" && OPTIONS[k]) {
      const { at, cls } = hook(r, ["cmseg"], true);
      return `<div class="${cls}" ${at}><div class="cmtrack">${OPTIONS[k].map((o) => `<span>${esc(o)}</span>`).join("")}</div>${paperOf(r)}</div>`;
    }
    return row("clash-mi", r, ["cmrow", LEAD[k] ? "" : "cmplain"]);
  }).join("")}</section>`).join("");
}

/* ---------- screen ---------- */

export function renderPhoneScreen(root: HTMLElement, map: ClientMap, s: RScreen, chrome: ScreenChrome = {}) {
  const g = map.geometry;
  const sheet = !!(s.def.sheet && g.sheet);
  const layout = map.client === "surge" && s.def.segment ? "surge-home"
    : map.client === "clash-mi" && s.id === map.root ? "clash-home" : "list";
  root.className = `ios-screen theme-${map.theme}${sheet ? " is-sheet" : ""}${layout !== "list" ? ` ${layout}` : ""}`;
  root.style.cssText = [
    `--content-top:${sheet ? g.content_top - 20 : g.content_top}px`,
    `--row-h:${g.row_h}px`,
    `--group-gap:${g.group_gap}px`,
    `--nav-cy:${g.nav_cy}px`,
    g.group_margin != null ? `--group-margin:${g.group_margin}px` : "",
  ].filter(Boolean).join(";");

  let html = "";
  if (layout === "surge-home") {
    const { head, body, bar } = surgeHome(s, chrome);
    html = `<div class="scroll"><div class="content">${body}</div></div>${head}${bar}`;
  } else {
    const seg = chrome.segments?.length
      ? `<div class="segbar">${chrome.segments.map((x) => `<span class="seg${x.on ? " on" : ""}" data-root="${esc(x.id)}">${esc(x.label)}</span>`).join("")}</div>`
      : "";
    const body = layout === "clash-home" ? clashHome(s) : listBody(map, s, seg);
    const nav = `<div class="navbar">${s.def.nav.left ? navbtn(map.client, s.def.nav.left, "left") : ""}<div class="navtitle">${esc(s.title)}</div>${s.def.nav.right ? navbtn(map.client, s.def.nav.right, "right") : ""}</div>`;
    const scroll = `<div class="scroll"><div class="content">${body}</div></div>`;
    html = sheet
      ? `<div class="dim"></div><div class="sheet" style="top:${g.sheet!.top}px;border-radius:${g.sheet!.radius}px ${g.sheet!.radius}px 0 0">${scroll}${nav}</div>`
      : scroll + nav;
  }
  html += statusbar();
  if (chrome.tabs?.length && g.tabbar) {
    const t = g.tabbar;
    html += `<div class="tabbar" style="left:${t.x[0]}px;width:${t.x[1] - t.x[0]}px">${chrome.tabs.map((it) =>
      `<div class="tab${it.on ? " on" : ""}" ${it.root ? `data-root="${esc(it.root)}"${it.on ? ' aria-current="page"' : ""}` : shellAttrs(`tab:${it.icon}`)}>${ICON[it.icon] ?? ""}<span>${esc(it.label)}</span></div>`).join("")}</div>`;
  }
  root.innerHTML = html;
}

/** Chrome (segments / tabs) for a root screen. */
export function chromeFor(map: ClientMap, screenId: string): ScreenChrome {
  const def = map.screens[screenId];
  const out: ScreenChrome = {};
  if (def.segment) {
    out.segments = map.roots.filter((id) => map.screens[id]?.segment).map((id) => {
      const via = map.screens[id].via ?? "";
      return { id, label: via.startsWith("segment:") ? via.slice(8) : "通用", on: id === screenId };
    });
  }
  if (map.tabs && def.tab != null) {
    out.tabs = map.tabs.map((t, i) => ({
      ...t, on: i === def.tab, root: map.roots.find((id) => map.screens[id]?.tab === i),
    }));
  }
  return out;
}
