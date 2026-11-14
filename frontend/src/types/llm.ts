export type LlmWorkflowId = "directness" | "routing" | "grouping";

export interface LlmWorkflowPoolSummary {
  pool_id: string;
  display_name: string;
  node_count: number;
}

export interface LlmWorkflowTargetOption {
  contract_id: string;
  display_name: string;
  description: string;
  strategy_type: string;
  primary_pools: LlmWorkflowPoolSummary[];
  fallback_pools: LlmWorkflowPoolSummary[];
}

export interface LlmWorkflowGroup {
  group_name: string;
  mode: string;
  description: string;
}

export interface LlmWorkflowExport {
  ok: boolean;
  workflow: LlmWorkflowId;
  schema: string;
  generated_at: string;
  snapshot_fingerprint: string;
  template: string;
  intent_override: string;
  prompt: string;
  items: Record<string, unknown>[];
  target_options: LlmWorkflowTargetOption[];
  groups: LlmWorkflowGroup[];
}

export interface LlmWorkflowInvalidItem {
  name: string;
  reason: string;
}

export interface LlmWorkflowChange {
  change_id: string;
  type: string;
  name: string;
  group_name: string;
  from_directness: string;
  to_directness: string;
  confidence: string;
  reason: string;
  from_contract_id: string;
  to_contract_id: string;
  from_display_name: string;
  to_display_name: string;
  current_effective_directness: string;
  from_group: string;
  to_group: string;
  routing_side_effect: boolean;
  from_mode: string;
  to_mode: string;
  from_description: string;
  to_description: string;
  mode: string;
  action: "keep" | "discard";
}

export interface LlmWorkflowPreview {
  ok: boolean;
  workflow: LlmWorkflowId;
  changes: LlmWorkflowChange[];
  invalid_items: LlmWorkflowInvalidItem[];
  skipped_locked: string[];
  skipped_unchanged: string[];
}

export interface LlmWorkflowApplyResponse extends LlmWorkflowPreview {
  applied: number;
  applied_change_ids: string[];
}

export interface LlmExportSettings {
  rules_preferences: string;
  pins_preferences: string;
  directness_preferences: string;
}

export interface LogRoutingUploadedFile {
  id: string;
  filename: string;
  detected_client: string;
  uploaded_at: string;
  evidence_count: number;
  fallback_count: number;
  candidate_count: number;
}

export interface LogRoutingEvidenceRow {
  source_client: string;
  source_file: string;
  occurred_at: string;
  host: string;
  root_domain: string;
  fallback_reason: string;
  matched_rule: string;
  matched_policy: string;
  process_name: string;
  app_name: string;
  raw_excerpt: string;
}

export interface LogRoutingCandidate {
  root_domain: string;
  hosts: string[];
  hit_count: number;
  fallback_hits: number;
  observed_rules: string[];
  observed_policies: string[];
  sample_evidence: LogRoutingEvidenceRow[];
  existing_category: string;
  existing_route: string;
  existing_route_display_name: string;
  current_match_status: string;
  suggested_category_name: string;
}

export interface LogRoutingSessionInfo {
  session_id: string;
  created_at: string;
  updated_at: string;
  file_count: number;
  evidence_count: number;
}

export interface LogRoutingRouteOption {
  id: string;
  display_name: string;
  strategy_type: string;
  primary_pools: string[];
  fallback_pools: string[];
}

export interface LogRoutingExport {
  ok: boolean;
  workflow: "log-routing";
  schema: string;
  generated_at: string;
  session_id: string;
  snapshot_id: string;
  template: string;
  intent_override: string;
  prompt: string;
  allowed_actions: string[];
  available_routes: LogRoutingRouteOption[];
  files: LogRoutingUploadedFile[];
  candidates: LogRoutingCandidate[];
}

export interface LogRoutingCandidatesResponse {
  ok: boolean;
  session_id: string;
  files: LogRoutingUploadedFile[];
  evidence_count: number;
  candidate_count: number;
  candidates: LogRoutingCandidate[];
}

export interface LogRoutingPreviewChange {
  id: string;
  type: string;
  status: string;
  summary: string;
}

export interface LogRoutingPreviewNotice {
  id?: string;
  type?: string;
  code: string;
  message: string;
}

export interface LogRoutingPreview {
  ok: boolean;
  workflow: "log-routing";
  session_id: string;
  snapshot_id: string;
  schema: string;
  current_revision: string;
  changes: LogRoutingPreviewChange[];
  warnings: LogRoutingPreviewNotice[];
  blockers: LogRoutingPreviewNotice[];
}

export interface LogRoutingApplyResponse extends LogRoutingPreview {
  revision_before: string;
  revision_after: string;
  applied_count: number;
  noop_count: number;
}
