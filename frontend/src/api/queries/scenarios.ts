import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import { parseScenarioProfileList } from "@/api/validators/profile";

export function useScenarios() {
  return useQuery({
    queryKey: ["scenarios"],
    queryFn: async () => {
      const data = await apiGet("/api/scenarios", parseScenarioProfileList);
      return data.items;
    },
  });
}
