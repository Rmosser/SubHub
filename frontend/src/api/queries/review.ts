import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import { parseReviewSettings } from "@/api/validators/review";

export function useReviewSettings() {
  return useQuery({
    queryKey: ["reviewSettings"],
    queryFn: () => apiGet("/api/settings/review", parseReviewSettings),
  });
}
