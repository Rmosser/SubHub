import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import { parseLlmExportSettingsResponse, parseLogRoutingCandidatesResponse } from "@/api/validators/llm";
import type { LlmExportSettings, LogRoutingCandidatesResponse } from "@/types";

export function useLlmExportSettings() {
  return useQuery({
    queryKey: ["llmExportSettings"],
    queryFn: () =>
      apiGet<LlmExportSettings | null>("/api/settings/llm-export", parseLlmExportSettingsResponse),
  });
}

export function useLogRoutingCandidates(sessionId: string | null) {
  return useQuery({
    queryKey: ["logRoutingCandidates", sessionId],
    enabled: Boolean(sessionId),
    queryFn: () =>
      apiGet<LogRoutingCandidatesResponse>(
        `/api/llm/log-routing/sessions/${sessionId}/candidates`,
        parseLogRoutingCandidatesResponse,
      ),
  });
}
