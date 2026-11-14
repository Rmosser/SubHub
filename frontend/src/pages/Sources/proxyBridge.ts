import type { ProxyBridgeStatus, SystemStatus } from "@/types";

// 出站代理只在有 GoRelay 来源时才是必需的；没有问题（code 为 ok）时不提醒。
export function proxyBridgeNote(status: SystemStatus | undefined): ProxyBridgeStatus | null {
  const bridge = status?.egress?.proxy_bridge;
  const relevant = bridge?.required === true || (status?.source_summary?.gorelay_count ?? 0) > 0;
  return relevant && bridge?.code && bridge.code !== "ok" ? bridge : null;
}
