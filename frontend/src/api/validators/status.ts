import type {
  EgressStatus,
  HubRuntime,
  OverlayStatus,
  ProxyBridgeStatus,
  SourceSummary,
  SystemStatus,
} from "@/types";
import { isRecord } from "./shared";

function requiredRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid status response: ${path} must be an object`);
  }
  return value;
}

function requiredString(value: unknown, path: string): string {
  if (typeof value !== "string") {
    throw new Error(`Invalid status response: ${path} must be a string`);
  }
  return value;
}

function requiredBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`Invalid status response: ${path} must be a boolean`);
  }
  return value;
}

function requiredNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Invalid status response: ${path} must be a number`);
  }
  return value;
}

function nullableString(value: unknown, path: string): string | null {
  if (value !== null && typeof value !== "string") {
    throw new Error(`Invalid status response: ${path} must be a string or null`);
  }
  return value;
}

function requiredStringArray(value: unknown, path: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`Invalid status response: ${path} must be an array of strings`);
  }
  return value;
}

function parseHubRuntime(raw: unknown): HubRuntime {
  const payload = requiredRecord(raw, "runtime");
  const sourceStatus = requiredRecord(payload.source_status, "runtime.source_status");

  if (sourceStatus.standard !== undefined) {
    const standard = requiredRecord(sourceStatus.standard, "runtime.source_status.standard");
    for (const [sourceId, rawStatus] of Object.entries(standard)) {
      const status = requiredRecord(rawStatus, `runtime.source_status.standard.${sourceId}`);
      if (status.ok !== undefined && typeof status.ok !== "boolean") {
        throw new Error(`Invalid status response: runtime.source_status.standard.${sourceId}.ok must be a boolean`);
      }
      if (status.auto_pull_expired !== undefined && typeof status.auto_pull_expired !== "boolean") {
        throw new Error(
          `Invalid status response: runtime.source_status.standard.${sourceId}.auto_pull_expired must be a boolean`,
        );
      }
    }
  }

  return {
    last_refresh_at: nullableString(payload.last_refresh_at, "runtime.last_refresh_at"),
    last_error: nullableString(payload.last_error, "runtime.last_error"),
    source_status: sourceStatus,
  };
}

function countStandardStatuses(
  runtime: HubRuntime,
  predicate: (status: Record<string, unknown>) => boolean,
): number {
  const standard = runtime.source_status.standard;
  if (standard === undefined) {
    return 0;
  }
  return Object.values(requiredRecord(standard, "runtime.source_status.standard"))
    .map((status, index) => requiredRecord(status, `runtime.source_status.standard[${index}]`))
    .filter(predicate).length;
}

function parseProxyBridgeStatus(raw: unknown): ProxyBridgeStatus {
  const payload = requiredRecord(raw, "egress.proxy_bridge");
  return {
    ...payload,
    code: requiredString(payload.code, "egress.proxy_bridge.code"),
    severity: requiredString(payload.severity, "egress.proxy_bridge.severity"),
    summary: requiredString(payload.summary, "egress.proxy_bridge.summary"),
    meaning: requiredString(payload.meaning, "egress.proxy_bridge.meaning"),
    repair_hint: requiredString(payload.repair_hint, "egress.proxy_bridge.repair_hint"),
    last_error: requiredString(payload.last_error, "egress.proxy_bridge.last_error"),
    actions: requiredStringArray(payload.actions, "egress.proxy_bridge.actions"),
    required: requiredBoolean(payload.required, "egress.proxy_bridge.required"),
  };
}

export function parseOverlayStatus(raw: unknown, path = "overlay_status"): OverlayStatus {
  const payload = requiredRecord(raw, path);
  return {
    available: requiredBoolean(payload.available, `${path}.available`),
    reason_code: requiredString(payload.reason_code, `${path}.reason_code`),
    reason: requiredString(payload.reason, `${path}.reason`),
    renderable_process_rule_count: requiredNumber(
      payload.renderable_process_rule_count,
      `${path}.renderable_process_rule_count`,
    ),
    renderable_external_proxy_program_count: requiredNumber(
      payload.renderable_external_proxy_program_count,
      `${path}.renderable_external_proxy_program_count`,
    ),
  };
}

export function parseSystemStatusResponse(raw: unknown): SystemStatus {
  const payload = requiredRecord(raw, "response");
  if (payload.ok !== true) {
    throw new Error("Invalid status response: ok must be true");
  }

  const hubRuntime = parseHubRuntime(payload.runtime);
  const sourceSummary: SourceSummary = {
    gorelay_count: requiredNumber(payload.gorelay_source_count, "gorelay_source_count"),
    standard_count: requiredNumber(payload.standard_source_count, "standard_source_count"),
    standard_expired: countStandardStatuses(
      hubRuntime,
      (status) => status.auto_pull_expired === true,
    ),
    standard_failed: countStandardStatuses(hubRuntime, (status) => status.ok === false),
  };
  const egressPayload = requiredRecord(payload.egress, "egress");
  const egress: EgressStatus = {
    ...egressPayload,
    proxy_bridge: parseProxyBridgeStatus(egressPayload.proxy_bridge),
  };

  return {
    hub_runtime: hubRuntime,
    source_summary: sourceSummary,
    egress,
  };
}
