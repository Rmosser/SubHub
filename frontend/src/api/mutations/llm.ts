import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, apiPut, apiUpload, withQuery } from "@/api/client";
import {
  parseLlmWorkflowApplyResponse,
  parseLlmWorkflowExportResponse,
  parseLlmWorkflowPreviewResponse,
  parseLogRoutingApplyResponse,
  parseLogRoutingExportResponse,
  parseLogRoutingPreviewResponse,
  parseLogRoutingSessionResponse,
} from "@/api/validators/llm";
import { useScenario } from "@/contexts/ScenarioContext";
import type {
  LlmExportSettings,
  LlmWorkflowApplyResponse,
  LlmWorkflowExport,
  LlmWorkflowId,
  LlmWorkflowPreview,
  LogRoutingApplyResponse,
  LogRoutingExport,
  LogRoutingPreview,
  LogRoutingSessionInfo,
} from "@/types";

export function useUpdateLlmExportSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<LlmExportSettings>) => apiPut("/api/settings/llm-export", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llmExportSettings"] }),
  });
}

export function useExportLlmWorkflow() {
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: {
      workflow_type: LlmWorkflowId;
      intent_override?: string;
      sample_rule_limit?: number;
    }) =>
      apiPost<LlmWorkflowExport>(
        withQuery(`/api/llm/workflows/${body.workflow_type}/export`, { scenario_id: selectedScenarioId }),
        {
          intent_override: body.intent_override,
          sample_rule_limit: body.sample_rule_limit,
        },
        parseLlmWorkflowExportResponse,
      ),
  });
}

export function usePreviewLlmImport() {
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: {
      workflow_type: LlmWorkflowId;
      snapshot_fingerprint: string;
      result: Record<string, unknown>;
    }) =>
      apiPost<LlmWorkflowPreview>(
        withQuery(`/api/llm/workflows/${body.workflow_type}/preview-import`, { scenario_id: selectedScenarioId }),
        {
          snapshot_fingerprint: body.snapshot_fingerprint,
          result: body.result,
        },
        parseLlmWorkflowPreviewResponse,
      ),
  });
}

export function useApplyLlmImport() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: {
      workflow_type: LlmWorkflowId;
      snapshot_fingerprint: string;
      result: Record<string, unknown>;
      selected_change_ids: string[];
    }) =>
      apiPost<LlmWorkflowApplyResponse>(
        withQuery(`/api/llm/workflows/${body.workflow_type}/apply`, { scenario_id: selectedScenarioId }),
        {
          snapshot_fingerprint: body.snapshot_fingerprint,
          result: body.result,
          selected_change_ids: body.selected_change_ids,
        },
        parseLlmWorkflowApplyResponse,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["businessGroups", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["directnessReviews"] });
    },
  });
}

export function useCreateLogRoutingSession() {
  return useMutation({
    mutationFn: () =>
      apiPost<LogRoutingSessionInfo>("/api/llm/log-routing/sessions", {}, parseLogRoutingSessionResponse),
  });
}

export function useUploadLogRoutingFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { sessionId: string; file: File }) =>
      apiUpload(
        `/api/llm/log-routing/sessions/${body.sessionId}/files`,
        body.file,
      ),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["logRoutingCandidates", variables.sessionId] });
    },
  });
}

export function useExportLogRoutingSession() {
  return useMutation({
    mutationFn: (body: {
      sessionId: string;
      intent_override?: string;
      sample_evidence_limit?: number;
    }) =>
      apiPost<LogRoutingExport>(
        `/api/llm/log-routing/sessions/${body.sessionId}/export`,
        {
          intent_override: body.intent_override,
          sample_evidence_limit: body.sample_evidence_limit,
        },
        parseLogRoutingExportResponse,
      ),
  });
}

export function usePreviewLogRoutingPatch() {
  return useMutation({
    mutationFn: (body: {
      sessionId: string;
      snapshot_id: string;
      patch: Record<string, unknown>;
    }) =>
      apiPost<LogRoutingPreview>(
        `/api/llm/log-routing/sessions/${body.sessionId}/preview`,
        {
          snapshot_id: body.snapshot_id,
          patch: body.patch,
        },
        parseLogRoutingPreviewResponse,
      ),
  });
}

export function useApplyLogRoutingPatch() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: {
      sessionId: string;
      snapshot_id: string;
      patch: Record<string, unknown>;
      selected_action_ids: string[];
    }) =>
      apiPost<LogRoutingApplyResponse>(
        `/api/llm/log-routing/sessions/${body.sessionId}/apply`,
        {
          snapshot_id: body.snapshot_id,
          patch: body.patch,
          selected_action_ids: body.selected_action_ids,
        },
        parseLogRoutingApplyResponse,
      ),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["logRoutingCandidates", variables.sessionId] });
      qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["businessGroups", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["directnessReviews"] });
    },
  });
}
