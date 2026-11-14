import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import { parsePoolListResponse } from "@/api/validators/pools";
import type { PoolStatus, ApiListResponse } from "@/types";

export function usePools() {
  return useQuery({
    queryKey: ["pools"],
    queryFn: async () => {
      const data = await apiGet<ApiListResponse<PoolStatus>>("/api/pools", parsePoolListResponse);
      return data.items;
    },
  });
}
