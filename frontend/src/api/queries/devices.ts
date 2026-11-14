import { useQuery } from "@tanstack/react-query";
import { apiGet, apiGetText, withQuery } from "@/api/client";
import {
  normalizeDevicePreviewResponse,
  normalizePreviewSummary,
  parseDeviceListResponse,
} from "@/api/validators/devices";
import { useScenario } from "@/contexts/ScenarioContext";
import type { DeviceWithLinks, DevicePreview, PreviewContent, PreviewSummary, ApiListResponse } from "@/types";
import type { ClientTarget } from "@/constants/clients";

export function useDevices() {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["devices", selectedScenarioId],
    queryFn: async () => {
      const data = await apiGet<ApiListResponse<DeviceWithLinks>>(
        withQuery("/api/devices", { scenario_id: selectedScenarioId }),
        parseDeviceListResponse,
      );
      return data.items;
    },
  });
}

export function useDevicePreview(subscriptionId: string, target: ClientTarget | null) {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["devicePreview", selectedScenarioId, subscriptionId, target],
    queryFn: async () =>
      apiGet<DevicePreview>(
        withQuery(`/api/devices/${encodeURIComponent(subscriptionId)}/render-preview`, {
          target,
          scenario_id: selectedScenarioId,
        }),
        normalizeDevicePreviewResponse,
      ),
    enabled: !!subscriptionId && !!target,
  });
}

export function usePreviewSummary(subscriptionId: string, target: ClientTarget | null) {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["previewSummary", selectedScenarioId, subscriptionId, target],
    queryFn: () =>
      apiGet<PreviewSummary>(
        withQuery(`/api/devices/${encodeURIComponent(subscriptionId)}/preview-summary`, {
          target,
          scenario_id: selectedScenarioId,
        }),
        normalizePreviewSummary,
      ),
    enabled: !!subscriptionId && !!target,
  });
}

export function usePreviewContent(subscriptionId: string, target: ClientTarget | null) {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["previewContent", selectedScenarioId, subscriptionId, target],
    queryFn: async (): Promise<PreviewContent> => {
      const result = await apiGetText(
        withQuery(`/api/devices/${encodeURIComponent(subscriptionId)}/preview-content`, {
          target,
          scenario_id: selectedScenarioId,
        }),
      );
      return {
        text: result.body,
        lineCount: Number(result.headers.get("X-Preview-Lines") || "0"),
        charCount: Number(result.headers.get("X-Preview-Chars") || "0"),
      };
    },
    enabled: !!subscriptionId && !!target,
  });
}
