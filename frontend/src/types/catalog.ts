export interface RuleCategory {
  name: string;
  assigned_group: string;
  stored_contract_id?: string;
  rule_count: number;
  rule_source: string;
  category_type: "auto" | "manual";
  custom_rule_count: number;
  updated_at: string;
  locked: boolean;
  system_directness: "DIRECT" | "PROXY";
  system_default_group: string;
  system_default_locked: boolean;
  override_group: string;
  override_active: boolean;
  directness_override: string;
  lock_source: string;
  pin_group?: string;
  pin_sort_order?: number;
  effective_contract_id?: string;
  effective_contract_display_name?: string;
  effective_contract_source?: string;
}

export interface ServiceCatalogEntry {
  category_name: string;
  catalog_group: string;
  contract_id: string;
  contract_display_name: string;
  sort_order: number;
  source: string;
  updated_at: string;
  pin_group: string;
}

export interface BusinessGroup {
  name: string;
  sort_order: number;
  category_names: string[];
  pool_names: string[];
  mode: "standard" | "ad_block";
  created_by_system: boolean;
}

export interface PinData {
  groups: BusinessGroup[];
  pinned: string[];
}

export interface CategoryPreviewRule {
  type: string;
  value: string;
  target: string;
}

export interface CategoryPreviewData {
  rules: CategoryPreviewRule[];
  count: number;
}

export interface CategoryCustomRulesData {
  effectiveContractId: string;
  effectiveContractDisplayName: string;
  effectiveContractSource: string;
  active: boolean;
  items: CategoryCustomRuleItem[];
}

export interface RuleCategoryDirectnessReview {
  id: string;
  category_name: string;
  proposed_decision: string;
  confidence: string;
  reason: string;
  source: string;
  status: "pending" | "applied" | "dismissed";
  created_at: string;
  decided_at: string;
}

export interface CustomRule {
  id: string;
  rule_type: string;
  value: string;
  target_contract_id: string;
  target_group: string;
  target_contract_display_name: string;
  category_name: string;
  created_at: string;
}

export interface CategoryCustomRuleItem {
  id: string;
  rule_type: string;
  value: string;
  category_name: string;
  created_at: string;
  effective_contract_id: string;
  effective_contract_display_name: string;
  effective_contract_source: string;
  active: boolean;
}

export interface RuleMetadata {
  category_rule_types: string[];
}
