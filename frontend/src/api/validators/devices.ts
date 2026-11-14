import type {
  ApiListResponse,
  DeviceLinks,
  DevicePreview,
  DeviceWithLinks,
  OverlayStatus,
  PreviewSummary,
  RenderWarning,
} from "@/types";
import { isRecord } from "./shared";
import { parseOverlayStatus } from "./status";

function requiredRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid devices response: ${path} must be an object`);
  }
  return value;
}

function requiredString(value: unknown, path: string): string {
  if (typeof value !== "string") {
    throw new Error(`Invalid devices response: ${path} must be a string`);
  }
  return value;
}

function requiredBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`Invalid devices response: ${path} must be a boolean`);
  }
  return value;
}

function requiredNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Invalid devices response: ${path} must be a number`);
  }
  return value;
}

function requiredStringArray(value: unknown, path: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`Invalid devices response: ${path} must be an array of strings`);
  }
  return value;
}

function nullableString(value: unknown, path: string): string | null {
  if (value !== null && typeof value !== "string") {
    throw new Error(`Invalid devices response: ${path} must be a string or null`);
  }
  return value;
}

const DEVICE_LINK_FIELDS = [
  "clash_url",
  "shadowrocket_url",
  "shadowrocket_nodes_url",
  "surge_url",
  "surge_mac_overlay_url",
  "clash_scheme",
  "shadowrocket_scheme",
  "surge_scheme",
  "surge_mac_overlay_scheme",
] as const;

function parseDeviceLinks(raw: unknown, path: string): DeviceLinks {
  const payload = requiredRecord(raw, path);
  const links = Object.fromEntries(
    DEVICE_LINK_FIELDS.map((field) => [field, requiredString(payload[field], `${path}.${field}`)]),
  ) as DeviceLinks;
  if (!links.shadowrocket_scheme.startsWith("shadowrocket://config/add/")) {
    throw new Error(`Invalid devices response: ${path}.shadowrocket_scheme must use config/add/<raw URL>`);
  }
  if (links.shadowrocket_scheme.slice("shadowrocket://config/add/".length) !== links.shadowrocket_url) {
    throw new Error(`Invalid devices response: ${path}.shadowrocket_scheme must contain the raw configuration URL`);
  }
  return links;
}

function parseDevice(raw: unknown, index: number): DeviceWithLinks {
  const path = `items[${index}]`;
  const payload = requiredRecord(raw, path);
  return {
    id: requiredString(payload.id, `${path}.id`),
    device_key: requiredString(payload.device_key, `${path}.device_key`),
    device_name: requiredString(payload.device_name, `${path}.device_name`),
    subscription_id: requiredString(payload.subscription_id, `${path}.subscription_id`),
    enabled: requiredBoolean(payload.enabled, `${path}.enabled`),
    last_seen_at: nullableString(payload.last_seen_at, `${path}.last_seen_at`),
    last_seen_ip: nullableString(payload.last_seen_ip, `${path}.last_seen_ip`),
    scenario_id: requiredString(payload.scenario_id, `${path}.scenario_id`),
    scenario_slug: requiredString(payload.scenario_slug, `${path}.scenario_slug`),
    scenario_name: requiredString(payload.scenario_name, `${path}.scenario_name`),
    links: parseDeviceLinks(payload.links, `${path}.links`),
    overlay_status: parseOverlayStatus(payload.overlay_status, `${path}.overlay_status`),
  };
}

function sameOverlayStatus(left: OverlayStatus, right: OverlayStatus): boolean {
  return (
    left.available === right.available &&
    left.reason_code === right.reason_code &&
    left.reason === right.reason &&
    left.renderable_process_rule_count === right.renderable_process_rule_count &&
    left.renderable_external_proxy_program_count === right.renderable_external_proxy_program_count
  );
}

export function parseDeviceListResponse(raw: unknown): ApiListResponse<DeviceWithLinks> {
  const payload = requiredRecord(raw, "response");
  if (payload.ok !== true) {
    throw new Error("Invalid devices response: ok must be true");
  }
  if (!Array.isArray(payload.items)) {
    throw new Error("Invalid devices response: items must be an array");
  }

  const items = payload.items.map(parseDevice);
  // The endpoint returns one overlay snapshot for the selected scenario on every device.
  // Reject a mixed response instead of silently using an arbitrary first device.
  const firstOverlay = items[0]?.overlay_status;
  if (firstOverlay && items.some((item) => !sameOverlayStatus(firstOverlay, item.overlay_status))) {
    throw new Error("Invalid devices response: overlay_status must match across the selected scenario");
  }
  return { items };
}

interface RawDevicePreviewResponse {
  ok?: unknown;
  target?: unknown;
  scenario_id?: unknown;
  scenario_slug?: unknown;
  scenario_name?: unknown;
  revision?: unknown;
  metadata?: unknown;
  content?: unknown;
  policy_ir?: unknown;
  diagnostics?: unknown;
  blockers?: unknown;
  blocked?: unknown;
  skipped?: unknown;
  asset_counts?: unknown;
}

function normalizeWarningList(value: unknown, path: string): RenderWarning[] {
  if (isRecord(value)) {
    return ["supported", "downgraded", "refused", "pending_validation"].flatMap((bucket) => {
      const entries = value[bucket];
      if (!Array.isArray(entries)) {
        throw new Error(`Invalid devices response: ${path}.${bucket} must be an array`);
      }
      return entries.map((item, index) => parseRenderWarning(item, `${path}.${bucket}[${index}]`))
        .map((item) => ({ ...item, bucket }));
    });
  }

  if (!Array.isArray(value)) {
    throw new Error(`Invalid devices response: ${path} must be an array or diagnostics object`);
  }

  return value.map((item, index) => parseRenderWarning(item, `${path}[${index}]`));
}

function parseRenderWarning(value: unknown, path: string): RenderWarning {
  const item = requiredRecord(value, path);
  const warning = {
    code: requiredString(item.code, `${path}.code`),
    message: requiredString(item.message, `${path}.message`),
    target: requiredString(item.target, `${path}.target`),
    severity: requiredString(item.severity, `${path}.severity`),
  };
  if (item.bucket !== undefined && typeof item.bucket !== "string") {
    throw new Error(`Invalid devices response: ${path}.bucket must be a string`);
  }
  return item.bucket === undefined ? warning : { ...warning, bucket: item.bucket };
}

function normalizeSkippedList(value: unknown): string[] {
  return requiredStringArray(value, "skipped");
}

export function normalizeDevicePreviewResponse(raw: unknown): DevicePreview {
  const payload: RawDevicePreviewResponse = requiredRecord(raw, "response");
  if (payload.ok !== true) {
    throw new Error("Invalid devices response: ok must be true");
  }
  const metadata = requiredRecord(payload.metadata, "metadata");
  const policyIr = payload.policy_ir === null ? null : requiredRecord(payload.policy_ir, "policy_ir");
  const assetCounts = requiredRecord(payload.asset_counts, "asset_counts");

  return {
    ok: true,
    target: requiredString(payload.target, "target"),
    scenario_id: requiredString(payload.scenario_id, "scenario_id"),
    scenario_slug: requiredString(payload.scenario_slug, "scenario_slug"),
    scenario_name: requiredString(payload.scenario_name, "scenario_name"),
    revision: requiredString(payload.revision, "revision"),
    metadata,
    content: requiredString(payload.content, "content"),
    policy_ir: policyIr,
    diagnostics: normalizeWarningList(payload.diagnostics, "diagnostics"),
    blockers: normalizeWarningList(payload.blockers, "blockers"),
    blocked: requiredBoolean(payload.blocked, "blocked"),
    skipped: normalizeSkippedList(payload.skipped),
    asset_counts: {
      domain_sets: requiredNumber(assetCounts.domain_sets, "asset_counts.domain_sets"),
      rule_sets: requiredNumber(assetCounts.rule_sets, "asset_counts.rule_sets"),
    },
  };
}

export function normalizePreviewSummary(raw: unknown): PreviewSummary {
  const payload = requiredRecord(raw, "response");
  if (payload.ok !== true) {
    throw new Error("Invalid devices response: ok must be true");
  }
  requiredString(payload.target, "target");
  requiredString(payload.revision, "revision");
  requiredRecord(payload.metadata, "metadata");
  requiredRecord(payload.summary, "summary");
  return payload;
}
