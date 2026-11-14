import type { ApiListResponse, PoolStatus } from "@/types";
import { isRecord } from "./shared";

function requiredRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid pools response: ${path} must be an object`);
  }
  return value;
}

function requiredString(value: unknown, path: string): string {
  if (typeof value !== "string") {
    throw new Error(`Invalid pools response: ${path} must be a string`);
  }
  return value;
}

function requiredBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`Invalid pools response: ${path} must be a boolean`);
  }
  return value;
}

function requiredNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Invalid pools response: ${path} must be a number`);
  }
  return value;
}

function parsePoolStatus(raw: unknown, index: number): PoolStatus {
  const payload = requiredRecord(raw, `items[${index}]`);
  const rawSources = requiredRecord(payload.sources, `items[${index}].sources`);
  const sources = Object.fromEntries(
    Object.entries(rawSources).map(([sourceId, count]) => [
      sourceId,
      requiredNumber(count, `items[${index}].sources.${sourceId}`),
    ]),
  );

  return {
    id: requiredString(payload.id, `items[${index}].id`),
    display_name: requiredString(payload.display_name, `items[${index}].display_name`),
    node_count: requiredNumber(payload.node_count, `items[${index}].node_count`),
    renderable_node_count: requiredNumber(
      payload.renderable_node_count,
      `items[${index}].renderable_node_count`,
    ),
    last_refresh_at: requiredString(payload.last_refresh_at, `items[${index}].last_refresh_at`),
    sources,
    pseudo: requiredBoolean(payload.pseudo, `items[${index}].pseudo`),
  };
}

export function parsePoolListResponse(raw: unknown): ApiListResponse<PoolStatus> {
  const payload = requiredRecord(raw, "response");
  if (payload.ok !== true) {
    throw new Error("Invalid pools response: ok must be true");
  }
  if (!Array.isArray(payload.items)) {
    throw new Error("Invalid pools response: items must be an array");
  }
  return {
    items: payload.items.map(parsePoolStatus),
  };
}
