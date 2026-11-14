import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, apiPut, apiDelete, withQuery } from "@/api/client";
import { useScenario } from "@/contexts/ScenarioContext";
import type { ProfileEditorState } from "@/types";
import { parseGeneralProfileItem } from "@/api/validators/profile";

type ProfileWriteBody = {
  name?: string;
  settings?: Record<string, unknown>;
  capabilities?: Record<string, unknown>;
  editor_state?: ProfileEditorState;
};

export function useUpdateGeneralProfile() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: ProfileWriteBody) =>
      apiPut(withQuery("/api/general-profile", { scenario_id: selectedScenarioId }), body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["generalProfile", selectedScenarioId] }),
  });
}

export function useResetGeneralProfileEditorState() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: () =>
      apiPost(withQuery("/api/general-profile/reset-editor-state", { scenario_id: selectedScenarioId }), {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["generalProfile", selectedScenarioId] }),
  });
}

export function useCreateGeneralProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; settings?: Record<string, unknown>; capabilities?: Record<string, unknown>; editor_state?: ProfileEditorState }) =>
      apiPost("/api/general-profiles", body, parseGeneralProfileItem),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["generalProfiles"] }),
  });
}

export function useDeleteGeneralProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/general-profiles/${encodeURIComponent(id)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["generalProfiles"] }),
  });
}

export function useUpdateGeneralProfileItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) =>
      apiPut(`/api/general-profiles/${encodeURIComponent(id)}`, body),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["generalProfiles"] });
      qc.invalidateQueries({ queryKey: ["generalProfileItem", vars.id] });
    },
  });
}

export function useResetGeneralProfileItemEditorState() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiPost(`/api/general-profiles/${encodeURIComponent(id)}/reset-editor-state`, {}),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["generalProfiles"] });
      qc.invalidateQueries({ queryKey: ["generalProfileItem", id] });
    },
  });
}
