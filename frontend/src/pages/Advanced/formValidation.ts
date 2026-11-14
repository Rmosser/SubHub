import type { ExternalProxyProgramTemplate, ProcessRuleTemplate } from "@/types";

export const PROCESS_RULE_TYPES = ["PROCESS-NAME", "PROCESS-NAME-REGEX", "PROCESS-PATH", "PROCESS-PATH-REGEX"] as const;

export interface RowValidationError {
  row: number;
  field: string;
  reason: "validation.required" | "validation.integer" | "validation.port" | "validation.choice";
}

export function validateProcessRules(items: ProcessRuleTemplate[]): RowValidationError | undefined {
  for (const [index, item] of items.entries()) {
    const row = index + 1;
    if (!PROCESS_RULE_TYPES.some((type) => type === item.match_type)) return { row, field: "match_type", reason: "validation.choice" };
    if (!item.value.trim()) return { row, field: "value", reason: "validation.required" };
    if (!item.contract_id) return { row, field: "contract_id", reason: "validation.required" };
    if (!Number.isInteger(item.sort_order)) return { row, field: "sort_order", reason: "validation.integer" };
  }
}

export function validateExternalProxyPrograms(items: ExternalProxyProgramTemplate[]): RowValidationError | undefined {
  for (const [index, item] of items.entries()) {
    const row = index + 1;
    if (!item.program_path.trim()) return { row, field: "program_path", reason: "validation.required" };
    if (!item.contract_id) return { row, field: "contract_id", reason: "validation.required" };
    if (!Number.isInteger(item.local_port) || item.local_port < 1 || item.local_port > 65535) return { row, field: "local_port", reason: "validation.port" };
    if (!Number.isInteger(item.sort_order)) return { row, field: "sort_order", reason: "validation.integer" };
  }
}
