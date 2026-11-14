import type {
  LlmExportSettings,
  LlmWorkflowApplyResponse,
  LlmWorkflowChange,
  LlmWorkflowExport,
  LlmWorkflowGroup,
  LlmWorkflowId,
  LlmWorkflowInvalidItem,
  LlmWorkflowPoolSummary,
  LlmWorkflowPreview,
  LlmWorkflowTargetOption,
  LogRoutingApplyResponse,
  LogRoutingCandidate,
  LogRoutingCandidatesResponse,
  LogRoutingEvidenceRow,
  LogRoutingExport,
  LogRoutingPreview,
  LogRoutingPreviewChange,
  LogRoutingPreviewNotice,
  LogRoutingRouteOption,
  LogRoutingSessionInfo,
  LogRoutingUploadedFile,
} from "@/types";
import {
  ApiContractError,
  asBoolean,
  asNumber,
  asRecord,
  asString,
  asStringArray,
  parseApiItemResponse,
  parseRequiredApiItemResponse,
} from "./shared";

function asWorkflowId(value: unknown): LlmWorkflowId {
  const candidate = asString(value);
  if (candidate === "routing" || candidate === "grouping") {
    return candidate;
  }
  return "directness";
}

function parsePoolSummary(raw: unknown): LlmWorkflowPoolSummary {
  const payload = asRecord(raw);
  return {
    pool_id: asString(payload.pool_id),
    display_name: asString(payload.display_name),
    node_count: asNumber(payload.node_count),
  };
}

function parseTargetOption(raw: unknown): LlmWorkflowTargetOption {
  const payload = asRecord(raw);
  return {
    contract_id: asString(payload.contract_id),
    display_name: asString(payload.display_name),
    description: asString(payload.description),
    strategy_type: asString(payload.strategy_type),
    primary_pools: Array.isArray(payload.primary_pools) ? payload.primary_pools.map(parsePoolSummary) : [],
    fallback_pools: Array.isArray(payload.fallback_pools) ? payload.fallback_pools.map(parsePoolSummary) : [],
  };
}

function parseGroup(raw: unknown): LlmWorkflowGroup {
  const payload = asRecord(raw);
  return {
    group_name: asString(payload.group_name),
    mode: asString(payload.mode),
    description: asString(payload.description),
  };
}

function parseInvalidItem(raw: unknown): LlmWorkflowInvalidItem {
  const payload = asRecord(raw);
  return {
    name: asString(payload.name),
    reason: asString(payload.reason),
  };
}

function parseChange(raw: unknown): LlmWorkflowChange {
  const payload = asRecord(raw);
  return {
    change_id: asString(payload.change_id),
    type: asString(payload.type),
    name: asString(payload.name),
    group_name: asString(payload.group_name),
    from_directness: asString(payload.from_directness),
    to_directness: asString(payload.to_directness),
    confidence: asString(payload.confidence),
    reason: asString(payload.reason),
    from_contract_id: asString(payload.from_contract_id),
    to_contract_id: asString(payload.to_contract_id),
    from_display_name: asString(payload.from_display_name),
    to_display_name: asString(payload.to_display_name),
    current_effective_directness: asString(payload.current_effective_directness),
    from_group: asString(payload.from_group),
    to_group: asString(payload.to_group),
    routing_side_effect: typeof payload.routing_side_effect === "boolean" ? payload.routing_side_effect : false,
    from_mode: asString(payload.from_mode),
    to_mode: asString(payload.to_mode),
    from_description: asString(payload.from_description),
    to_description: asString(payload.to_description),
    mode: asString(payload.mode),
    action: "keep",
  };
}

function parseLogRoutingSessionInfo(raw: unknown): LogRoutingSessionInfo {
  const payload = asRecord(raw);
  const sessionId = asString(payload.session_id);
  const createdAt = asString(payload.created_at);
  const updatedAt = asString(payload.updated_at);
  const fileCount = asNumber(payload.file_count, Number.NaN);
  const evidenceCount = asNumber(payload.evidence_count, Number.NaN);
  if (
    !sessionId ||
    !createdAt ||
    !updatedAt ||
    !Number.isInteger(fileCount) ||
    fileCount < 0 ||
    !Number.isInteger(evidenceCount) ||
    evidenceCount < 0
  ) {
    throw new ApiContractError("API response contains an invalid log-routing session item");
  }
  return {
    session_id: sessionId,
    created_at: createdAt,
    updated_at: updatedAt,
    file_count: fileCount,
    evidence_count: evidenceCount,
  };
}

function parseLogRoutingFile(raw: unknown): LogRoutingUploadedFile {
  const payload = asRecord(raw);
  return {
    id: asString(payload.id),
    filename: asString(payload.filename),
    detected_client: asString(payload.detected_client),
    uploaded_at: asString(payload.uploaded_at),
    evidence_count: asNumber(payload.evidence_count),
    fallback_count: asNumber(payload.fallback_count),
    candidate_count: asNumber(payload.candidate_count),
  };
}

function parseLogRoutingEvidenceRow(raw: unknown): LogRoutingEvidenceRow {
  const payload = asRecord(raw);
  return {
    source_client: asString(payload.source_client),
    source_file: asString(payload.source_file),
    occurred_at: asString(payload.occurred_at),
    host: asString(payload.host),
    root_domain: asString(payload.root_domain),
    fallback_reason: asString(payload.fallback_reason),
    matched_rule: asString(payload.matched_rule),
    matched_policy: asString(payload.matched_policy),
    process_name: asString(payload.process_name),
    app_name: asString(payload.app_name),
    raw_excerpt: asString(payload.raw_excerpt),
  };
}

function parseLogRoutingCandidate(raw: unknown): LogRoutingCandidate {
  const payload = asRecord(raw);
  return {
    root_domain: asString(payload.root_domain),
    hosts: asStringArray(payload.hosts),
    hit_count: asNumber(payload.hit_count),
    fallback_hits: asNumber(payload.fallback_hits),
    observed_rules: asStringArray(payload.observed_rules),
    observed_policies: asStringArray(payload.observed_policies),
    sample_evidence: Array.isArray(payload.sample_evidence)
      ? payload.sample_evidence.map(parseLogRoutingEvidenceRow)
      : [],
    existing_category: asString(payload.existing_category),
    existing_route: asString(payload.existing_route),
    existing_route_display_name: asString(payload.existing_route_display_name),
    current_match_status: asString(payload.current_match_status),
    suggested_category_name: asString(payload.suggested_category_name),
  };
}

function parseLogRoutingRoute(raw: unknown): LogRoutingRouteOption {
  const payload = asRecord(raw);
  return {
    id: asString(payload.id),
    display_name: asString(payload.display_name),
    strategy_type: asString(payload.strategy_type),
    primary_pools: asStringArray(payload.primary_pools),
    fallback_pools: asStringArray(payload.fallback_pools),
  };
}

function parseLogRoutingPreviewChange(raw: unknown): LogRoutingPreviewChange {
  const payload = asRecord(raw);
  return {
    id: asString(payload.id),
    type: asString(payload.type),
    status: asString(payload.status),
    summary: asString(payload.summary),
  };
}

function parseLogRoutingPreviewNotice(raw: unknown): LogRoutingPreviewNotice {
  const payload = asRecord(raw);
  return {
    id: payload.id ? asString(payload.id) : undefined,
    type: payload.type ? asString(payload.type) : undefined,
    code: asString(payload.code),
    message: asString(payload.message),
  };
}

export function parseLlmExportSettingsResponse(raw: unknown): LlmExportSettings | null {
  return parseApiItemResponse(raw, (item) => {
    const payload = asRecord(item);
    return {
      rules_preferences: asString(payload.rules_preferences),
      pins_preferences: asString(payload.pins_preferences),
      directness_preferences: asString(payload.directness_preferences),
    };
  }).item;
}

export function parseLlmWorkflowExportResponse(raw: unknown): LlmWorkflowExport {
  const payload = asRecord(raw);
  return {
    ok: asBoolean(payload.ok),
    workflow: asWorkflowId(payload.workflow),
    schema: asString(payload.schema),
    generated_at: asString(payload.generated_at),
    snapshot_fingerprint: asString(payload.snapshot_fingerprint),
    template: asString(payload.template),
    intent_override: asString(payload.intent_override),
    prompt: asString(payload.prompt),
    items: Array.isArray(payload.items) ? payload.items.map((item) => asRecord(item)) : [],
    target_options: Array.isArray(payload.target_options) ? payload.target_options.map(parseTargetOption) : [],
    groups: Array.isArray(payload.groups) ? payload.groups.map(parseGroup) : [],
  };
}

export function parseLlmWorkflowPreviewResponse(raw: unknown): LlmWorkflowPreview {
  const payload = asRecord(raw);
  return {
    ok: asBoolean(payload.ok),
    workflow: asWorkflowId(payload.workflow),
    changes: Array.isArray(payload.changes) ? payload.changes.map(parseChange) : [],
    invalid_items: Array.isArray(payload.invalid_items) ? payload.invalid_items.map(parseInvalidItem) : [],
    skipped_locked: asStringArray(payload.skipped_locked),
    skipped_unchanged: asStringArray(payload.skipped_unchanged),
  };
}

export function parseLlmWorkflowApplyResponse(raw: unknown): LlmWorkflowApplyResponse {
  const preview = parseLlmWorkflowPreviewResponse(raw);
  const payload = asRecord(raw);
  return {
    ...preview,
    applied: asNumber(payload.applied),
    applied_change_ids: asStringArray(payload.applied_change_ids),
  };
}

export function parseLogRoutingSessionResponse(raw: unknown): LogRoutingSessionInfo {
  return parseRequiredApiItemResponse(raw, parseLogRoutingSessionInfo);
}

export function parseLogRoutingCandidatesResponse(raw: unknown): LogRoutingCandidatesResponse {
  const payload = asRecord(raw);
  return {
    ok: asBoolean(payload.ok),
    session_id: asString(payload.session_id),
    files: Array.isArray(payload.files) ? payload.files.map(parseLogRoutingFile) : [],
    evidence_count: asNumber(payload.evidence_count),
    candidate_count: asNumber(payload.candidate_count),
    candidates: Array.isArray(payload.candidates) ? payload.candidates.map(parseLogRoutingCandidate) : [],
  };
}

export function parseLogRoutingExportResponse(raw: unknown): LogRoutingExport {
  const payload = asRecord(raw);
  return {
    ok: asBoolean(payload.ok),
    workflow: "log-routing",
    schema: asString(payload.schema),
    generated_at: asString(payload.generated_at),
    session_id: asString(payload.session_id),
    snapshot_id: asString(payload.snapshot_id),
    template: asString(payload.template),
    intent_override: asString(payload.intent_override),
    prompt: asString(payload.prompt),
    allowed_actions: asStringArray(payload.allowed_actions),
    available_routes: Array.isArray(payload.available_routes) ? payload.available_routes.map(parseLogRoutingRoute) : [],
    files: Array.isArray(payload.files) ? payload.files.map(parseLogRoutingFile) : [],
    candidates: Array.isArray(payload.candidates) ? payload.candidates.map(parseLogRoutingCandidate) : [],
  };
}

export function parseLogRoutingPreviewResponse(raw: unknown): LogRoutingPreview {
  const payload = asRecord(raw);
  return {
    ok: asBoolean(payload.ok),
    workflow: "log-routing",
    session_id: asString(payload.session_id),
    snapshot_id: asString(payload.snapshot_id),
    schema: asString(payload.schema),
    current_revision: asString(payload.current_revision),
    changes: Array.isArray(payload.changes) ? payload.changes.map(parseLogRoutingPreviewChange) : [],
    warnings: Array.isArray(payload.warnings) ? payload.warnings.map(parseLogRoutingPreviewNotice) : [],
    blockers: Array.isArray(payload.blockers) ? payload.blockers.map(parseLogRoutingPreviewNotice) : [],
  };
}

export function parseLogRoutingApplyResponse(raw: unknown): LogRoutingApplyResponse {
  const preview = parseLogRoutingPreviewResponse(raw);
  const payload = asRecord(raw);
  return {
    ...preview,
    revision_before: asString(payload.revision_before),
    revision_after: asString(payload.revision_after),
    applied_count: asNumber(payload.applied_count),
    noop_count: asNumber(payload.noop_count),
  };
}
