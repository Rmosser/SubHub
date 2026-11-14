import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import type { PolicyBackupSnapshot } from "@/types";
import { parsePolicyBackupSnapshot, parsePolicyBackupStatusItem } from "@/api/validators/policyBackup";

export function usePolicyBackupStatus() {
  return useQuery({
    queryKey: ["policyBackupStatus"],
    queryFn: async () => {
      const data = await apiGet("/api/policy-backup/status", parsePolicyBackupStatusItem);
      return data.item;
    },
  });
}

export async function fetchPolicyBackupExport(): Promise<PolicyBackupSnapshot> {
  return apiGet("/api/policy-backup/export", parsePolicyBackupSnapshot);
}
