import { useCallback } from "react";
import { queryOptions, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, withQuery } from "@/api/client";
import {
  parseBusinessGroupListResponse,
  parseCategoryCustomRules,
  parseCategoryPreviewData,
  parseDirectnessReviewList,
  parsePinData,
  parseRuleCategoryList,
  parseRuleMetadata,
  parseServiceCatalogList,
} from "@/api/validators/catalog";
import { useScenario } from "@/contexts/ScenarioContext";
import type { CategoryPreviewData, PinData, ApiListResponse } from "@/types";

const categoriesQuery = (scenarioId: string) =>
  queryOptions({
    queryKey: ["categories", scenarioId],
    queryFn: async () => {
      const data = await apiGet(
        withQuery("/api/rules/categories", { scenario_id: scenarioId }),
        parseRuleCategoryList,
      );
      return data.items;
    },
  });

const serviceCatalogQuery = (scenarioId: string) =>
  queryOptions({
    queryKey: ["serviceCatalog", scenarioId],
    queryFn: async () => {
      const data = await apiGet(
        withQuery("/api/service-catalog", { scenario_id: scenarioId }),
        parseServiceCatalogList,
      );
      return data.items;
    },
  });

export function useCategories() {
  const { selectedScenarioId } = useScenario();
  return useQuery(categoriesQuery(selectedScenarioId));
}

export function useServiceCatalog() {
  const { selectedScenarioId } = useScenario();
  return useQuery(serviceCatalogQuery(selectedScenarioId));
}

// 服务目录进页要等这两份数据。导航项一被悬停或聚焦就先取，请求和换页动画同时进行，
// 页面挂载时数据多半已在缓存里，跟缓存还新鲜时再进页一样直接出表格，不再先转一圈加载。
// 缓存新鲜时 prefetchQuery 不会重复请求。
export function usePrefetchCatalog() {
  const queryClient = useQueryClient();
  const { selectedScenarioId } = useScenario();
  return useCallback(() => {
    void queryClient.prefetchQuery(categoriesQuery(selectedScenarioId));
    void queryClient.prefetchQuery(serviceCatalogQuery(selectedScenarioId));
  }, [queryClient, selectedScenarioId]);
}

export function usePins() {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["pins", selectedScenarioId],
    queryFn: async () => {
      return apiGet<PinData>(
        withQuery("/api/rules/pins", { scenario_id: selectedScenarioId }),
        parsePinData,
      );
    },
  });
}

export function useDirectnessReviews() {
  return useQuery({
    queryKey: ["directnessReviews"],
    queryFn: async () => {
      const data = await apiGet("/api/rules/directness/reviews", parseDirectnessReviewList);
      return data.items;
    },
  });
}

export function useCategoryCustomRules(categoryName: string) {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["categoryCustomRules", selectedScenarioId, categoryName],
    queryFn: () =>
      apiGet(
        withQuery(`/api/rules/categories/${encodeURIComponent(categoryName)}/custom`, {
          scenario_id: selectedScenarioId,
        }),
        parseCategoryCustomRules,
      ),
    enabled: !!categoryName,
  });
}

export function useRuleMetadata() {
  return useQuery({
    queryKey: ["ruleMetadata"],
    queryFn: () => apiGet("/api/rules/metadata", parseRuleMetadata),
  });
}

export function useCategoryPreview(name: string, offset = 0, limit = 50) {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["categoryPreview", selectedScenarioId, name, offset, limit],
    queryFn: () =>
      apiGet<CategoryPreviewData>(
        withQuery(`/api/rules/categories/${encodeURIComponent(name)}/preview`, {
          scenario_id: selectedScenarioId,
          limit,
          offset,
        }),
        parseCategoryPreviewData,
      ),
    enabled: !!name,
  });
}

export function useBusinessGroups() {
  const { selectedScenarioId } = useScenario();
  return useQuery({
    queryKey: ["businessGroups", selectedScenarioId],
    queryFn: async () => {
      const data = await apiGet<ApiListResponse<import("@/types").BusinessGroup>>(
        withQuery("/api/rules/business-groups", { scenario_id: selectedScenarioId }),
        parseBusinessGroupListResponse,
      );
      return data.items;
    },
  });
}
