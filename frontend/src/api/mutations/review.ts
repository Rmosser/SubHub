import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPut, apiPost, apiDelete } from "@/api/client";
import { parseReviewRunResponse } from "@/api/validators/review";
import type { ReviewRunResponse } from "@/types";

export function useUpdateReviewSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => apiPut("/api/settings/review", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reviewSettings"] }),
  });
}

export function useRunReview() {
  return useMutation({
    mutationFn: (body: { primary_profile_id: string; target_profile_ids: string[] }) =>
      apiPost<ReviewRunResponse>("/api/review", body, parseReviewRunResponse),
  });
}

export function useClearReviewCache() {
  return useMutation({
    mutationFn: (profileId?: string) =>
      apiDelete(`/api/review/cache${profileId ? `?profile_id=${encodeURIComponent(profileId)}` : ""}`),
  });
}
