import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, apiPut, apiDelete, withQuery } from "@/api/client";
import { useScenario } from "@/contexts/ScenarioContext";

export function useCreateManualCategory() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: { name: string }) => apiPost("/api/rules/categories/manual", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
    },
  });
}

export function useUpdateCategoryBinding() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({
      name,
      ...body
    }: {
      name: string;
      catalog_group?: string;
      contract_id?: string;
      sort_order?: number;
    }) =>
      apiPut(withQuery(`/api/service-catalog/${encodeURIComponent(name)}`, { scenario_id: selectedScenarioId }), body),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["categoryCustomRules", selectedScenarioId, vars.name] });
      qc.invalidateQueries({ queryKey: ["categoryPreview", selectedScenarioId, vars.name] });
    },
  });
}

export function useDeleteCategory() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (name: string) => apiDelete(`/api/rules/categories/${encodeURIComponent(name)}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
    },
  });
}

export function useRenameCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, new_name }: { name: string; new_name: string }) =>
      apiPut(`/api/rules/categories/${encodeURIComponent(name)}/rename`, { new_name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["categories"] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog"] });
    },
  });
}

export function useLockCategory() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (name: string) =>
      apiPost(withQuery(`/api/rules/categories/${encodeURIComponent(name)}/lock`, { scenario_id: selectedScenarioId })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] }),
  });
}

export function useUnlockCategory() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (name: string) =>
      apiPost(
        withQuery(`/api/rules/categories/${encodeURIComponent(name)}/lock`, { scenario_id: selectedScenarioId }),
        { locked: false },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] }),
  });
}

export function useRestoreCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiPost(`/api/rules/categories/${encodeURIComponent(name)}/restore`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["categories"] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog"] });
    },
  });
}

export function useAddCategoryCustomRule() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({ name, ...body }: { name: string; rule_type: string; value: string }) =>
      apiPost(
        withQuery(`/api/rules/categories/${encodeURIComponent(name)}/custom`, { scenario_id: selectedScenarioId }),
        body,
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["categoryCustomRules", selectedScenarioId, vars.name] });
      qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] });
    },
  });
}

export function useDeleteCategoryCustomRule() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({ name, ruleId }: { name: string; ruleId: string }) =>
      apiDelete(
        withQuery(`/api/rules/categories/${encodeURIComponent(name)}/custom/${encodeURIComponent(ruleId)}`, {
          scenario_id: selectedScenarioId,
        }),
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["categoryCustomRules", selectedScenarioId, vars.name] });
      qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] });
    },
  });
}

export function useCreateBusinessGroup() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: { name: string }) =>
      apiPost(withQuery("/api/rules/business-groups", { scenario_id: selectedScenarioId }), body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["businessGroups", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
    },
  });
}

export function useDeleteBusinessGroup() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (name: string) =>
      apiDelete(withQuery(`/api/rules/business-groups/${encodeURIComponent(name)}`, { scenario_id: selectedScenarioId })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["businessGroups", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
    },
  });
}

export function useRenameBusinessGroup() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({ name, new_name }: { name: string; new_name: string }) =>
      apiPut(
        withQuery(`/api/rules/business-groups/${encodeURIComponent(name)}/rename`, {
          scenario_id: selectedScenarioId,
        }),
        { new_name },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["businessGroups", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
    },
  });
}

export function useRefreshCatalog() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost("/api/rules/refresh"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["categories"] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog"] });
      qc.invalidateQueries({ queryKey: ["pins"] });
    },
  });
}

export function useReviewDirectness() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "accept" | "dismiss" }) =>
      apiPost(`/api/rules/directness/reviews/${encodeURIComponent(id)}/${action}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["directnessReviews"] });
      qc.invalidateQueries({ queryKey: ["categories"] });
    },
  });
}

export function usePinCategory() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({ name, pin_group, sort_order }: { name: string; pin_group?: string; sort_order?: number }) =>
      apiPut(
        withQuery(`/api/rules/categories/${encodeURIComponent(name)}/pin`, { scenario_id: selectedScenarioId }),
        { pin_group, sort_order },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
    },
  });
}

export function useUnpinCategory() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (name: string) =>
      apiDelete(
        withQuery(`/api/rules/categories/${encodeURIComponent(name)}/pin`, { scenario_id: selectedScenarioId }),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
    },
  });
}

export function useCreatePinGroup() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: { group_name: string; mode?: string; description?: string }) =>
      apiPost(withQuery("/api/rules/pin-groups", { scenario_id: selectedScenarioId }), body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] }),
  });
}

export function useRenamePinGroup() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({ name, new_name }: { name: string; new_name: string }) =>
      apiPut(
        withQuery(`/api/rules/pin-groups/${encodeURIComponent(name)}/rename`, { scenario_id: selectedScenarioId }),
        { new_name },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] }),
  });
}

export function useDeletePinGroup() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (name: string) =>
      apiDelete(
        withQuery(`/api/rules/pin-groups/${encodeURIComponent(name)}`, { scenario_id: selectedScenarioId }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] }),
  });
}

export function useReorderPinGroups() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: { items: Record<string, unknown>[] }) =>
      apiPut(withQuery("/api/rules/pin-groups/reorder", { scenario_id: selectedScenarioId }), body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] }),
  });
}

export function useReorderBusinessGroups() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: { items: Record<string, unknown>[] }) =>
      apiPut(withQuery("/api/rules/business-groups/reorder", { scenario_id: selectedScenarioId }), body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["businessGroups", selectedScenarioId] });
    },
  });
}

export function useReorderPins() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: { items: Record<string, unknown>[] }) =>
      apiPut(withQuery("/api/rules/pins/reorder", { scenario_id: selectedScenarioId }), body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] }),
  });
}

export function useApplyDirectnessReviews() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { review_ids: string[]; action: "accept" | "dismiss" }) =>
      apiPost("/api/rules/directness/reviews/apply", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["directnessReviews"] });
      qc.invalidateQueries({ queryKey: ["categories"] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog"] });
    },
  });
}

export function useBulkAssignCategories() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: { assignments: Record<string, string> }) =>
      apiPost(withQuery("/api/rules/categories/bulk-assign", { scenario_id: selectedScenarioId }), body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
    },
  });
}

export function useBulkAssignCatalogGroups() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: { assignments: Record<string, string> }) =>
      apiPut(withQuery("/api/service-catalog/bulk-groups", { scenario_id: selectedScenarioId }), body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pins", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["serviceCatalog", selectedScenarioId] });
      qc.invalidateQueries({ queryKey: ["businessGroups", selectedScenarioId] });
    },
  });
}

export function useBulkAddCategoryCustomRules() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({ name, items }: { name: string; items: { rule_type: string; value: string }[] }) =>
      apiPost(
        withQuery(`/api/rules/categories/${encodeURIComponent(name)}/custom/bulk`, { scenario_id: selectedScenarioId }),
        { items },
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["categoryCustomRules", selectedScenarioId, vars.name] });
      qc.invalidateQueries({ queryKey: ["categories", selectedScenarioId] });
    },
  });
}
