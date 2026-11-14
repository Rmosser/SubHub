import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, apiPut, apiDelete, withQuery } from "@/api/client";
import { useScenario } from "@/contexts/ScenarioContext";
import type { ContractCreatePayload, ContractUpdatePayload } from "@/types";

const CONTRACT_DEPENDENT_QUERY_KEYS = [
  "contracts",
  "contract-references",
  "standardSources",
  "categories",
  "serviceCatalog",
  "categoryCustomRules",
  "categoryPreview",
  "customRules",
  "processRules",
  "externalProxyPrograms",
  "devices",
  "pools",
  "status",
  "devicePreview",
  "previewSummary",
  "previewContent",
] as const;

function invalidateContractDependents(qc: ReturnType<typeof useQueryClient>) {
  for (const key of CONTRACT_DEPENDENT_QUERY_KEYS) {
    qc.invalidateQueries({ queryKey: [key] });
  }
}

export function useCreateContract() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: ContractCreatePayload) =>
      apiPost(withQuery("/api/contracts", { scenario_id: selectedScenarioId }), body),
    onSuccess: () => invalidateContractDependents(qc),
  });
}

export function useUpdateContract() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({ id, ...body }: ContractUpdatePayload) =>
      apiPut(`/api/contracts/${encodeURIComponent(id)}?scenario_id=${encodeURIComponent(selectedScenarioId)}`, body),
    onSuccess: () => invalidateContractDependents(qc),
  });
}

export function useDeleteContract() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({ id, replacement_contract_id }: { id: string; replacement_contract_id?: string }) =>
      apiDelete(
        withQuery(`/api/contracts/${encodeURIComponent(id)}`, {
          scenario_id: selectedScenarioId,
          replacement_contract_id,
        }),
      ),
    onSuccess: () => invalidateContractDependents(qc),
  });
}
