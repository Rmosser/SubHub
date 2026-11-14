import { isRecord } from "@/api/validators/shared";

interface TypedSetting { key: string; type: string }

export function settingError(type: string, value: unknown): string | undefined {
  if (value === undefined || value === null) return;
  if (type === "dict" && !isRecord(value)) return "validation.dict";
  if (type === "int" && (typeof value !== "number" || !Number.isSafeInteger(value))) return "validation.integer";
}

export function settingsErrors(schema: TypedSetting[], values: Record<string, unknown>): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of schema) {
    const error = settingError(field.type, values[field.key]);
    if (error) errors[field.key] = error;
  }
  return errors;
}

export function integerDraftValue(text: string): number | string {
  const value = Number(text);
  return text.trim() && Number.isSafeInteger(value) ? value : text;
}
