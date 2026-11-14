/* The render's notes, folded by kind: one line per kind with its count, the details underneath.
   Kinds SubHub emits often get a plain sentence; anything unknown keeps the server's own words. */

export interface Warning {
  code: string;
  message: string;
  target: string;
  severity: string;
  bucket?: string;
}

export type Tone = "refused" | "pending" | "downgraded" | "info";

export interface WarningGroup {
  key: string;
  title: string;
  /** One sentence on what this kind means; null when the details already say it. */
  lead: string | null;
  tone: Tone;
  /** How many notes the server sent of this kind. */
  count: number;
  /** Distinct details, in the server's order. */
  items: string[];
}

const CLIENT = "(?:clash|surge|shadowrocket)";
const INTENT = new RegExp(`^intent-(.+?)-${CLIENT}-(unsupported|pending-validation)$`);
const INTENT_GAP = new RegExp(`^intent-(.+)-${CLIENT}$`);
const INTENT_OWN = new RegExp(`^intent-${CLIENT}-(.+)$`);

/** Intents whose message does not start with the setting's name. */
const INTENT_TITLE: Record<string, string> = {
  "contract-strict": "严格契约的回退组",
  "routing-evidence-gap": "分流声明缺少等价证据",
  "ip-dns-client-default-differs": "IP 规则查不查 DNS，各端不同",
  "ip-dns-conditional": "IP 规则能否命中，取决于兜底路径",
};

interface Known {
  title: string;
  /** Read from every note of the kind: a sentence that holds for only some of them is not the lead. */
  lead: (ws: readonly Warning[]) => string | null;
  item: (w: Warning) => string;
}

const KNOWN: Record<string, Known> = {
  "shadowrocket-inline-unsupported": {
    title: "有节点没写进配置",
    lead: (ws) => {
      const plugin = ws.filter((w) => /SS plugin/i.test(w.message)).length;
      if (plugin === ws.length) return "这些节点带 SS 插件参数，Shadowrocket 只能用节点链接导入，配置里跳过了它们。";
      if (!plugin) return "Shadowrocket 不认这些节点在配置里的写法，配置里跳过了它们。";
      return "Shadowrocket 没法把这些节点写进配置，跳过了它们。";
    },
    item: (w) => w.target || w.message,
  },
  "shadowrocket-unverified-fields-omitted": {
    title: "节点少写了没验证过的字段",
    lead: (ws) => {
      const fields = [...new Set(ws.flatMap((w) => /\(([^)]+)\)/.exec(w.message)?.[1].split(/,\s*/) ?? []))];
      return `${fields.length ? `${fields.join("、")} ` : ""}在 Shadowrocket 上没验证过，没有写；这些节点的 TLS 和传输要自己试一下能不能连。`;
    },
    item: (w) => w.target || w.message,
  },
  "shadowrocket-forwarding-proxy-pending-validation": {
    title: "前置代理没验证过",
    lead: () => "Shadowrocket 认不认 forwarding-proxy 还没验证；不认的话会直接连后面的家宽代理。",
    item: (w) => w.target || w.message,
  },
  "shadowrocket-always-real-ip-direct-access-validated": {
    title: "always-real-ip 只验证了一部分",
    lead: () => "订阅刷新和文本导出验证过；分流只在和「跳过代理」一起用的局域网测试里验证过。",
    item: (w) => w.target || w.message,
  },
  "clash-always-real-ip-pending-validation": {
    title: "没确认安全的设置没写",
    lead: () => "这些设置在 Mihomo 上还没确认安全，没有写进配置。",
    item: (w) => w.target || w.message,
  },
  "duplicate-ip-rule": {
    title: "重复的 IP 规则只留了一条",
    lead: () => "同一个网段写了不止一次，后面的已忽略。",
    item: (w) => /IP-CIDR6?,\S+/.exec(w.message)?.[0] ?? w.message,
  },
  "mac-only-rule-ignored": {
    title: "只在 Mac 上用的规则没写进来",
    lead: () => "PROCESS-NAME 规则只写进 surge-mac-overlay.conf，手机上的配置里没有。",
    item: (w) => w.target || w.message,
  },
};

function toneOf(w: Warning): Tone {
  if (w.bucket === "refused" || w.severity === "error") return "refused";
  if (w.bucket === "pending_validation") return "pending";
  if (w.severity === "info") return "info";
  return "downgraded";
}

const ORDER: Tone[] = ["refused", "pending", "downgraded", "info"];

/** `设置名：说明` → [设置名, 说明]; only when the prefix reads like a name. */
function splitName(message: string): [string, string] | null {
  const at = message.indexOf("：");
  if (at <= 0 || at > 14) return null;
  const name = message.slice(0, at);
  if (/[（(，。]/.test(name)) return null;
  return [name, message.slice(at + 1)];
}

/** Longest title drawn from the server's own words; longer ones are cut and the whole note goes underneath. */
const TITLE_MAX = 24;

/** A title for a note SubHub has no sentence for: its setting name, or the note itself, cut short. */
function titleOf(message: string): string {
  const name = splitName(message)?.[0];
  if (name) return name;
  const t = message.trim();
  return t.length > TITLE_MAX ? `${t.slice(0, TITLE_MAX - 1).trimEnd()}…` : t;
}

/** Strip a leading `设置名：` from a body that repeats it. */
function body(message: string): string {
  return splitName(message)?.[1] ?? message;
}

function intentKey(code: string): { family: string; status: "unsupported" | "pending" | null } | null {
  let m = INTENT.exec(code);
  if (m) return { family: m[1], status: m[2] === "unsupported" ? "unsupported" : "pending" };
  m = INTENT_OWN.exec(code);
  if (m && INTENT_TITLE[m[1]]) return { family: m[1], status: null };
  if (INTENT_TITLE[code.slice("intent-".length)]) return { family: code.slice("intent-".length), status: null };
  m = INTENT_GAP.exec(code);
  if (m) return { family: m[1], status: null };
  return null;
}

export function groupWarnings(list: readonly Warning[]): WarningGroup[] {
  const groups = new Map<string, WarningGroup & { known?: Known; notes: Warning[]; tones: Set<Tone>; statuses: Set<string>; seen: Set<string> }>();
  for (const w of list) {
    if (!w?.message) continue;
    let key: string, title: string, item: string;
    const known = KNOWN[w.code];
    const intent = known ? null : w.code.startsWith("intent-") ? intentKey(w.code) : null;
    if (known) {
      key = w.code; title = known.title; item = known.item(w);
    } else if (intent) {
      key = `intent:${intent.family}`;
      title = INTENT_TITLE[intent.family] ?? titleOf(w.message);
      item = body(w.message).replace(/^本项没有可证明等价的 \w+ 投影。/, "");
    } else {
      key = `raw:${w.code}`; title = titleOf(w.message); item = body(w.message).trim();
    }
    let g = groups.get(key);
    if (!g) {
      g = { key, title, lead: null, known, notes: [], tone: toneOf(w), count: 0, items: [], tones: new Set(), statuses: new Set(), seen: new Set() };
      groups.set(key, g);
    }
    g.count++;
    g.notes.push(w);
    g.tones.add(toneOf(w));
    if (intent?.status) g.statuses.add(intent.status);
    if (!g.seen.has(item)) { g.seen.add(item); g.items.push(item); }
  }
  const out: WarningGroup[] = [];
  for (const g of groups.values()) {
    const tone = ORDER.find((t) => g.tones.has(t)) ?? "downgraded";
    let lead = g.known ? g.known.lead(g.notes) : null;
    if (g.key.startsWith("intent:")) {
      lead = g.statuses.has("unsupported") && !g.statuses.has("pending") ? "这一端没有等价的写法，没写进配置。"
        : g.statuses.has("unsupported") ? "有的没写进配置，写进去的效果要自己核对。"
          : "写进了配置，效果要自己核对。";
    }
    // A raw kind with a single note: the title already is the note, unless it had to be cut.
    const items = g.key.startsWith("raw:") && g.items.length === 1 && g.items[0] === g.title ? [] : g.items;
    out.push({ key: g.key, title: g.title, lead, tone, count: g.count, items });
  }
  return out.sort((a, b) => ORDER.indexOf(a.tone) - ORDER.indexOf(b.tone));
}
