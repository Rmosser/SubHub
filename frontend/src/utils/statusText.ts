import type { StatusKind } from "@/components/StatusBadge";
import type { OverlayStatus } from "@/types";

type Translate = (key: string, vars?: Record<string, string | number>) => string;

// 后端给的是英文原文与机器码：已知码走 i18n，未知码用后端原文兜底。
const OVERLAY_REASON_KEYS: Record<string, string> = {
  needs_rebind: "overlay.reason_needs_rebind",
  missing_templates: "overlay.reason_missing_templates",
  all_templates_disabled: "overlay.reason_all_templates_disabled",
};

export function overlayReasonText(status: Pick<OverlayStatus, "reason_code" | "reason">, t: Translate): string {
  const key = OVERLAY_REASON_KEYS[status.reason_code];
  return key ? t(key) : status.reason || status.reason_code || "";
}

// needs_rebind 时订阅接口直接 409，是阻断；其余不可用是提醒。
export function overlayStatusKind(status: Pick<OverlayStatus, "available" | "reason_code">): StatusKind {
  if (status.available) return "success";
  return status.reason_code === "needs_rebind" ? "error" : "warning";
}

const PROXY_BRIDGE_KEYS: Record<string, string> = {
  ok: "advanced.proxy_bridge_ok",
  not_checked: "advanced.proxy_bridge_not_checked",
  missing_proxy_env: "advanced.proxy_bridge_missing_proxy_env",
  invalid_proxy_env: "advanced.proxy_bridge_invalid_proxy_env",
  proxy_bridge_unreachable: "advanced.proxy_bridge_unreachable",
  proxy_bridge_upstream_failed: "advanced.proxy_bridge_upstream_failed",
};

// 出站代理桥接的状态码：已知码给一句短标签；未知码返回 null，由调用处按严重级别给通用标签并附上原码。
export function proxyBridgeLabel(code: string, t: Translate): string | null {
  const key = PROXY_BRIDGE_KEYS[code];
  return key ? t(key) : null;
}

// 诊断的严重程度：已知值走 i18n，未知值原样显示（徽章颜色由调用处决定）
const SEVERITY_KEYS = new Map<string, string>([
  ["error", "common.severity_error"],
  ["warning", "common.severity_warning"],
  ["info", "common.severity_info"],
  ["fatal", "common.severity_fatal"],
]);

export function severityLabel(severity: string, t: Translate): string {
  const key = SEVERITY_KEYS.get(severity);
  return key ? t(key) : severity;
}
