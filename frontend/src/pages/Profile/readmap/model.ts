/* Resolves the generated phone tree (data/<client>.json) against one rendered config.
   Every value shown on the phone comes from the config text; rows SubHub does not write stay empty. */
import {
  asSwitch,
  type Block,
  type ParsedConfig,
  iniValue,
  splitCols,
  yamlValue,
} from "./parse";
import { MASK } from "./mask";

/* ---------- generated data ---------- */

export interface Bind {
  kind: "value" | "count" | "exists" | "list" | "item";
  ini?: string | string[];
  key?: string | string[];
  yaml?: string;
  match?: string;
  re?: string;
  split?: string;
  map?: Record<string, string>;
  mask?: boolean;
  sep?: string;
  col?: number | number[];
  label_col?: number | number[];
  sub_col?: number | number[];
  value_col?: number | number[];
  max_cols?: number;
  param?: string;
  sub_param?: string;
  unquote?: boolean;
  line?: "kv-list";
  part?: "name";
  pos?: number;
  pos_from?: number;
  repeat?: boolean;
  label_part?: "name";
  sub_pos?: number[];
}

export interface RowDef {
  id: string;
  label: string;
  ctl: string;
  rel: string;
  to?: string;
  acc?: string;
  info?: boolean;
  ph?: boolean;
  empty_only?: boolean;
  bind?: Bind;
  explain?: string;
  /** What the control does on the phone (rows SubHub does not write). */
  about?: string;
  /** Where the setting lives: p = the config file, a = the app on the phone, x = an action. */
  layer?: "p" | "a" | "x";
  paper?: string;
  override?: boolean;
  fixed?: string;
  /** A bare text field (no label beside it): the value takes the placeholder's place. */
  solo?: boolean;
  placeholder?: string;
}
export interface GroupDef {
  header?: string;
  footer?: string;
  rows: RowDef[];
}
export interface ScreenDef {
  id: string;
  title: string;
  parent: string | null;
  via: string | null;
  kind?: string;
  sheet: boolean;
  nav: { left?: string | null; right?: string | null };
  groups: GroupDef[];
  deferred?: boolean;
  tab?: number;
  segment?: boolean;
  /** What each piece of the app's own chrome on this screen does (`start`, `nav:plus`, `tab:gear` …). */
  shell?: Record<string, string>;
}
export interface ClientMap {
  client: "shadowrocket" | "surge" | "clash-mi";
  target: "shadowrocket" | "surge" | "clash";
  format: "ini" | "yaml";
  theme: string;
  root: string;
  roots: string[];
  geometry: {
    content_top: number;
    row_h: number;
    row_h_sub?: number;
    group_gap: number;
    nav_cy: number;
    group_margin?: number;
    sheet?: { top: number; radius: number };
    tabbar?: { x: [number, number] };
  };
  tabs?: { icon: string; label: string }[] | null;
  screens: Record<string, ScreenDef>;
}

/* ---------- resolved view ---------- */

export type RowState = "lit" | "trail" | "glass";
export interface RRow {
  key: string;            // unique per rendered row: `${id}` or `${id}@${item}`
  id: string;             // data row id
  item?: number;          // list index for template rows
  label: string;
  /** The phone control this row is drawn as (toggle, segmented, button, link, …). */
  ctl?: string;
  sub?: string;
  detail?: string;
  field?: string;
  sw?: "on" | "off" | "none";
  acc?: string;
  to?: string;
  info?: boolean;
  ph?: boolean;
  state: RowState;
  paper?: string;
  paperTrail?: boolean;   // a held paper row lives somewhere under this nav row
  lines: number[];
  secret?: boolean;
  solo?: boolean;
  placeholder?: string;
  /** The subtitle's parts, before they are joined (Surge draws the first one as a badge). */
  subParts?: string[];
}
export interface RGroup {
  header?: string;
  footer?: string;
  rows: RRow[];
}
export interface RScreen {
  id: string;
  title: string;
  def: ScreenDef;
  groups: RGroup[];
}
export interface Target {
  screen: string;
  row: string;
  item?: number;
}
export interface SectionView {
  block: Block;
  label: string;           // phone label or raw name
  phone: boolean;          // label came from the phone
  count: number | null;
  landing?: string;        // screen the section opens on (one-to-one sections only)
  paper?: string;
}

const LIST_WINDOW = 50;

interface Item {
  line: number;
  name?: string;
  pos: string[];
  params: Map<string, string>;
  cols: string[];
}

export class ReadMap {
  readonly map: ClientMap;
  readonly doc: ParsedConfig;
  private lineTargets = new Map<number, Target>();
  private lit = new Map<string, boolean>();
  readonly sections: SectionView[];
  /** Paper rows that hold (row id → text) and the sections their condition reads. */
  readonly papers: { screen: string; row: string; text: string; keys: string[]; lines: number[] }[] = [];

  /** The name the phone gives this config: the managed URL's file name, as the app saves it on download. */
  readonly file: string;

  constructor(map: ClientMap, doc: ParsedConfig) {
    this.map = map;
    this.doc = doc;
    const managed = doc.lines.slice(0, 5).map((l) => /^#!MANAGED-CONFIG\s+(\S+)/.exec(l)?.[1]).find(Boolean);
    let file = "";
    try { file = managed ? decodeURIComponent(new URL(managed).pathname.split("/").pop() ?? "") : ""; } catch { /* keep fallback */ }
    this.file = file || `SubHub.${doc.format === "yaml" ? "yaml" : "conf"}`;
    this.indexLines();
    this.sections = this.buildSections();
  }

  /* ----- binds ----- */

  private secKeys(b: Bind): string[] {
    if (b.yaml) return [b.yaml.split(".")[0]];
    return b.ini == null ? [] : Array.isArray(b.ini) ? b.ini : [b.ini];
  }

  private value(b: Bind): { value: string; line: number } | null {
    let hit: { value: string; line: number } | null = null;
    if (b.yaml) hit = yamlValue(this.doc, b.yaml);
    else {
      const keys = b.key == null ? [] : Array.isArray(b.key) ? b.key : [b.key];
      for (const s of this.secKeys(b)) {
        for (const k of keys) {
          hit = iniValue(this.doc, s, k);
          if (hit) break;
        }
        if (hit) break;
      }
    }
    if (!hit) return null;
    if (b.re) {
      const m = new RegExp(b.re).exec(hit.value);
      if (!m) return null;
      hit = { value: m[1] ?? m[0], line: hit.line };
    }
    return hit;
  }

  private exists(b: Bind): number[] | null {
    if (b.yaml) {
      const v = yamlValue(this.doc, b.yaml);
      return v ? [v.line] : null;
    }
    if (b.key != null) {
      const v = this.value(b);
      return v ? [v.line] : null;
    }
    const lines = this.secKeys(b)
      .map((k) => this.doc.byKey.get(k))
      .filter((x): x is Block => !!x)
      .filter((blk) => !b.match || blk.items.some((i) => new RegExp(b.match!).test(this.doc.lines[i])))
      .map((blk) => blk.header);
    return lines.length ? lines : null;
  }

  private items(b: Bind): Item[] {
    if (b.split && b.key != null) {
      const v = this.value(b);
      if (!v) return [];
      return v.value.split(b.split).map((p) => p.trim()).filter(Boolean)
        .map((p) => ({ line: v.line, pos: [p], params: new Map(), cols: [p] }));
    }
    if (b.yaml) {
      const blk = this.doc.byKey.get(b.yaml.split(".")[0]);
      if (!blk) return [];
      return blk.items.map((line) => {
        const head = this.doc.lines[line].replace(/^\s*-\s*/, "").trim();
        const cols = b.sep ? head.split(b.sep).map((c) => c.trim()) : [head];
        return { line, pos: cols, params: new Map(), cols };
      });
    }
    const re = b.match ? new RegExp(b.match) : null;
    const out: Item[] = [];
    for (const k of this.secKeys(b)) {
      const blk = this.doc.byKey.get(k);
      if (!blk) continue;
      for (const line of blk.items) {
        const raw = this.doc.lines[line];
        if (re && !re.test(raw)) continue;
        out.push(b.line === "kv-list" ? kvList(raw, line) : sepItem(raw, line, b));
      }
    }
    return out;
  }

  private pick(it: Item, b: Bind, which: "label" | "sub" | "value"): string | undefined {
    if (which === "label") {
      if (b.label_part === "name") return it.name;
      if (b.label_col != null) return cols(it.cols, b.label_col);
      return it.name ?? it.cols[0];
    }
    if (which === "sub") {
      if (b.sub_pos) return b.sub_pos.map((i) => it.pos[i]).filter(Boolean).join(" | ") || undefined;
      if (b.sub_param) return it.params.get(b.sub_param);
      if (b.sub_col != null) return cols(it.cols, b.sub_col);
      return undefined;
    }
    if (b.part === "name") return it.name;
    if (b.param) return it.params.get(b.param.toLowerCase()) ?? undefined;
    if (b.pos != null) return it.pos[b.pos];
    if (b.col != null) return cols(it.cols, b.col);
    if (b.value_col != null) return cols(it.cols, b.value_col);
    return undefined;
  }

  private subParts(it: Item, b: Bind): string[] | undefined {
    const parts = b.sub_pos ? b.sub_pos.map((i) => it.pos[i])
      : Array.isArray(b.sub_col) ? b.sub_col.map((i) => it.cols[i]) : undefined;
    const out = parts?.filter((x): x is string => !!x);
    return out?.length ? out : undefined;
  }

  /* ----- screens ----- */

  /** Item list feeding a detail screen: the bind of the row it was entered through. */
  private sourceList(screenId: string): { bind: Bind; items: Item[] } | null {
    const def = this.map.screens[screenId];
    if (!def?.via || !def.parent) return null;
    const parent = this.map.screens[def.parent];
    const row = parent?.groups.flatMap((g) => g.rows).find((r) => r.id === def.via);
    if (!row?.bind || row.bind.kind !== "list") return null;
    return { bind: row.bind, items: this.items(row.bind) };
  }

  screen(id: string, items: Record<string, number> = {}, around?: number): RScreen {
    const def = this.map.screens[id];
    const parentItem = def.parent != null ? items[def.parent] : undefined;
    const src = this.sourceList(id);
    const current = src && parentItem != null ? src.items[parentItem] : undefined;
    const groups: RGroup[] = [];
    for (const g of def.groups) {
      const rows: RRow[] = [];
      let listed = false;
      for (const r of g.rows) {
        if (r.bind?.kind === "list") {
          const all = this.items(r.bind);
          listed = all.length > 0;
          const center = around ?? items[id] ?? 0;
          const from = Math.max(0, Math.min(center - LIST_WINDOW, all.length - LIST_WINDOW * 2));
          all.slice(from, from + LIST_WINDOW * 2).forEach((it, k) => {
            const idx = from + k;
            const secret = !!r.bind!.mask;
            rows.push({
              key: `${r.id}@${idx}`, id: r.id, item: idx, ctl: r.ctl,
              label: this.pick(it, r.bind!, "label") ?? "",
              sub: this.pick(it, r.bind!, "sub"),
              subParts: this.subParts(it, r.bind!),
              detail: r.bind!.value_col != null ? cols(it.cols, r.bind!.value_col) : undefined,
              acc: r.acc, to: r.to, state: "lit", lines: [it.line], secret,
            });
          });
          continue;
        }
        if (r.empty_only) {
          if (!listed && !g.rows.some((x) => x.bind?.kind === "list" && this.items(x.bind).length)) rows.push(this.glass(r));
          continue;
        }
        if (r.bind?.kind === "item" && r.bind.repeat && current && src) {
          const vals = current.pos.slice(r.bind.pos_from ?? 0);
          vals.forEach((v, k) => rows.push({
            key: `${r.id}@${k}`, id: r.id, label: v, ctl: r.ctl, acc: r.acc, state: "lit", lines: [current.line],
          }));
          if (!vals.length) rows.push(this.glass(r));
          continue;
        }
        rows.push(this.row(id, r, current));
      }
      if (rows.length || g.header) groups.push({ header: g.header, footer: g.footer, rows });
    }
    for (const g of groups) for (const r of g.rows) r.label = this.fill(r.label);
    return { id, title: this.fill(def.title), def, groups };
  }

  /** `{file}` / `{name}` placeholders → this config's own file name. */
  fill(s: string): string {
    if (!s.includes("{")) return s;
    return s.replace(/\{file\}/g, this.file).replace(/\{name\}/g, this.file.replace(/\.[^.]+$/, ""));
  }

  private glass(r: RowDef, extra: Partial<RRow> = {}): RRow {
    const sw = r.acc === "switch" ? "none" : undefined;
    return { key: r.id, id: r.id, label: r.label, ctl: r.ctl, acc: r.acc, to: r.to, info: r.info, ph: r.ph, sw,
      solo: r.solo, placeholder: r.placeholder,
      state: r.to && this.subtreeLit(r.to) ? "trail" : "glass", lines: [],
      paperTrail: r.to ? this.papers.some((p) => this.under(p.screen, r.to!)) : undefined, ...extra };
  }

  /** True when `screen` is `top` or sits below it. */
  private under(screen: string, top: string): boolean {
    for (let cur: string | null | undefined = screen, n = 0; cur && n < 12; cur = this.map.screens[cur]?.parent, n++) {
      if (cur === top) return true;
    }
    return false;
  }

  private row(screenId: string, r: RowDef, current?: Item): RRow {
    const b = r.bind;
    if (!b) return this.glass(r);
    const written = r.rel === "w" || r.rel === "p";
    if (b.kind === "exists") {
      const lines = this.exists(b);
      if (r.paper) return this.glass(r, lines ? { paper: r.paper, lines } : {});
      if (r.override) return this.glass(r, lines ? { lines } : {});
      if (!lines || !written) return this.glass(r);
      return { ...this.glass(r), state: "lit", lines, detail: r.fixed };
    }
    if (b.kind === "count") {
      const n = this.count(b);
      if (!n) return this.glass(r);
      return { ...this.glass(r), state: written ? "lit" : this.glass(r).state, detail: String(n.n), lines: n.lines };
    }
    let val: { value: string; line: number } | null = null;
    if (b.kind === "item") {
      if (!current) return this.glass(r);
      const v = this.pick(current, b, "value");
      val = v == null ? null : { value: v, line: current.line };
    } else {
      val = this.value(b);
    }
    if (!val) return this.glass(r);
    if (r.override || !written) return this.glass(r, { lines: [val.line] });
    let shown = b.map?.[val.value] ?? b.map?.[val.value.toLowerCase()] ?? val.value;
    if (b.unquote) shown = shown.replace(/^(['"])(.*)\1$/, "$2");
    const out: RRow = { ...this.glass(r), state: "lit", lines: [val.line] };
    if (r.acc === "switch") out.sw = asSwitch(val.value) ? "on" : asSwitch(val.value) === false ? "off" : "none";
    else if (r.ctl === "textfield") out.field = b.mask ? MASK : shown;
    else out.detail = b.mask ? MASK : shown;
    if (b.mask) out.secret = true;
    void screenId;
    return out;
  }

  private count(b: Bind): { n: number; lines: number[] } | null {
    if (b.split && b.key != null) {
      const v = this.value(b);
      if (!v) return null;
      const n = v.value.split(b.split).map((s) => s.trim()).filter(Boolean).length;
      return n ? { n, lines: [v.line] } : null;
    }
    if (b.yaml) {
      const [top, child] = splitPath(b.yaml);
      const blk = this.doc.byKey.get(top);
      if (!blk) return null;
      if (!child) return blk.items.length ? { n: blk.items.length, lines: [blk.header] } : null;
      const c = yamlValue(this.doc, b.yaml);
      if (!c) return null;
      const inline = c.value.match(/^\[(.*)\]$/);
      if (inline) {
        const n = inline[1].split(",").map((s) => s.trim()).filter(Boolean).length;
        return n ? { n, lines: [c.line] } : null;
      }
      let n = 0;
      for (let i = c.line + 1; i < blk.end; i++) {
        const l = this.doc.lines[i];
        if (/^ {4,}-\s/.test(l) || /^ {2}-\s/.test(l)) n++;
        else if (/^ {0,2}\S/.test(l)) break;
      }
      return n ? { n, lines: [c.line] } : null;
    }
    const blocks = this.secKeys(b).map((k) => this.doc.byKey.get(k)).filter((x): x is Block => !!x);
    const re = b.match ? new RegExp(b.match) : null;
    const n = blocks.reduce((s, blk) => s + blk.items.filter((i) => !re || re.test(this.doc.lines[i])).length, 0);
    return n ? { n, lines: blocks.map((blk) => blk.header) } : null;
  }

  /** A navigation row glows weakly when anything under it is written and present. */
  private subtreeLit(id: string, seen = new Set<string>()): boolean {
    if (this.lit.has(id)) return this.lit.get(id)!;
    if (seen.has(id)) return false;
    seen.add(id);
    const def = this.map.screens[id];
    let on = false;
    for (const r of def?.groups.flatMap((g) => g.rows) ?? []) {
      const b = r.bind;
      if (b && (r.rel === "w" || r.rel === "p") && !r.override) {
        if (b.kind === "list" && this.items(b).length) on = true;
        else if (b.kind === "count" && this.count(b)) on = true;
        else if (b.kind === "value" && this.value(b)) on = true;
        else if (b.kind === "exists" && !r.paper && this.exists(b)) on = true;
      }
      if (!on && r.to && this.subtreeLit(r.to, seen)) on = true;
      if (on) break;
    }
    this.lit.set(id, on);
    return on;
  }

  /* ----- lines ↔ rows ----- */

  private indexLines() {
    const claim = (line: number, t: Target) => {
      if (!this.lineTargets.has(line)) this.lineTargets.set(line, t);
    };
    for (const def of Object.values(this.map.screens)) {
      for (const r of def.groups.flatMap((g) => g.rows)) {
        const b = r.bind;
        if (!b) continue;
        if (r.paper) {
          const lines = this.exists(b);
          if (lines) this.papers.push({ screen: def.id, row: r.id, text: r.paper, keys: this.secKeys(b), lines });
          continue;
        }
        if (b.kind === "list") this.items(b).forEach((it, k) => claim(it.line, { screen: def.id, row: r.id, item: k }));
        else if (b.kind === "value") {
          const v = this.value(b);
          if (v) claim(v.line, { screen: def.id, row: r.id });
        }
      }
    }
  }

  target(line: number): Target | null {
    return this.lineTargets.get(line) ?? null;
  }

  /** Root first. */
  path(screen: string): string[] {
    const out: string[] = [];
    let cur: string | null = screen;
    while (cur) {
      out.unshift(cur);
      cur = this.map.screens[cur]?.parent ?? null;
    }
    return out;
  }

  rowDef(screen: string, row: string): RowDef | undefined {
    return this.map.screens[screen]?.groups.flatMap((g) => g.rows).find((r) => r.id === row);
  }

  /** Papers whose condition reads one of these sections (shown under a written row's explain). */
  papersFor(keys: string[]) {
    return this.papers.filter((p) => p.keys.some((k) => keys.includes(k)));
  }

  sectionKeys(screen: string, row: string): string[] {
    const r = this.rowDef(screen, row);
    return r?.bind ? this.secKeys(r.bind) : [];
  }

  /* ----- reading column ----- */

  private buildSections(): SectionView[] {
    const landing = new Map<string, Set<string>>();
    const counts = new Map<string, { label: string; n: number }>();
    for (const def of Object.values(this.map.screens)) {
      for (const r of def.groups.flatMap((g) => g.rows)) {
        const b = r.bind;
        if (!b || r.paper) continue;
        for (const k of this.secKeys(b)) {
          if (b.kind === "value" || b.kind === "list") {
            if (!landing.has(k)) landing.set(k, new Set());
            landing.get(k)!.add(def.id);
          }
          if (b.kind === "count" && r.to && !counts.has(k)) {
            const n = this.count(b);
            if (n) counts.set(k, { label: r.label, n: n.n });
          }
        }
      }
    }
    return this.doc.blocks.map((block) => {
      if (block.line) return { block, label: this.doc.lines[block.header], phone: false, count: null };
      const raw = this.doc.format === "ini" && block.key ? `[${block.key}]` : block.key;
      const items = block.items.length;
      const land = landing.get(block.key);
      const only = land && land.size === 1 ? [...land][0] : undefined;
      const paper = this.papers.find((p) => p.keys.includes(block.key))?.text;
      if (only && !this.map.roots.includes(only)) {
        const def = this.map.screens[only];
        const via = def.parent ? this.rowDef(def.parent, def.via ?? "") : undefined;
        const c = counts.get(block.key);
        return { block, label: this.fill(via?.label || def.title), phone: true, count: c ? c.n : items, landing: only, paper };
      }
      return { block, label: raw, phone: false, count: block.line ? null : items, paper };
    });
  }
}

/* ---------- line syntaxes ---------- */

function kvList(raw: string, line: number): Item {
  const eq = raw.indexOf("=");
  const name = eq < 0 ? raw.trim() : raw.slice(0, eq).trim();
  const rest = eq < 0 ? "" : raw.slice(eq + 1);
  const fields = splitTopLevel(rest);
  const pos: string[] = [];
  const params = new Map<string, string>();
  for (const f of fields) {
    const e = f.indexOf("=");
    if (e > 0 && !/^["']/.test(f)) params.set(f.slice(0, e).trim().toLowerCase(), f.slice(e + 1).trim());
    else pos.push(f);
  }
  return { line, name, pos, params, cols: [name, ...fields] };
}

/** Comma split that keeps quoted and parenthesised runs together. */
function splitTopLevel(s: string): string[] {
  const out: string[] = [];
  let cur = "", q = "", depth = 0;
  for (const ch of s) {
    if (q) { cur += ch; if (ch === q) q = ""; continue; }
    if (ch === '"' || ch === "'") { q = ch; cur += ch; continue; }
    if (ch === "(" || ch === "[" || ch === "{") depth++;
    if (ch === ")" || ch === "]" || ch === "}") depth = Math.max(0, depth - 1);
    if (ch === "," && depth === 0) { out.push(cur.trim()); cur = ""; continue; }
    cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

function sepItem(raw: string, line: number, b: Bind): Item {
  let c = b.sep === "=" ? (() => { const e = raw.indexOf("="); return e < 0 ? [raw.trim()] : [raw.slice(0, e).trim(), raw.slice(e + 1).trim()]; })()
    : splitCols(raw, b.sep ?? ",");
  if (b.max_cols && c.length > b.max_cols) {
    const sepStr = b.sep === " " ? " " : b.sep ?? ",";
    c = [...c.slice(0, b.max_cols - 1), c.slice(b.max_cols - 1).join(sepStr)];
  }
  if (b.unquote) c = c.map((x) => x.replace(/^(['"])(.*)\1$/, "$2"));
  const params = new Map<string, string>();
  for (const x of c) {
    const e = x.indexOf("=");
    if (e > 0) params.set(x.slice(0, e).trim().toLowerCase(), x.slice(e + 1).trim());
  }
  return { line, pos: c, params, cols: c };
}

function cols(c: string[], at: number | number[]): string | undefined {
  const idx = Array.isArray(at) ? at : [at];
  const v = idx.map((i) => c[i]).filter((x) => x != null && x !== "");
  return v.length ? v.join(" ") : undefined;
}

const splitPath = (p: string): [string, string | undefined] => {
  const dot = p.indexOf(".");
  return dot < 0 ? [p, undefined] : [p.slice(0, dot), p.slice(dot + 1)];
};
