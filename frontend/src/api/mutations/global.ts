import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost } from "@/api/client";

export function useRefreshAll() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost("/api/refresh", { rule_catalog_mode: "incremental" }),
    onSettled: () => {
      queryClient.invalidateQueries();
    },
  });
}
