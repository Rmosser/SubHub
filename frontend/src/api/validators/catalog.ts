import type {
  ApiListResponse,
  CategoryCustomRuleItem,
  CategoryCustomRulesData,
  CategoryPreviewData,
  CategoryPreviewRule,
  CustomRule,
  PinData,
  BusinessGroup,
  RuleCategory,
  RuleCategoryDirectnessReview,
  RuleMetadata,
  ServiceCatalogEntry,
} from "@/types";
import { isRecord } from "./shared";
import { array, bool, listResponse, literal, num, object, optional, response, str } from "./schema";

function requiredRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid catalog response: ${path} must be an object`);
  }
  return value;
}

function requiredString(value: unknown, path: string): string {
  if (typeof value !== "string") {
    throw new Error(`Invalid catalog response: ${path} must be a string`);
  }
  return value;
}

function requiredNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Invalid catalog response: ${path} must be a number`);
  }
  return value;
}

function requiredStringArray(value: unknown, path: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`Invalid catalog response: ${path} must be an array of strings`);
  }
  return value;
}

function parsePinGroup(value: unknown, pinnedByGroup: Map<string, string[]>): BusinessGroup {
  const item = requiredRecord(value, "groups[]");
  const name = requiredString(item.group_name, "groups[].group_name").trim();
  if (!name) {
    throw new Error("Invalid catalog response: groups[].group_name must not be empty");
  }
  const mode = requiredString(item.mode, `groups[${name}].mode`);
  if (mode !== "standard" && mode !== "ad_block") {
    throw new Error(`Invalid catalog response: groups[${name}].mode is invalid`);
  }
  const categoryNames = item.category_names === undefined
    ? pinnedByGroup.get(name) ?? []
    : requiredStringArray(item.category_names, `groups[${name}].category_names`);
  return {
    name,
    sort_order: requiredNumber(item.sort_order, `groups[${name}].sort_order`),
    category_names: categoryNames,
    pool_names: item.pool_names === undefined
      ? []
      : requiredStringArray(item.pool_names, `groups[${name}].pool_names`),
    mode,
    created_by_system: item.created_by_system === true,
  };
}

function parseBusinessGroup(value: unknown): BusinessGroup {
  const item = requiredRecord(value, "items[]");
  const name = requiredString(item.name, "items[].name").trim();
  if (!name) {
    throw new Error("Invalid catalog response: items[].name must not be empty");
  }
  const mode = requiredString(item.mode, `items[${name}].mode`);
  if (mode !== "standard" && mode !== "ad_block") {
    throw new Error(`Invalid catalog response: items[${name}].mode is invalid`);
  }
  return {
    name,
    sort_order: requiredNumber(item.sort_order, `items[${name}].sort_order`),
    category_names: requiredStringArray(item.category_names, `items[${name}].category_names`),
    pool_names: requiredStringArray(item.pool_names, `items[${name}].pool_names`),
    mode,
    created_by_system: item.created_by_system === true,
  };
}

function parsePinnedCategoryName(value: unknown, index: number): string {
  const item = requiredRecord(value, `pinned[${index}]`);
  const name = requiredString(item.category_name, `pinned[${index}].category_name`).trim();
  if (!name) {
    throw new Error(`Invalid catalog response: pinned[${index}].category_name must not be empty`);
  }
  return name;
}

export function parsePinData(raw: unknown): PinData {
  const payload = requiredRecord(raw, "response");
  if (payload.ok !== true) {
    throw new Error("Invalid catalog response: ok must be true");
  }
  if (!Array.isArray(payload.pinned)) {
    throw new Error("Invalid catalog response: pinned must be an array");
  }
  if (!Array.isArray(payload.groups)) {
    throw new Error("Invalid catalog response: groups must be an array");
  }
  const pinnedItems = payload.pinned;
  const pinnedByGroup = new Map<string, string[]>();

  pinnedItems.forEach((entry, index) => {
    const item = requiredRecord(entry, `pinned[${index}]`);
    const groupName = requiredString(item.pin_group, `pinned[${index}].pin_group`).trim();
    const categoryName = parsePinnedCategoryName(item, index);
    if (!groupName) {
      throw new Error(`Invalid catalog response: pinned[${index}].pin_group must not be empty`);
    }
    const existing = pinnedByGroup.get(groupName) ?? [];
    existing.push(categoryName);
    pinnedByGroup.set(groupName, existing);
  });

  const groups = payload.groups.map((item) => parsePinGroup(item, pinnedByGroup));

  return {
    groups,
    pinned: pinnedItems.map(parsePinnedCategoryName),
  };
}

export function parseBusinessGroupListResponse(raw: unknown): ApiListResponse<BusinessGroup> {
  const payload = requiredRecord(raw, "response");
  if (payload.ok !== true) {
    throw new Error("Invalid catalog response: ok must be true");
  }
  if (!Array.isArray(payload.items)) {
    throw new Error("Invalid catalog response: items must be an array");
  }
  return { items: payload.items.map(parseBusinessGroup) };
}

function parseCategoryPreviewRule(raw: unknown): CategoryPreviewRule {
  if (typeof raw === "string") {
    const parts = raw.split(",");
    const [type = "", value = "", target = ""] = parts;
    return {
      type: type.trim(),
      value: value.trim(),
      target: target.trim(),
    };
  }
  const item = requiredRecord(raw, "items[]");
  return {
    type: requiredString(item.rule_type, "items[].rule_type"),
    value: requiredString(item.value, "items[].value"),
    target: requiredString(item.target, "items[].target"),
  };
}

export function parseCategoryPreviewData(raw: unknown): CategoryPreviewData {
  const payload = requiredRecord(raw, "response");
  if (payload.ok !== true) {
    throw new Error("Invalid catalog response: ok must be true");
  }
  if (!Array.isArray(payload.items)) {
    throw new Error("Invalid catalog response: items must be an array");
  }
  return {
    count: requiredNumber(payload.total, "total"),
    rules: payload.items.map(parseCategoryPreviewRule),
  };
}

const ruleCategory = object<RuleCategory>({
  name: str,
  assigned_group: str,
  stored_contract_id: optional(str),
  rule_count: num,
  rule_source: str,
  category_type: literal("auto", "manual"),
  custom_rule_count: num,
  updated_at: str,
  locked: bool,
  system_directness: literal("DIRECT", "PROXY"),
  system_default_group: str,
  system_default_locked: bool,
  override_group: str,
  override_active: bool,
  directness_override: str,
  lock_source: str,
  pin_group: optional(str),
  pin_sort_order: optional(num),
  effective_contract_id: optional(str),
  effective_contract_display_name: optional(str),
  effective_contract_source: optional(str),
});

const serviceCatalogEntry = object<ServiceCatalogEntry>({
  category_name: str,
  catalog_group: str,
  contract_id: str,
  contract_display_name: str,
  sort_order: num,
  source: str,
  updated_at: str,
  pin_group: str,
});

const directnessReview = object<RuleCategoryDirectnessReview>({
  id: str,
  category_name: str,
  proposed_decision: str,
  confidence: str,
  reason: str,
  source: str,
  status: literal("pending", "applied", "dismissed"),
  created_at: str,
  decided_at: str,
});

export const customRule = object<CustomRule>({
  id: str,
  rule_type: str,
  value: str,
  target_contract_id: str,
  target_group: str,
  target_contract_display_name: str,
  category_name: str,
  created_at: str,
});

const categoryCustomRuleItem = object<CategoryCustomRuleItem>({
  id: str,
  rule_type: str,
  value: str,
  category_name: str,
  created_at: str,
  effective_contract_id: str,
  effective_contract_display_name: str,
  effective_contract_source: str,
  active: bool,
});

type CategoryCustomRulesPayload = {
  items: CategoryCustomRuleItem[];
  category: { effective_contract_id: string; effective_contract_display_name: string; effective_contract_source: string; active: boolean };
};

const categoryCustomRulesPayload = response(
  object<CategoryCustomRulesPayload>({
    items: array(categoryCustomRuleItem),
    category: object<CategoryCustomRulesPayload["category"]>({
      effective_contract_id: str,
      effective_contract_display_name: str,
      effective_contract_source: str,
      active: bool,
    }),
  }),
);

export const parseRuleCategoryList = listResponse(ruleCategory);
export const parseServiceCatalogList = listResponse(serviceCatalogEntry);
export const parseDirectnessReviewList = listResponse(directnessReview);
export const parseCustomRuleList = listResponse(customRule);
export const parseRuleMetadata = response(object<RuleMetadata>({ category_rule_types: array(str) }));

export function parseCategoryCustomRules(raw: unknown): CategoryCustomRulesData {
  const { items, category } = categoryCustomRulesPayload(raw);
  return {
    effectiveContractId: category.effective_contract_id.trim(),
    effectiveContractDisplayName: category.effective_contract_display_name.trim(),
    effectiveContractSource: category.effective_contract_source.trim(),
    active: category.active,
    items,
  };
}
