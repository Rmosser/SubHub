import type { ApiItemResponse, ApiListResponse } from "@/types";

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

export function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function asNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return fallback;
}

export function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

export class ApiContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiContractError";
  }
}

export function parseApiItemResponse<T>(
  raw: unknown,
  parseItem: (value: unknown) => T,
): ApiItemResponse<T> {
  const payload = asRecord(raw);
  const item = payload.item;
  return {
    item: item == null ? null : parseItem(item),
  };
}

export function parseRequiredApiItemResponse<T>(
  raw: unknown,
  parseItem: (value: unknown) => T,
): T {
  const { item } = parseApiItemResponse(raw, parseItem);
  if (item === null) {
    throw new ApiContractError("API response is missing required item");
  }
  return item;
}

export function parseApiListResponse<T>(
  raw: unknown,
  parseItem: (value: unknown) => T,
): ApiListResponse<T> {
  const payload = asRecord(raw);
  return {
    items: Array.isArray(payload.items) ? payload.items.map(parseItem) : [],
  };
}
