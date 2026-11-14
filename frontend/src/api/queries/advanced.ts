import { useQuery } from "@tanstack/react-query";
import { apiGet, withQuery } from "@/api/client";
import { useScenario } from "@/contexts/ScenarioContext";
import type { ProcessRuleTemplate, ExternalProxyProgramTemplate, ApiListResponse } from "@/types";
import { parseCustomRuleList } from "@/api/validators/catalog";
import { parseProcessRuleListResponse, parseExternalProxyProgramListResponse } from "@/api/validators/advanced";

export function useCustomRules() {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["customRules", selectedScenarioId],
    queryFn: async () => {
      const data = await apiGet(
        withQuery("/api/rules/custom", { scenario_id: selectedScenarioId }),
        parseCustomRuleList,
      );
      return data.items;
    },
  });
}

export function useProcessRules() {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["processRules", selectedScenarioId],
    queryFn: async () => {
      const data = await apiGet<ApiListResponse<ProcessRuleTemplate>>(
        withQuery("/api/settings/surge/process-rules", { scenario_id: selectedScenarioId }),
        parseProcessRuleListResponse,
      );
      return data.items;
    },
  });
}

export function useExternalProxyPrograms() {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["externalProxyPrograms", selectedScenarioId],
    queryFn: async () => {
      const data = await apiGet<ApiListResponse<ExternalProxyProgramTemplate>>(
        withQuery("/api/settings/surge/external-proxy-programs", { scenario_id: selectedScenarioId }),
        parseExternalProxyProgramListResponse,
      );
      return data.items;
    },
  });
}
