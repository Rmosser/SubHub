import { useQuery } from "@tanstack/react-query";
import { apiGet, withQuery } from "@/api/client";
import { useScenario } from "@/contexts/ScenarioContext";
import {
  parseGoRelayAccountDeviceList,
  parseGoRelayAccountStatus,
  parseGoRelayEntryUsageList,
  parseGoRelayImportHistoryList,
  parseGoRelayPendingBindings,
  parseGoRelaySnapshotList,
  parseGoRelaySourceList,
  parseGoRelaySubscriptionList,
  parseRefreshPolicyItem,
  parseStandardSourceList,
} from "@/api/validators/sources";

export function useStandardSources() {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["standardSources", selectedScenarioId],
    queryFn: async () => {
      const data = await apiGet(
        withQuery("/api/sources/standard", { scenario_id: selectedScenarioId }),
        parseStandardSourceList,
      );
      return data.items;
    },
  });
}

export function useGorelaySources() {
  return useQuery({
    queryKey: ["gorelaySources"],
    queryFn: async () => {
      const data = await apiGet("/api/sources/gorelay", parseGoRelaySourceList);
      return data.items;
    },
  });
}

export function useRefreshPolicy() {
  return useQuery({
    queryKey: ["refreshPolicy"],
    queryFn: async () => {
      const data = await apiGet("/api/settings/refresh-policy", parseRefreshPolicyItem);
      return data.item;
    },
  });
}

export function useGorelayAccountStatus(accountId: string | null) {
  return useQuery({
    queryKey: ["gorelayAccountStatus", accountId],
    queryFn: async () => {
      const data = await apiGet(`/api/gorelay/accounts/${encodeURIComponent(accountId || "")}/status`, parseGoRelayAccountStatus);
      return data;
    },
    enabled: !!accountId,
  });
}

export function useGorelayAccountDevices(accountId: string | null) {
  return useQuery({
    queryKey: ["gorelayAccountDevices", accountId],
    queryFn: async () => {
      const data = await apiGet(
        withQuery(`/api/gorelay/accounts/${encodeURIComponent(accountId || "")}/devices`, { include_stale: true }),
        parseGoRelayAccountDeviceList,
      );
      return data.items;
    },
    enabled: !!accountId,
  });
}

export function useGorelayPendingBindings(accountId: string | null) {
  return useQuery({
    queryKey: ["gorelayPendingBindings", accountId],
    queryFn: async () => {
      const data = await apiGet(
        `/api/gorelay/accounts/${encodeURIComponent(accountId || "")}/domain-bindings/pending`,
        parseGoRelayPendingBindings,
      );
      return data;
    },
    enabled: !!accountId,
  });
}

export function useGorelayEntryUsage(accountId: string | null) {
  return useQuery({
    queryKey: ["gorelayEntryUsage", accountId],
    queryFn: async () => {
      const data = await apiGet(
        `/api/gorelay/accounts/${encodeURIComponent(accountId || "")}/entries`,
        parseGoRelayEntryUsageList,
      );
      return data.items;
    },
    enabled: !!accountId,
  });
}

export function useGorelayImportHistories(accountId: string | null) {
  return useQuery({
    queryKey: ["gorelayImportHistories", accountId],
    queryFn: async () => {
      const data = await apiGet(
        `/api/gorelay/accounts/${encodeURIComponent(accountId || "")}/domain-import-histories`,
        parseGoRelayImportHistoryList,
      );
      return data.items;
    },
    enabled: !!accountId,
  });
}

export function useGorelaySnapshots(accountId: string | null) {
  return useQuery({
    queryKey: ["gorelaySnapshots", accountId],
    queryFn: async () => {
      const data = await apiGet(
        `/api/gorelay/accounts/${encodeURIComponent(accountId || "")}/snapshots`,
        parseGoRelaySnapshotList,
      );
      return data;
    },
    enabled: !!accountId,
  });
}

export function useGorelaySubscriptions(accountId: string | null) {
  return useQuery({
    queryKey: ["gorelaySubscriptions", accountId],
    queryFn: async () => {
      const data = await apiGet(
        withQuery("/api/gorelay/subscriptions", { account_id: accountId, include_disabled: true }),
        parseGoRelaySubscriptionList,
      );
      return data.items;
    },
    enabled: !!accountId,
  });
}
