import type { ContractReference, ContractReferencesResponse, RouteContract } from "@/types";
import { array, bool, listResponse, literal, nullable, num, object, optional, response, str } from "./schema";

const routeContract = object<RouteContract>({
  id: str,
  display_name: str,
  description: str,
  llm_routing_intent: str,
  routing_action: literal("proxy", "direct", "reject"),
  can_bind_standard_source: optional(bool),
  strategy_type: literal("strict", "failover", "load-balance"),
  primary_pools: array(str),
  fallback_pools: array(str),
  primary_pool_display_names: array(str),
  fallback_pool_display_names: array(str),
  failure_action: literal("degrade", "direct", "interrupt"),
  editable: bool,
  enabled: bool,
  is_default: bool,
  sort_order: num,
  is_system: bool,
  scope: literal("system", "global", "scenario"),
  owner_scenario_id: str,
  updated_at: str,
});

const contractReference = object<ContractReference>({ kind: str, count: num, scenario_id: nullable(str) });

export const parseRouteContractList = listResponse(routeContract);
export const parseContractReferences = response(
  object<ContractReferencesResponse>({ references: array(contractReference), is_default: bool, can_delete: bool }),
);
