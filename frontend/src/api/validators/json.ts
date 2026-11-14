import { isRecord } from "./shared";

export function parseJsonValue(source: string): unknown {
  return JSON.parse(source);
}

export function parseJsonObject(source: string): Record<string, unknown> {
  const value = parseJsonValue(source);
  if (!isRecord(value)) throw new Error("Expected a JSON object");
  return value;
}
