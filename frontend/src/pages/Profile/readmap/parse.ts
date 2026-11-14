/* Read-only indexes over a rendered client config (render-preview `content`).
   INI (Surge / Shadowrocket): whole-line `[Section]` headers only — node names such as
   `[山海] 香港01 = …` are body lines, not sections.
   YAML (Mihomo): a two-level key scan by indentation, no YAML library. */

export type ConfigFormat = "ini" | "yaml";

export interface Block {
  /** Section name (`General`) or top-level YAML key (`dns`). Empty for a preamble line. */
  key: string;
  /** Line index of the header line. */
  header: number;
  /** Body line range [start, end). Empty for one-line blocks. */
  start: number;
  end: number;
  /** Meaningful body lines: INI non-comment lines, YAML list-item starts (or child keys). */
  items: number[];
  /** True for a one-line block (YAML scalar, INI preamble line). */
  line: boolean;
}

export interface ParsedConfig {
  format: ConfigFormat;
  lines: string[];
  blocks: Block[];
  byKey: Map<string, Block>;
}

const INI_HEADER = /^\[([^\]\r\n]+)\]\s*$/;
const INI_COMMENT = /^\s*(#|;|\/\/)/;
const YAML_TOP = /^([^\s#-][^:]*?):(?:\s+(.*))?$/;
const YAML_CHILD = /^ {2}([^\s#-][^:]*?):(?:\s+(.*))?$/;
const YAML_ITEM = /^(\s*)-(\s|$)/;

export function parseConfig(text: string, format: ConfigFormat): ParsedConfig {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  const blocks = format === "ini" ? iniBlocks(lines) : yamlBlocks(lines);
  const byKey = new Map<string, Block>();
  for (const b of blocks) if (b.key && !byKey.has(b.key)) byKey.set(b.key, b);
  return { format, lines, blocks, byKey };
}

function iniBlocks(lines: string[]): Block[] {
  const out: Block[] = [];
  let cur: Block | null = null;
  lines.forEach((raw, i) => {
    const m = INI_HEADER.exec(raw);
    if (m) {
      if (cur) cur.end = i;
      cur = { key: m[1].trim(), header: i, start: i + 1, end: lines.length, items: [], line: false };
      out.push(cur);
      return;
    }
    if (!cur) {
      if (raw.trim()) out.push({ key: "", header: i, start: i + 1, end: i + 1, items: [], line: true });
      return;
    }
    if (raw.trim() && !INI_COMMENT.test(raw)) cur.items.push(i);
  });
  return out;
}

function yamlBlocks(lines: string[]): Block[] {
  const out: Block[] = [];
  let cur: Block | null = null;
  let itemIndent = -1;
  lines.forEach((raw, i) => {
    if (!raw.trim() || /^\s*#/.test(raw)) return;
    const top = /^\S/.test(raw) && !raw.startsWith("-") ? YAML_TOP.exec(raw) : null;
    if (top) {
      if (cur) cur.end = i;
      const inline = (top[2] ?? "").trim();
      const scalar = inline !== "" && !/^[|>]/.test(inline);
      cur = { key: unquote(top[1]), header: i, start: i + 1, end: scalar ? i + 1 : lines.length, items: [], line: scalar };
      out.push(cur);
      itemIndent = -1;
      if (scalar) cur = null;
      return;
    }
    if (!cur) return;
    const it = YAML_ITEM.exec(raw);
    if (it) {
      const ind = it[1].length;
      if (itemIndent < 0) itemIndent = ind;
      if (ind === itemIndent) cur.items.push(i);
      return;
    }
    if (itemIndent < 0 && YAML_CHILD.test(raw)) cur.items.push(i);
  });
  return out;
}

const unquote = (s: string) => s.trim().replace(/^(['"])(.*)\1$/, "$2");

/* ---------- lookups used by binds ---------- */

export interface ConfigItem {
  line: number;
  end: number;
  cols: string[];
}

/** INI `key = value` inside a section. */
export function iniValue(doc: ParsedConfig, section: string, key: string): { value: string; line: number } | null {
  const b = doc.byKey.get(section);
  if (!b) return null;
  const want = key.toLowerCase();
  for (const i of b.items) {
    const eq = doc.lines[i].indexOf("=");
    if (eq < 0) continue;
    if (doc.lines[i].slice(0, eq).trim().toLowerCase() === want) return { value: doc.lines[i].slice(eq + 1).trim(), line: i };
  }
  return null;
}

/** Split one body line into columns. `=` gives [name, ...comma list] (proxy / group / host lines). */
export function splitCols(raw: string, sep: string): string[] {
  const s = raw.trim();
  if (sep === "=") {
    const eq = s.indexOf("=");
    if (eq < 0) return [s];
    return [s.slice(0, eq).trim(), ...s.slice(eq + 1).split(",").map((c) => c.trim())];
  }
  if (sep === " ") return s.split(/\s+/);
  return s.split(sep).map((c) => c.trim());
}

/** `k=v` parameter among item columns (e.g. `password`, `udp-relay`). */
export function colParam(cols: string[], key: string): string | null {
  const want = key.toLowerCase();
  for (const c of cols) {
    const eq = c.indexOf("=");
    if (eq > 0 && c.slice(0, eq).trim().toLowerCase() === want) return c.slice(eq + 1).trim();
  }
  return null;
}

export function iniItems(doc: ParsedConfig, section: string, sep: string, match?: string): ConfigItem[] {
  const b = doc.byKey.get(section);
  if (!b) return [];
  const re = match ? new RegExp(match) : null;
  return b.items
    .filter((i) => !re || re.test(doc.lines[i]))
    .map((i) => ({ line: i, end: i + 1, cols: splitCols(doc.lines[i], sep) }));
}

/** YAML path `dns.enable` (two levels) or `mixed-port`. */
export function yamlValue(doc: ParsedConfig, path: string): { value: string; line: number } | null {
  const [top, child] = splitPath(path);
  const b = doc.byKey.get(top);
  if (!b) return null;
  if (!child) {
    const m = YAML_TOP.exec(doc.lines[b.header]);
    return { value: unquote(m?.[2] ?? ""), line: b.header };
  }
  for (let i = b.start; i < b.end; i++) {
    const m = YAML_CHILD.exec(doc.lines[i]);
    if (m && unquote(m[1]) === child) return { value: unquote(m[2] ?? ""), line: i };
  }
  return null;
}

/** YAML list under a top key: `proxy-groups` (maps, label from `field`) or `rules` (scalars, split by `sep`). */
export function yamlItems(doc: ParsedConfig, key: string, sep?: string, field?: string, match?: string): ConfigItem[] {
  const b = doc.byKey.get(key);
  if (!b) return [];
  const re = match ? new RegExp(match) : null;
  const starts = b.items.filter((i) => YAML_ITEM.test(doc.lines[i]));
  return starts
    .map((line, k) => {
      const end = k + 1 < starts.length ? starts[k + 1] : b.end;
      const head = doc.lines[line].replace(YAML_ITEM, "").trim();
      let cols: string[];
      if (field) {
        let v = "";
        for (let i = line; i < end; i++) {
          const m = new RegExp(`^[\\s-]*${escapeRe(field)}:\\s*(.*)$`).exec(doc.lines[i]);
          if (m) { v = unquote(m[1]); break; }
        }
        cols = [v];
      } else {
        cols = sep ? head.split(sep).map((c) => c.trim()) : [unquote(head)];
      }
      return { line, end, cols };
    })
    .filter((it) => !re || re.test(doc.lines.slice(it.line, it.end).join("\n")));
}

const splitPath = (p: string): [string, string | undefined] => {
  const dot = p.indexOf(".");
  return dot < 0 ? [p, undefined] : [p.slice(0, dot), p.slice(dot + 1)];
};
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const ON = new Set(["true", "1", "on", "yes", "enable", "enabled"]);
const OFF = new Set(["false", "0", "off", "no", "disable", "disabled"]);
export function asSwitch(v: string | null | undefined): boolean | null {
  if (v == null) return null;
  const s = v.trim().toLowerCase();
  if (ON.has(s)) return true;
  if (OFF.has(s)) return false;
  return null;
}
