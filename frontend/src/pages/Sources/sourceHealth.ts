// 一行来源此刻的状态：一个语气（点的颜色）、一句状态短语、一行时间，以及失败时的原因表。
// 原因表读 last_pull_reasons：后端按客户端给出稳定代码、脱敏后的地址和说明，已去重。
import type { GoRelaySource, PullReasonCode, StandardSource } from "@/types";
import { formatRelativeTime } from "@/utils/formatting";

export type SourceTone = "ok" | "amber" | "red" | "idle";

export interface PullReason {
  client: string;
  status: string;
  host: string;
}

const CLIENT_LABEL: Record<string, string> = { clash: "Clash", surge: "Surge", shadowrocket: "Shadowrocket" };
// 说明里没有细节的代码换成人话；其余代码显示后端的说明（HTTP 码、解析跳过原因等）
const CODE_KEYS: Partial<Record<PullReasonCode, string>> = {
  timeout: "sources.reason_timeout",
  request_failed: "sources.reason_request_failed",
  url_not_configured: "sources.reason_not_configured",
  all_methods_failed: "sources.reason_all_failed",
};

export function shortUrl(raw: string): string {
  try {
    const url = new URL(raw);
    let path = url.pathname === "/" ? "" : url.pathname;
    try { path = decodeURI(path); } catch { /* keep the escaped path */ }
    return `${url.host}${path}`;
  } catch {
    return raw.replace(/^[a-z][a-z0-9+.-]*:\/\//i, "");
  }
}

export function pullReasons(source: StandardSource, t: Translate): PullReason[] {
  return source.last_pull_reasons.map((reason) => {
    const key = CODE_KEYS[reason.code];
    return {
      client: CLIENT_LABEL[reason.method] ?? "",
      status: key ? t(key) : reason.message,
      host: reason.url ? shortUrl(reason.url) : "",
    };
  });
}

export function compatibilityCounts(source: StandardSource) {
  return Object.values(source.compatibility || {}).reduce(
    (counts, item) => ({
      refused: counts.refused + (item?.refused?.length || 0),
      pending: counts.pending + (item?.pending_validation?.length || 0),
    }),
    { refused: 0, pending: 0 },
  );
}

export interface SourceHealth {
  tone: SourceTone;
  phrase: string;
  sub: string;
  tip: string;
  nodes: number;
}

type Translate = (key: string, vars?: Record<string, string | number>) => string;

export const MANUAL_NODES = "manual_nodes";

export function sourceHealth(source: StandardSource, t: Translate, opts: { requestError?: string; now?: number; formatAbsolute?: (value: string) => string } = {}): SourceHealth {
  const now = opts.now ?? Date.now();
  const rel = (value: string | null | undefined) => formatRelativeTime(value, now);
  const abs = opts.formatAbsolute ?? ((value: string) => value);
  const tipParts = [
    source.last_success_at ? t("sources.last_success", { time: abs(source.last_success_at) }) : "",
    source.last_pull_attempt_at ? t("sources.last_attempt", { time: abs(source.last_pull_attempt_at) }) : "",
  ].filter(Boolean);
  const tip = tipParts.join(" · ");
  const failed = source.last_pull_ok === false;
  const nodes = failed ? source.cached_node_count || 0 : source.last_pull_node_count;
  const pulledSub = source.last_success_at ? t("sources.pulled_ago", { time: rel(source.last_success_at) }) : "";
  const manual = source.ingest_kind === MANUAL_NODES;

  if (!source.enabled) return { tone: "idle", phrase: t("sources.state_disabled"), sub: pulledSub, tip, nodes };
  if (opts.requestError) return { tone: "red", phrase: t("sources.pull_failed"), sub: pulledSub || t("sources.never_succeeded"), tip, nodes };
  if (failed) {
    if (nodes > 0) {
      const sub = source.last_success_at ? t("sources.reusing_nodes_from", { time: rel(source.last_success_at) }) : t("sources.reusing_cached_nodes");
      return { tone: "amber", phrase: t("sources.pull_failed"), sub, tip, nodes };
    }
    const sub = source.last_success_at ? t("sources.last_success", { time: rel(source.last_success_at) }) : t("sources.never_succeeded");
    return { tone: "red", phrase: t("sources.state_failed_empty"), sub, tip, nodes };
  }
  if (source.pull_warning_count > 0) {
    return { tone: "amber", phrase: t("sources.state_warnings", { count: source.pull_warning_count }), sub: pulledSub, tip, nodes };
  }
  const { refused, pending } = compatibilityCounts(source);
  if (refused > 0) return { tone: "amber", phrase: t("sources.state_refused", { count: refused }), sub: pulledSub, tip, nodes };
  if (pending > 0) return { tone: "amber", phrase: t("sources.state_pending", { count: pending }), sub: pulledSub, tip, nodes };
  if (source.auto_pull_expired) return { tone: "amber", phrase: t("sources.auto_pull_expired_badge"), sub: pulledSub, tip, nodes };
  if (source.last_success_at) {
    if (manual) return { tone: "idle", phrase: t("sources.state_manual"), sub: t("sources.updated_ago", { time: rel(source.updated_at) }), tip, nodes };
    return { tone: "ok", phrase: t("sources.state_ok"), sub: pulledSub, tip, nodes };
  }
  return { tone: "idle", phrase: t("sources.state_never"), sub: "", tip, nodes };
}

// GoRelay 账号的最近一次抓取。抓取失败时后端沿用上一份快照的节点，所以失败但还有节点是琥珀，没有节点才是红。
export function gorelayHealth(account: GoRelaySource, t: Translate, opts: { now?: number; formatAbsolute?: (value: string) => string } = {}): SourceHealth {
  const now = opts.now ?? Date.now();
  const abs = opts.formatAbsolute ?? ((value: string) => value);
  const at = account.last_refresh_at;
  const tip = at ? t("sources.last_attempt", { time: abs(at) }) : "";
  const sub = at ? t("sources.crawled_ago", { time: formatRelativeTime(at, now) }) : "";
  const nodes = account.last_node_count || 0;
  const status = account.last_refresh_status || "";

  if (!account.enabled) return { tone: "idle", phrase: t("sources.state_disabled"), sub, tip, nodes };
  if (status === "failed") {
    if (nodes > 0) return { tone: "amber", phrase: t("sources.gorelay_status_failed"), sub: t("sources.reusing_cached_nodes"), tip, nodes };
    return { tone: "red", phrase: t("sources.gorelay_failed_empty"), sub, tip, nodes };
  }
  if (status === "empty") return { tone: "amber", phrase: t("sources.gorelay_status_empty"), sub, tip, nodes };
  if (status === "success") return { tone: "ok", phrase: t("sources.state_ok"), sub, tip, nodes };
  return { tone: "idle", phrase: t("sources.gorelay_never"), sub: "", tip, nodes };
}

export function needsAttention(health: SourceHealth) {
  return health.tone === "amber" || health.tone === "red";
}
