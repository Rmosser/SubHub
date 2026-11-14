import { useQuery } from "@tanstack/react-query";
import { apiGet, withQuery } from "@/api/client";
import { useScenario } from "@/contexts/ScenarioContext";
import { parseContractReferences, parseRouteContractList } from "@/api/validators/contracts";

export function useContracts(scenarioId?: string) {
  const { selectedScenarioId } = useScenario();
  const resolvedScenarioId = scenarioId || selectedScenarioId;
  return useQuery({
    queryKey: ["contracts", resolvedScenarioId],
    queryFn: async () => {
      const data = await apiGet(
        withQuery("/api/contracts", { scenario_id: resolvedScenarioId }),
        parseRouteContractList,
      );
      return data.items;
    },
  });
}

export function useContractReferences(contractId?: string, enabled = true) {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["contract-references", selectedScenarioId, contractId],
    queryFn: () =>
      apiGet(
        withQuery(`/api/contracts/${encodeURIComponent(contractId || "")}/references`, {
          scenario_id: selectedScenarioId,
        }),
        parseContractReferences,
      ),
    enabled: enabled && Boolean(contractId),
  });
}
