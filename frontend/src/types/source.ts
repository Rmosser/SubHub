import type { RenderWarning } from "./device";

export interface SourceRendererDiagnostics {
  supported: RenderWarning[];
  downgraded: RenderWarning[];
  pending_validation: RenderWarning[];
  refused: RenderWarning[];
}

/** Stable reason codes for a failed pull attempt (`docs/api/http-api.md`). */
export type PullReasonCode =
  | "url_not_configured"
  | "http_status"
  | "timeout"
  | "request_failed"
  | "invalid_payload"
  | "no_valid_nodes"
  | "fetch_failed"
  | "manual_nodes_missing"
  | "refresh_failed"
  | "all_methods_failed"
  | "unclassified";

/** One failed attempt of the last pull. `url` and `message` are redacted by the server. */
export interface StandardSourcePullReason {
  method: string;
  code: PullReasonCode;
  url: string;
  message: string;
}

export interface StandardSource {
  id: string;
  name: string;
  clash_url: string;
  shadowrocket_url: string;
  surge_url: string;
  login_url: string;
  quality_group: string;
  target_contract_id: string;
  target_contract_display_name: string;
  source_mode: string;
  ingest_kind: string;
  manual_nodes_text: string;
  enabled: boolean;
  last_pull_attempt_at: string | null;
  last_success_at: string | null;
  last_pull_ok: boolean | null;
  last_pull_method: string;
  last_pull_node_count: number;
  last_pull_error: string;
  last_pull_reasons: StandardSourcePullReason[];
  pull_network_mode: string;
  auto_pull_consecutive_failures: number;
  auto_pull_expired: boolean;
  auto_pull_expired_at: string | null;
  last_success_config_fingerprint: string;
  config_fingerprint: string;
  export_config: Record<string, unknown>;
  pull_warning_count: number;
  pull_warnings: StandardSourceWarningItem[];
  cached_node_count: number;
  compatibility: Record<string, SourceRendererDiagnostics>;
  updated_at: string;
}

export interface StandardSourceWarningItem {
  code: string;
  message: string;
  field: string;
  expected_method: string;
  actual_variant: string;
  severity: string;
}

export interface StandardSourceQrAsset {
  source_id: string;
  field: string;
  file_relpath: string;
  mime_type: string;
  detected_url: string;
  updated_at: string;
}

export interface GoRelayAccount {
  id: string;
  name: string;
  login_url: string;
  rules_url: string;
  gorelay_username: string;
  has_gorelay_password: boolean;
  proxy_username_default: string;
  has_proxy_password_default: boolean;
  selectors_json: string;
  mcp_url: string;
  has_auth_header: boolean;
  login_tool: string;
  nodes_tool: string;
  login_args_json: string;
  nodes_args_json: string;
  enabled: boolean;
  updated_at: string;
}

export interface GoRelaySource {
  id: string;
  name: string;
  login_url: string;
  gorelay_username: string;
  has_gorelay_password: boolean;
  proxy_username: string;
  has_proxy_password: boolean;
  selectors_json: string;
  enabled: boolean;
  updated_at: string;
  last_refresh_at?: string | null;
  last_refresh_status?: string;
  last_refresh_error?: string;
  last_node_count?: number;
  last_device_count?: number;
  pending_domain_count?: number;
  latest_snapshot_id?: string;
  active_snapshot_id?: string;
  active_snapshot_is_latest?: boolean;
}

export interface GoRelayAccountStatus {
  ok: boolean;
  account_id: string;
  name: string;
  enabled: boolean;
  active_snapshot_id: string;
  latest_snapshot_id: string;
  latest_status: string;
  latest_error: string | null;
  latest_node_count: number;
  latest_device_count: number;
  pending_domain_count: number;
  source_status: Record<string, unknown>;
  snapshot_id?: string | null;
  created_at?: string | null;
}

export interface GoRelayUsageDevice {
  device_key: string;
  device_name: string;
  ports: number[];
  rule_count: number;
}

export interface GoRelayAccountDevice {
  device_key: string;
  device_name: string;
  node_count: number;
  entry_count: number;
  entries: string[];
  proxy_username_override: string;
  proxy_password_override: string;
  strategy_preset: string;
  profile_enabled: boolean;
  subscription_id: string | null;
  subscription_enabled: boolean;
  subscription_count: number;
  is_stale: boolean;
  preview: Record<string, { available: boolean; reason_text: string[] }>;
  links: Record<string, string>;
}

export interface GoRelayBinding {
  id?: string;
  binding_id?: string;
  account_id?: string;
  entry_name: string;
  isp: string;
  ip_version: string;
  /** Missing on pending entries: a host is only known once the binding is approved. */
  host_value?: string;
  status?: string;
  source?: string;
  binding_source?: string;
  resolved?: boolean;
  ports: number[];
  devices: GoRelayUsageDevice[];
}

export interface GoRelayPendingBindingsResponse {
  pending: GoRelayBinding[];
  bindings: GoRelayBinding[];
}

export interface GoRelayEntryUsage {
  entry_name: string;
  isp: string;
  ip_version: string;
  ports: number[];
  devices: GoRelayUsageDevice[];
  hosts?: string[];
}

export interface GoRelayDomainImportHistory {
  id: string;
  account_id: string;
  created_at: string;
  reply_text?: string;
  source_type?: string;
  applied_bindings?: Record<string, unknown>[];
  skipped_bindings?: Record<string, unknown>[];
}

export interface GoRelaySnapshot {
  account_id: string;
  snapshot_id: string;
  created_at: string;
  node_count: number;
  device_count: number;
  status: string;
  error?: string;
  active: boolean;
}

export interface GoRelaySubscription {
  id: string;
  account_id: string;
  device_key: string;
  device_name: string;
  subscription_id: string;
  enabled: boolean;
  updated_at?: string;
  links: Record<string, string>;
}

export interface RefreshPolicy {
  rule_catalog_cache_hours: number;
  cn_cache_hours: number;
  standard_source_auto_pull_enabled: boolean;
  standard_source_auto_pull_interval_minutes: number;
}

export interface StandardSourcePullResult {
  ok: boolean;
  method: string;
  node_count: number;
  cached_node_count: number;
  error: string;
  attempts: Record<string, unknown>[];
  warning_count: number;
  warnings: StandardSourceWarningItem[];
  filtered_technical_count: number;
  filtered_technical_examples: string[];
  last_success_at: string | null;
  config_fingerprint: string;
  last_success_config_fingerprint: string;
}

export interface StandardSourcePullResponse {
  ok: boolean;
  item: StandardSource;
  pull_result: StandardSourcePullResult;
}
