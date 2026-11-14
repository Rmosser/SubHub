import type {
  GoRelayAccountDevice,
  GoRelayAccountStatus,
  GoRelayBinding,
  GoRelayDomainImportHistory,
  GoRelayEntryUsage,
  GoRelayPendingBindingsResponse,
  GoRelaySnapshot,
  GoRelaySource,
  GoRelaySubscription,
  GoRelayUsageDevice,
  RefreshPolicy,
  RenderWarning,
  SourceRendererDiagnostics,
  StandardSource,
  StandardSourcePullReason,
  StandardSourcePullResponse,
  StandardSourcePullResult,
  StandardSourceWarningItem,
} from "@/types";
import {
  anyRecord,
  array,
  bool,
  itemResponse,
  listResponse,
  literal,
  nullable,
  num,
  object,
  optional,
  record,
  response,
  str,
} from "./schema";

const renderWarning = object<RenderWarning>({
  code: str,
  message: str,
  target: str,
  severity: str,
  bucket: optional(str),
});

const rendererDiagnostics = object<SourceRendererDiagnostics>({
  supported: array(renderWarning),
  downgraded: array(renderWarning),
  pending_validation: array(renderWarning),
  refused: array(renderWarning),
});

const warningItem = object<StandardSourceWarningItem>({
  code: str,
  message: str,
  field: str,
  expected_method: str,
  actual_variant: str,
  severity: str,
});

const pullReason = object<StandardSourcePullReason>({
  method: str,
  code: literal(
    "url_not_configured",
    "http_status",
    "timeout",
    "request_failed",
    "invalid_payload",
    "no_valid_nodes",
    "fetch_failed",
    "manual_nodes_missing",
    "refresh_failed",
    "all_methods_failed",
    "unclassified",
  ),
  url: str,
  message: str,
});

export const standardSource = object<StandardSource>({
  id: str,
  name: str,
  clash_url: str,
  shadowrocket_url: str,
  surge_url: str,
  login_url: str,
  quality_group: str,
  target_contract_id: str,
  target_contract_display_name: str,
  source_mode: str,
  ingest_kind: str,
  manual_nodes_text: str,
  enabled: bool,
  last_pull_attempt_at: nullable(str),
  last_success_at: nullable(str),
  last_pull_ok: nullable(bool),
  last_pull_method: str,
  last_pull_node_count: num,
  last_pull_error: str,
  last_pull_reasons: array(pullReason),
  pull_network_mode: str,
  auto_pull_consecutive_failures: num,
  auto_pull_expired: bool,
  auto_pull_expired_at: nullable(str),
  last_success_config_fingerprint: str,
  config_fingerprint: str,
  export_config: anyRecord,
  pull_warning_count: num,
  pull_warnings: array(warningItem),
  cached_node_count: num,
  compatibility: record(rendererDiagnostics),
  updated_at: str,
});

export const goRelaySource = object<GoRelaySource>({
  id: str,
  name: str,
  login_url: str,
  gorelay_username: str,
  has_gorelay_password: bool,
  proxy_username: str,
  has_proxy_password: bool,
  selectors_json: str,
  enabled: bool,
  updated_at: str,
  last_refresh_at: optional(str),
  last_refresh_status: optional(str),
  last_refresh_error: optional(str),
  last_node_count: optional(num),
  last_device_count: optional(num),
  pending_domain_count: optional(num),
  latest_snapshot_id: optional(str),
  active_snapshot_id: optional(str),
  active_snapshot_is_latest: optional(bool),
});

const refreshPolicy = object<RefreshPolicy>({
  rule_catalog_cache_hours: num,
  cn_cache_hours: num,
  standard_source_auto_pull_enabled: bool,
  standard_source_auto_pull_interval_minutes: num,
});

const accountStatus = object<GoRelayAccountStatus>({
  ok: bool,
  account_id: str,
  name: str,
  enabled: bool,
  active_snapshot_id: str,
  latest_snapshot_id: str,
  latest_status: str,
  latest_error: nullable(str),
  latest_node_count: num,
  latest_device_count: num,
  pending_domain_count: num,
  source_status: anyRecord,
  snapshot_id: optional(str),
  created_at: optional(str),
});

const accountDevice = object<GoRelayAccountDevice>({
  device_key: str,
  device_name: str,
  node_count: num,
  entry_count: num,
  entries: array(str),
  proxy_username_override: str,
  proxy_password_override: str,
  strategy_preset: str,
  profile_enabled: bool,
  subscription_id: nullable(str),
  subscription_enabled: bool,
  subscription_count: num,
  is_stale: bool,
  preview: record(object<{ available: boolean; reason_text: string[] }>({ available: bool, reason_text: array(str) })),
  links: record(str),
});

const usageDevice = object<GoRelayUsageDevice>({
  device_key: str,
  device_name: str,
  ports: array(num),
  rule_count: num,
});

const binding = object<GoRelayBinding>({
  id: optional(str),
  binding_id: optional(str),
  account_id: optional(str),
  entry_name: str,
  isp: str,
  ip_version: str,
  host_value: optional(str),
  status: optional(str),
  source: optional(str),
  binding_source: optional(str),
  resolved: optional(bool),
  ports: array(num),
  devices: array(usageDevice),
});

const entryUsage = object<GoRelayEntryUsage>({
  entry_name: str,
  isp: str,
  ip_version: str,
  ports: array(num),
  devices: array(usageDevice),
  hosts: optional(array(str)),
});

const importHistory = object<GoRelayDomainImportHistory>({
  id: str,
  account_id: str,
  created_at: str,
  reply_text: optional(str),
  source_type: optional(str),
  applied_bindings: optional(array(anyRecord)),
  skipped_bindings: optional(array(anyRecord)),
});

const snapshot = object<GoRelaySnapshot>({
  account_id: str,
  snapshot_id: str,
  created_at: str,
  node_count: num,
  device_count: num,
  status: str,
  error: optional(str),
  active: bool,
});

const subscription = object<GoRelaySubscription>({
  id: str,
  account_id: str,
  device_key: str,
  device_name: str,
  subscription_id: str,
  enabled: bool,
  updated_at: optional(str),
  links: record(str),
});

const pullResult = object<StandardSourcePullResult>({
  ok: bool,
  method: str,
  node_count: num,
  cached_node_count: num,
  error: str,
  attempts: array(anyRecord),
  warning_count: num,
  warnings: array(warningItem),
  filtered_technical_count: num,
  filtered_technical_examples: array(str),
  last_success_at: nullable(str),
  config_fingerprint: str,
  last_success_config_fingerprint: str,
});

export type GoRelaySnapshotList = { ok: boolean; active_snapshot_id: string; items: GoRelaySnapshot[] };

export const parseStandardSourceList = listResponse(standardSource);
export const parseGoRelaySourceList = listResponse(goRelaySource);
export const parseGoRelaySourceItem = itemResponse(goRelaySource);
export const parseRefreshPolicyItem = itemResponse(refreshPolicy);
export const parseGoRelayAccountStatus = response(accountStatus);
export const parseGoRelayAccountDeviceList = listResponse(accountDevice);
export const parseGoRelayPendingBindings = response(
  object<GoRelayPendingBindingsResponse>({ pending: array(binding), bindings: array(binding) }),
);
export const parseGoRelayEntryUsageList = listResponse(entryUsage);
export const parseGoRelayImportHistoryList = listResponse(importHistory);
export const parseGoRelaySnapshotList = response(
  object<GoRelaySnapshotList>({ ok: bool, active_snapshot_id: str, items: array(snapshot) }),
);
export const parseGoRelaySubscriptionList = listResponse(subscription);
export const parseStandardSourcePullResponse = response(
  object<StandardSourcePullResponse>({ ok: bool, item: standardSource, pull_result: pullResult }),
);
