import { useQuery } from "@tanstack/react-query";
import { apiGet, withQuery } from "@/api/client";
import { useScenario } from "@/contexts/ScenarioContext";
import {
  parseGeneralProfileItem,
  parseGeneralProfileList,
  parseProfileCapabilities,
  parseProfileEditorSchema,
} from "@/api/validators/profile";

export function useGeneralProfile() {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["generalProfile", selectedScenarioId],
    queryFn: async () => {
      const data = await apiGet(
        withQuery("/api/general-profile", { scenario_id: selectedScenarioId }),
        parseGeneralProfileItem,
      );
      return data.item;
    },
  });
}

export function useGeneralProfiles() {
  return useQuery({
    queryKey: ["generalProfiles"],
    queryFn: async () => {
      const data = await apiGet("/api/general-profiles", parseGeneralProfileList);
      return data.items;
    },
  });
}

export function useGeneralProfileItem(profileId: string | null) {
  return useQuery({
    queryKey: ["generalProfileItem", profileId],
    queryFn: async () => {
      const data = await apiGet(
        `/api/general-profiles/${encodeURIComponent(profileId || "")}`,
        parseGeneralProfileItem,
      );
      return data.item;
    },
    enabled: !!profileId,
  });
}

export function useProfileCapabilities() {
  return useQuery({
    queryKey: ["profileCapabilities"],
    queryFn: async () => apiGet("/api/profile-capabilities", parseProfileCapabilities),
  });
}

export function useProfileEditorSchema() {
  return useQuery({
    queryKey: ["profileEditorSchema"],
    queryFn: async () => apiGet("/api/profile-editor-schema", parseProfileEditorSchema),
  });
}
