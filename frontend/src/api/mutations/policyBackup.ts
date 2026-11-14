import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost } from "@/api/client";
import type { PolicyRestorePreview } from "@/types";
import {
  parsePolicyBackupApplyResult,
  parsePolicyBackupSyncResult,
  parsePolicyRestorePreview,
} from "@/api/validators/policyBackup";

export function useSyncPolicyBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost("/api/policy-backup/sync", undefined, parsePolicyBackupSyncResult),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["policyBackupStatus"] }),
  });
}

export function usePreviewPolicyBackupRestore() {
  return useMutation({
    mutationFn: (body: { ref?: string }) =>
      apiPost<PolicyRestorePreview>("/api/policy-backup/restore/preview", body, parsePolicyRestorePreview),
  });
}

export function useApplyPolicyBackupRestore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { ref?: string; expected_digest: string }) =>
      apiPost("/api/policy-backup/restore/apply", body, parsePolicyBackupApplyResult),
    onSuccess: async () => {
      await qc.invalidateQueries();
    },
  });
}
