import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost, apiPut, apiDelete, apiUpload, withQuery } from "@/api/client";
import { parseGoRelaySourceItem, parseStandardSourcePullResponse } from "@/api/validators/sources";
import { useScenario } from "@/contexts/ScenarioContext";

function invalidateGorelayAccount(qc: ReturnType<typeof useQueryClient>, accountId: string) {
  invalidatePublishedSubscriptions(qc);
  qc.invalidateQueries({ queryKey: ["gorelaySources"] });
  qc.invalidateQueries({ queryKey: ["gorelayAccountStatus", accountId] });
  qc.invalidateQueries({ queryKey: ["gorelayAccountDevices", accountId] });
  qc.invalidateQueries({ queryKey: ["gorelayPendingBindings", accountId] });
  qc.invalidateQueries({ queryKey: ["gorelayEntryUsage", accountId] });
  qc.invalidateQueries({ queryKey: ["gorelayImportHistories", accountId] });
  qc.invalidateQueries({ queryKey: ["gorelaySnapshots", accountId] });
  qc.invalidateQueries({ queryKey: ["gorelaySubscriptions", accountId] });
}

function invalidateAllStandardSources(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["standardSources"] });
  invalidatePublishedSubscriptions(qc);
}

function invalidatePublishedSubscriptions(qc: ReturnType<typeof useQueryClient>) {
  for (const key of ["devices", "pools", "status", "devicePreview", "previewSummary", "previewContent"]) {
    qc.invalidateQueries({ queryKey: [key] });
  }
}

export function useCreateStandardSource() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiPost(
        withQuery("/api/sources/standard", { scenario_id: selectedScenarioId }),
        body,
        parseStandardSourcePullResponse,
      ),
    onSuccess: () => invalidateAllStandardSources(qc),
  });
}

export function useUpdateStandardSource() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) =>
      apiPut(
        withQuery(`/api/sources/standard/${encodeURIComponent(id)}`, { scenario_id: selectedScenarioId }),
        body,
        parseStandardSourcePullResponse,
      ),
    onSuccess: () => invalidateAllStandardSources(qc),
  });
}

export function useDeleteStandardSource() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: (id: string) =>
      apiDelete(withQuery(`/api/sources/standard/${encodeURIComponent(id)}`, { scenario_id: selectedScenarioId })),
    onSuccess: () => invalidateAllStandardSources(qc),
  });
}

export function useUploadQrAsset() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({ sourceId, field, file }: { sourceId: string; field: string; file: File }) =>
      apiUpload(
        withQuery(`/api/sources/standard/${encodeURIComponent(sourceId)}/qr/${encodeURIComponent(field)}`, {
          scenario_id: selectedScenarioId,
        }),
        file,
      ),
    onSuccess: () => invalidateAllStandardSources(qc),
  });
}

export function useCreateGorelaySource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiPost("/api/sources/gorelay", body, parseGoRelaySourceItem),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["gorelaySources"] }); invalidatePublishedSubscriptions(qc); },
  });
}

export function useUpdateGorelaySource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) =>
      apiPut(`/api/sources/gorelay/${encodeURIComponent(id)}`, body, parseGoRelaySourceItem),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["gorelaySources"] }); invalidatePublishedSubscriptions(qc); },
  });
}

export function useDeleteGorelaySource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiDelete(`/api/sources/gorelay/${encodeURIComponent(id)}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["gorelaySources"] }); invalidatePublishedSubscriptions(qc); },
  });
}

export function useUpdateRefreshPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => apiPut("/api/settings/refresh-policy", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["refreshPolicy"] }),
  });
}

export function usePullStandardSource() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: async (sourceId: string) => {
      const response = await apiPost(
        withQuery(`/api/sources/standard/${encodeURIComponent(sourceId)}/pull`, { scenario_id: selectedScenarioId }),
        undefined,
        parseStandardSourcePullResponse,
      );
      const pullResult = response.pull_result;
      if (!pullResult?.ok) {
        throw new Error(pullResult?.error || "Pull failed");
      }
      return response;
    },
    onSettled: () => invalidateAllStandardSources(qc),
  });
}

export function useDeleteQrAsset() {
  const qc = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useMutation({
    mutationFn: ({ sourceId, field }: { sourceId: string; field: string }) =>
      apiDelete(
        withQuery(`/api/sources/standard/${encodeURIComponent(sourceId)}/qr/${encodeURIComponent(field)}`, {
          scenario_id: selectedScenarioId,
        }),
      ),
    onSuccess: () => invalidateAllStandardSources(qc),
  });
}

export function useRefreshGorelayAccounts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost("/api/gorelay/refresh"),
    onSettled: () => {
      for (const key of ["gorelaySources", "gorelayAccountStatus", "gorelayAccountDevices", "gorelayPendingBindings", "gorelayEntryUsage", "gorelaySnapshots", "gorelaySubscriptions"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
      invalidatePublishedSubscriptions(qc);
    },
  });
}

export function useCrawlGorelayAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => apiPost(`/api/gorelay/accounts/${encodeURIComponent(accountId)}/crawl`),
    onSuccess: (_data, accountId) => invalidateGorelayAccount(qc, accountId),
  });
}

export function useUpdateGorelayAccountProxyCredentials() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, username, password }: { accountId: string; username: string; password: string }) =>
      apiPut(`/api/gorelay/accounts/${encodeURIComponent(accountId)}/proxy-credentials`, { username, password }),
    onSuccess: (_data, vars) => invalidateGorelayAccount(qc, vars.accountId),
  });
}

export function useUpdateGorelayDeviceProxyCredentials() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      deviceKey,
      username,
      password,
    }: {
      accountId: string;
      deviceKey: string;
      username: string;
      password: string;
    }) =>
      apiPut(
        `/api/gorelay/accounts/${encodeURIComponent(accountId)}/devices/${encodeURIComponent(deviceKey)}/proxy-credentials`,
        { username, password },
      ),
    onSuccess: (_data, vars) => invalidateGorelayAccount(qc, vars.accountId),
  });
}

export function useUpdateGorelayDeviceStrategyPreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      deviceKey,
      strategy_preset,
    }: {
      accountId: string;
      deviceKey: string;
      strategy_preset: string;
    }) =>
      apiPut(
        `/api/gorelay/accounts/${encodeURIComponent(accountId)}/devices/${encodeURIComponent(deviceKey)}/strategy-preset`,
        { strategy_preset },
      ),
    onSuccess: (_data, vars) => invalidateGorelayAccount(qc, vars.accountId),
  });
}

export function useImportGorelayDomainBindings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, reply_text }: { accountId: string; reply_text: string }) =>
      apiPost(`/api/gorelay/accounts/${encodeURIComponent(accountId)}/domain-bindings/import`, { reply_text }),
    onSuccess: (_data, vars) => invalidateGorelayAccount(qc, vars.accountId),
  });
}

export function useImportGorelayEntryMultipliers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, text }: { accountId: string; text: string }) =>
      apiPost(`/api/gorelay/accounts/${encodeURIComponent(accountId)}/entry-multipliers/import`, { text }),
    onSuccess: (_data, vars) => invalidateGorelayAccount(qc, vars.accountId),
  });
}

export function useUpdateGorelayDomainBinding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      bindingId,
      host_value,
      status,
    }: {
      accountId: string;
      bindingId: string;
      host_value: string;
      status: string;
    }) =>
      apiPut(
        `/api/gorelay/accounts/${encodeURIComponent(accountId)}/domain-bindings/${encodeURIComponent(bindingId)}`,
        { host_value, status },
      ),
    onSuccess: (_data, vars) => invalidateGorelayAccount(qc, vars.accountId),
  });
}

export function useDeleteGorelayImportHistory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, historyId }: { accountId: string; historyId: string }) =>
      apiDelete(
        `/api/gorelay/accounts/${encodeURIComponent(accountId)}/domain-import-histories/${encodeURIComponent(historyId)}`,
      ),
    onSuccess: (_data, vars) => invalidateGorelayAccount(qc, vars.accountId),
  });
}

export function useActivateGorelaySnapshot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, snapshotId }: { accountId: string; snapshotId: string }) =>
      apiPost(
        `/api/gorelay/accounts/${encodeURIComponent(accountId)}/snapshots/${encodeURIComponent(snapshotId)}/activate`,
      ),
    onSuccess: (_data, vars) => invalidateGorelayAccount(qc, vars.accountId),
  });
}

export function useDisableGorelaySubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId: _accountId, subscriptionId }: { accountId: string; subscriptionId: string }) =>
      apiPost(`/api/gorelay/subscriptions/${encodeURIComponent(subscriptionId)}/disable`),
    onSuccess: (_data, vars) => invalidateGorelayAccount(qc, vars.accountId),
  });
}
