export type ContractRoutingAction = "proxy" | "direct" | "reject";

export interface RouteContract {
  id: string;
  display_name: string;
  description: string;
  llm_routing_intent: string;
  routing_action: ContractRoutingAction;
  can_bind_standard_source?: boolean;
  strategy_type: "strict" | "failover" | "load-balance";
  primary_pools: string[];
  fallback_pools: string[];
  primary_pool_display_names: string[];
  fallback_pool_display_names: string[];
  failure_action: "degrade" | "direct" | "interrupt";
  editable: boolean;
  enabled: boolean;
  is_default: boolean;
  sort_order: number;
  is_system: boolean;
  scope: "system" | "global" | "scenario";
  owner_scenario_id: string;
  updated_at: string;
}

export interface ContractReference {
  kind: string;
  count: number;
  scenario_id: string | null;
}

export interface ContractReferencesResponse {
  references: ContractReference[];
  is_default: boolean;
  can_delete: boolean;
}

export interface ContractMutationBody {
  display_name: string;
  description: string;
  llm_routing_intent: string;
  routing_action?: ContractRoutingAction;
  enabled: boolean;
  sort_order: number;
  is_default: boolean;
  strategy_type?: "strict" | "failover" | "load-balance";
  primary_pools?: string[];
  fallback_pools?: string[];
  failure_action?: "degrade" | "direct" | "interrupt";
}

export type ContractCreatePayload = ContractMutationBody;

export type ContractUpdatePayload = ContractMutationBody & {
  id: string;
};

export type ContractMutationPayload = ContractCreatePayload | ContractUpdatePayload;
