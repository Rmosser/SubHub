/* Secret spans inside one config line. Masked by default; the page reveals one value at a time.
   Covers credential params (`password=` / `password:`), positional socks5 / http credentials,
   Surge `http-api = key@host`, and tokens inside URLs. */

export interface Span {
  from: number;
  to: number;
}

const KEYS =
  "password|passwd|psk|uuid|private-key|privatekey|preshared-key|pre-shared-key|obfs-password|auth|auth-str|auth_str|" +
  "token|secret|http-api-secret|external-controller-secret|clash-secret|username|user|short-id|reality-short-id";
const PARAM = new RegExp(`(?<![\\w-])(?:${KEYS})\\s*[:=]\\s*("[^"]*"|'[^']*'|[^,}\\s]+)`, "gi");
const POSITIONAL = /^\s*[^=#;[]+?=\s*(socks5|socks5-tls|http|https)\s*,/i;
const HTTP_API = /^\s*http-api\s*=\s*([^@\s]+)@/i;
const URL = /\b[a-z][a-z0-9+.-]*:\/\/[^\s,"']+/gi;
const URL_SECRET_PARAM = /[?&](?:token|sig|key|auth|password|secret|sub|t|access_token)=([^&#\s]+)/gi;
const URL_LONG_SEGMENT = /\/([A-Za-z0-9_-]{20,})(?=[/?.#]|$)/g;
const URL_DEVICE = /\/sub\/device\/([^/?#\s]+)/g;
const URL_USERINFO = /^[a-z][a-z0-9+.-]*:\/\/([^/@\s]+)@/i;

export function secretSpans(line: string): Span[] {
  const out: Span[] = [];
  for (const m of line.matchAll(PARAM)) {
    const v = m[1];
    const at = (m.index ?? 0) + m[0].length - v.length;
    out.push({ from: at, to: at + v.length });
  }
  const pos = POSITIONAL.exec(line);
  if (pos) {
    // name = socks5, server, port, username, password, …
    const eq = line.indexOf("=");
    let at = eq + 1;
    const parts = line.slice(eq + 1).split(",");
    parts.forEach((p, k) => {
      const start = at + (p.length - p.trimStart().length);
      const v = p.trim();
      if ((k === 3 || k === 4) && v && !v.includes("=")) out.push({ from: start, to: start + v.length });
      at += p.length + 1;
    });
  }
  const api = HTTP_API.exec(line);
  if (api) {
    const at = line.indexOf(api[1], line.indexOf("="));
    out.push({ from: at, to: at + api[1].length });
  }
  for (const u of line.matchAll(URL)) {
    const base = u.index ?? 0;
    for (const p of u[0].matchAll(URL_SECRET_PARAM)) {
      const at = base + (p.index ?? 0) + p[0].length - p[1].length;
      out.push({ from: at, to: at + p[1].length });
    }
    for (const d of u[0].matchAll(URL_DEVICE)) {
      const at = base + (d.index ?? 0) + d[0].length - d[1].length;
      out.push({ from: at, to: at + d[1].length });
    }
    const ui = URL_USERINFO.exec(u[0]);
    if (ui) {
      const at = base + u[0].indexOf(ui[1]);
      out.push({ from: at, to: at + ui[1].length });
    }
    for (const s of u[0].matchAll(URL_LONG_SEGMENT)) {
      const at = base + (s.index ?? 0) + 1;
      out.push({ from: at, to: at + s[1].length });
    }
  }
  return merge(out);
}

function merge(spans: Span[]): Span[] {
  const s = spans.filter((x) => x.to > x.from).sort((a, b) => a.from - b.from);
  const out: Span[] = [];
  for (const x of s) {
    const last = out[out.length - 1];
    if (last && x.from <= last.to) last.to = Math.max(last.to, x.to);
    else out.push({ ...x });
  }
  return out;
}

export const MASK = "••••••";

/** Fully masked copy of a value (for phone rows that show a credential). */
export function maskValue(v: string): string {
  return v ? MASK : v;
}

/** True when a bound key names a credential. */
export function isSecretKey(key: string | undefined): boolean {
  return !!key && new RegExp(`^(?:${KEYS})$`, "i").test(key.trim());
}
