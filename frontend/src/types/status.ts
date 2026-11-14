export interface SystemStatus {
  hub_runtime: HubRuntime;
  source_summary: SourceSummary;
  egress: EgressStatus;
}

export interface HubRuntime {
  last_refresh_at: string | null;
  last_error: string | null;
  source_status: Record<string, unknown>;
}

export interface PoolStatusItem {
  id: string;
  display_name: string;
  node_count: number;
  renderable_node_count: number;
  last_refresh_at: string;
  sources: Record<string, number>;
  pseudo: boolean;
}

export interface SourceSummary {
  gorelay_count: number;
  standard_count: number;
  standard_expired: number;
  standard_failed: number;
}

export interface ProxyBridgeStatus {
  code: string;
  severity: string;
  summary: string;
  meaning: string;
  repair_hint: string;
  last_error: string;
  actions: string[];
  required: boolean;
  [key: string]: unknown;
}

export interface EgressStatus {
  proxy_bridge: ProxyBridgeStatus;
  [key: string]: unknown;
}

export interface OverlayStatus {
  available: boolean;
  reason_code: string;
  reason: string;
  renderable_process_rule_count: number;
  renderable_external_proxy_program_count: number;
}
