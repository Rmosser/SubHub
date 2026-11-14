import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, apiPut, apiDelete, withQuery } from "@/api/client";
import { useScenario } from "@/contexts/ScenarioContext";
import { parseProcessRuleListResponse, parseExternalProxyProgramListResponse } from "@/api/validators/advanced";

export function useCreateCustomRule() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiPost(withQuery("/api/rules/custom", { scenario_id: selectedScenarioId }), body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["customRules", selectedScenarioId] }),
  });
}

export function useDeleteCustomRule() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (id: string) =>
      apiDelete(withQuery(`/api/rules/custom/${encodeURIComponent(id)}`, { scenario_id: selectedScenarioId })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["customRules", selectedScenarioId] }),
  });
}

export function useSaveProcessRules() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: { items: Record<string, unknown>[] }) =>
      apiPut(withQuery("/api/settings/surge/process-rules", { scenario_id: selectedScenarioId }), body, parseProcessRuleListResponse),
    onSuccess: (data) => {
      qc.setQueryData(["processRules", selectedScenarioId], data.items);
      qc.invalidateQueries({ queryKey: ["devices", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["devicePreview", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["previewContent", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["previewSummary", selectedScenarioId] });
    },
  });
}

export function useSaveExternalProxyPrograms() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: { items: Record<string, unknown>[] }) =>
      apiPut(
        withQuery("/api/settings/surge/external-proxy-programs", { scenario_id: selectedScenarioId }),
        body,
        parseExternalProxyProgramListResponse,
      ),
    onSuccess: (data) => {
      qc.setQueryData(["externalProxyPrograms", selectedScenarioId], data.items);
      qc.invalidateQueries({ queryKey: ["devices", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["devicePreview", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["previewContent", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["previewSummary", selectedScenarioId] });
    },
  });
}
