import type { ApiListResponse, ExternalProxyProgramTemplate, ProcessRuleTemplate } from "@/types";
import { isRecord } from "./shared";

function requiredString(raw: Record<string, unknown>, field: string): string {
  if (typeof raw[field] !== "string") throw new Error(`Invalid advanced response: ${field} must be a string`);
  return raw[field];
}

function requiredNumber(raw: Record<string, unknown>, field: string): number {
  const value = raw[field];
  if (typeof value !== "number" || !Number.isInteger(value)) throw new Error(`Invalid advanced response: ${field} must be an integer`);
  return value;
}

function bindingFields(raw: Record<string, unknown>) {
  if (typeof raw.enabled !== "boolean") throw new Error("Invalid advanced response: enabled must be a boolean");
  if (raw.needs_rebind !== undefined && typeof raw.needs_rebind !== "boolean") throw new Error("Invalid advanced response: needs_rebind must be a boolean");
  if (raw.migration_warning !== undefined && typeof raw.migration_warning !== "string") throw new Error("Invalid advanced response: migration_warning must be a string");
  return {
    id: requiredString(raw, "id"),
    contract_id: requiredString(raw, "contract_id"),
    contract_display_name: requiredString(raw, "contract_display_name"),
    business_group: requiredString(raw, "business_group"),
    sort_order: requiredNumber(raw, "sort_order"),
    enabled: raw.enabled,
    needs_rebind: raw.needs_rebind === true,
    migration_warning: typeof raw.migration_warning === "string" ? raw.migration_warning : "",
  };
}

function parseList<T>(raw: unknown, parseItem: (raw: Record<string, unknown>) => T): ApiListResponse<T> {
  if (!isRecord(raw) || raw.ok !== true || !Array.isArray(raw.items)) throw new Error("Invalid advanced response: expected ok and items array");
  return {
    items: raw.items.map((item) => {
      if (!isRecord(item)) throw new Error("Invalid advanced response: item must be an object");
      return parseItem(item);
    }),
  };
}

export function parseProcessRuleListResponse(raw: unknown): ApiListResponse<ProcessRuleTemplate> {
  return parseList(raw, (item) => ({ ...bindingFields(item), match_type: requiredString(item, "match_type"), value: requiredString(item, "value") }));
}

export function parseExternalProxyProgramListResponse(raw: unknown): ApiListResponse<ExternalProxyProgramTemplate> {
  return parseList(raw, (item) => {
    if (!Array.isArray(item.args) || item.args.some((value) => typeof value !== "string")) throw new Error("Invalid advanced response: args must be a string array");
    return { ...bindingFields(item), program_path: requiredString(item, "program_path"), name: requiredString(item, "name"), local_port: requiredNumber(item, "local_port"), args: item.args };
  });
}
