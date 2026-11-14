import { isRecord } from "./shared";

export function apiErrorDetail(raw: unknown, status: number): string {
  const fallback = `HTTP ${status}`;
  if (!isRecord(raw)) return fallback;
  for (const value of [raw.detail, raw.message]) {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (Array.isArray(value)) {
      const messages = value.flatMap((item) => {
        if (!isRecord(item) || typeof item.msg !== "string") return [];
        const path = Array.isArray(item.loc) ? item.loc.join(".") : "";
        return [path ? `${path}: ${item.msg}` : item.msg];
      });
      if (messages.length) return messages.join("; ");
    }
  }
  if (Array.isArray(raw.errors)) {
    const errors = raw.errors.filter((error): error is string => typeof error === "string" && Boolean(error.trim()));
    if (errors.length) return [...new Set(errors)].join("; ");
  }
  if (isRecord(raw.result)) {
    if (typeof raw.result.error === "string" && raw.result.error.trim()) return raw.result.error.trim();
    if (typeof raw.result.failed_count === "number" && raw.result.failed_count > 0) {
      return `${fallback}: ${raw.result.failed_count} rule categories failed to refresh`;
    }
  }
  if (isRecord(raw.runtime) && typeof raw.runtime.last_error === "string" && raw.runtime.last_error.trim()) {
    return raw.runtime.last_error.trim();
  }
  return fallback;
}
