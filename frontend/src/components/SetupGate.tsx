import { useEffect, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import { parseSetupStatus } from "@/api/validators/setup";
import { WorkspaceLoader } from "./WorkspaceLoader";

export function SetupGate({ children }: { children: ReactNode }) {
  const status = useQuery({
    queryKey: ["setupStatus"],
    queryFn: () => apiGet("/api/setup/status", parseSetupStatus),
  });
  const requiresSetup = status.data?.setup_required === true;
  useEffect(() => {
    if (requiresSetup) window.location.replace("/setup");
  }, [requiresSetup]);

  return (
    <WorkspaceLoader loading={status.isLoading || requiresSetup} error={status.error} onRetry={() => status.refetch()}>
      {status.data?.initialized ? children : null}
    </WorkspaceLoader>
  );
}
