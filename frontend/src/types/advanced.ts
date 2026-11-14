export interface ProcessRuleTemplate {
  id: string;
  contract_id: string;
  contract_display_name: string;
  business_group: string;
  match_type: string;
  value: string;
  sort_order: number;
  enabled: boolean;
  needs_rebind: boolean;
  migration_warning: string;
}

export interface ExternalProxyProgramTemplate {
  id: string;
  contract_id: string;
  contract_display_name: string;
  business_group: string;
  program_path: string;
  args: string[];
  local_port: number;
  name: string;
  sort_order: number;
  enabled: boolean;
  needs_rebind: boolean;
  migration_warning: string;
}
