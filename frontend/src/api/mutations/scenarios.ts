import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, apiPut, apiDelete } from "@/api/client";
import type { ProfileEditorState } from "@/types";

export function useCreateScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { slug: string; name: string; description?: string; enabled?: boolean; editor_state?: ProfileEditorState }) =>
      apiPost("/api/scenarios", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scenarios"] }),
  });
}

export function useUpdateScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; slug?: string; name?: string; description?: string; enabled?: boolean; sort_order?: number; settings?: Record<string, unknown>; editor_state?: ProfileEditorState }) =>
      apiPut(`/api/scenarios/${encodeURIComponent(id)}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scenarios"] }),
  });
}

export function useDeleteScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/scenarios/${encodeURIComponent(id)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scenarios"] }),
  });
}

export function useResetScenarioEditorState() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost(`/api/scenarios/${encodeURIComponent(id)}/reset-editor-state`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scenarios"] }),
  });
}
