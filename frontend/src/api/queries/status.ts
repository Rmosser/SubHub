import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import { parseSystemStatusResponse } from "@/api/validators/status";
import type { SystemStatus } from "@/types";

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: () => apiGet<SystemStatus>("/api/status", parseSystemStatusResponse),
  });
}
