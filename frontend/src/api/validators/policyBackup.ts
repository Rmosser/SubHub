import type {
  PolicyBackupApplyResult,
  PolicyBackupSnapshot,
  PolicyBackupStatus,
  PolicyBackupSyncResult,
  PolicyRestorePreview,
  PolicyRestorePreviewSection,
} from "@/types";
import { isRecord } from "./shared";
import { anyRecord, array, bool, itemResponse, num, object, optional, record, response, str } from "./schema";

function section(raw: unknown): PolicyRestorePreviewSection {
  if (!isRecord(raw) || typeof raw.name !== "string") throw new Error("Invalid restore preview section");
  const readItems = (key: string): string[] => {
    const value = raw[key];
    if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) throw new Error(`Invalid restore preview: ${key} must be a string array`);
    return value;
  };
  const readCount = (key: string): number => {
    const value = raw[key];
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0) throw new Error(`Invalid restore preview: ${key} must be a count`);
    return value;
  };
  return {
    name: raw.name,
    added: readItems("added"), removed: readItems("removed"), changed: readItems("changed"),
    added_count: readCount("added_count"), removed_count: readCount("removed_count"), changed_count: readCount("changed_count"),
  };
}

export function parsePolicyRestorePreview(raw: unknown): PolicyRestorePreview {
  if (!isRecord(raw) || raw.ok !== true || typeof raw.ref !== "string" || typeof raw.source_digest !== "string"
    || typeof raw.snapshot_digest !== "string" || !/^[a-f0-9]{64}$/.test(raw.snapshot_digest)
    || typeof raw.changed !== "boolean" || !Array.isArray(raw.sections)) {
    throw new Error("Invalid restore preview: a verified snapshot checksum is required");
  }
  return {
    ok: true, ref: raw.ref, source_digest: raw.source_digest, snapshot_digest: raw.snapshot_digest,
    changed: raw.changed, sections: raw.sections.map(section),
  };
}

const backupStatus = object<PolicyBackupStatus>({
  enabled: bool,
  configured: bool,
  repo_url: str,
  branch: str,
  subdir: str,
  dirty: bool,
  syncing: bool,
  last_result: str,
  last_sync_at: str,
  last_commit_sha: str,
  last_error: str,
});

export const parsePolicyBackupStatusItem = itemResponse(backupStatus);

export const parsePolicyBackupSnapshot = response(
  object<PolicyBackupSnapshot>({
    manifest: anyRecord,
    global: object<PolicyBackupSnapshot["global"]>({ custom_rules: array(anyRecord) }),
    categories: object<PolicyBackupSnapshot["categories"]>({ manual_categories: array(anyRecord) }),
    scenarios: record(anyRecord),
  }),
);

export const parsePolicyBackupSyncResult = response(
  object<PolicyBackupSyncResult>({
    ok: bool,
    busy: optional(bool),
    changed: optional(bool),
    commit_sha: optional(str),
    reasons: optional(array(str)),
    error: optional(str),
    dirty: optional(bool),
  }),
);

export function parsePolicyBackupApplyResult(raw: unknown): PolicyBackupApplyResult {
  const payload = response(
    object<Omit<PolicyBackupApplyResult, "preview"> & { preview: unknown }>({
      ok: bool,
      preview: (value) => value,
      applied: object<PolicyBackupApplyResult["applied"]>({
        manual_categories: num,
        global_custom_rules: num,
        scenario_count: num,
      }),
    }),
  )(raw);
  return { ...payload, preview: parsePolicyRestorePreview(payload.preview) };
}
