import type { OverlayStatus } from "./status";

export interface DeviceSubscription {
  id: string;
  device_key: string;
  device_name: string;
  subscription_id: string;
  enabled: boolean;
  last_seen_at: string | null;
  last_seen_ip: string | null;
}

export interface DeviceLinks {
  clash_url: string;
  surge_url: string;
  /** Opaque ASCII filename isolates each subscription and scenario. */
  shadowrocket_url: string;
  shadowrocket_nodes_url: string;
  clash_scheme: string;
  surge_scheme: string;
  /** config/add/<raw URL> replaces the default configuration in Shadowrocket. */
  shadowrocket_scheme: string;
  surge_mac_overlay_scheme: string;
  surge_mac_overlay_url: string;
  [key: string]: string;
}

export interface DeviceWithLinks extends DeviceSubscription {
  scenario_id: string;
  scenario_slug: string;
  scenario_name: string;
  links: DeviceLinks;
  overlay_status: OverlayStatus;
}

export interface PreviewAssetCounts {
  domain_sets: number;
  rule_sets: number;
}

export interface DevicePreview {
  ok: boolean;
  target: string;
  scenario_id: string;
  scenario_slug: string;
  scenario_name: string;
  revision: string;
  metadata: Record<string, unknown>;
  content: string;
  policy_ir: Record<string, unknown> | null;
  diagnostics: RenderWarning[];
  blockers: RenderWarning[];
  blocked: boolean;
  skipped: string[];
  asset_counts: PreviewAssetCounts;
}

export interface RenderWarning {
  code: string;
  message: string;
  target: string;
  severity: string;
  bucket?: string;
}

export type PreviewSummary = Record<string, unknown>;

export interface PreviewContent {
  text: string;
  lineCount: number;
  charCount: number;
}
