import type { BusinessGroup, RuleCategory, ServiceCatalogEntry } from "@/types";

export interface CatalogTableRow {
  category: RuleCategory;
  name: string;
  ruleCount: number;
  categoryType: RuleCategory["category_type"];
  locked: boolean;
  directnessOverride: string;
  effectiveGroup: string;
  contractDisplayName: string;
  pinGroup: string;
  pinSortOrder: number;
}

export function getCatalogEntryMap(catalogEntries: ServiceCatalogEntry[]) {
  return new Map(catalogEntries.map((entry) => [entry.category_name, entry]));
}

export function getPinGroupMap(pinGroups: BusinessGroup[]) {
  const pinGroupMap = new Map<string, string>();

  pinGroups.forEach((group) => {
    group.category_names.forEach((categoryName) => {
      pinGroupMap.set(categoryName, group.name);
    });
  });

  return pinGroupMap;
}

export function resolveEffectiveGroup(category: RuleCategory, entry?: ServiceCatalogEntry) {
  return String(entry?.catalog_group ?? category.assigned_group ?? "").trim();
}

export function resolveContractDisplayName(entry?: ServiceCatalogEntry) {
  return String(entry?.contract_display_name ?? "").trim();
}

export function resolveEffectiveContractDisplayName(category: RuleCategory, entry?: ServiceCatalogEntry) {
  return String(entry?.contract_display_name ?? category.effective_contract_display_name ?? "").trim();
}

export function resolvePinGroup(
  categoryName: string,
  pinGroupMap: Map<string, string>,
  category?: RuleCategory,
  entry?: ServiceCatalogEntry,
) {
  return String(pinGroupMap.get(categoryName) ?? category?.pin_group ?? entry?.pin_group ?? "").trim();
}

export function resolvePinSortOrder(category?: RuleCategory, entry?: ServiceCatalogEntry) {
  const entrySortOrder = Number(entry?.sort_order);
  if (Number.isFinite(entrySortOrder)) {
    return entrySortOrder;
  }
  const categorySortOrder = Number(category?.pin_sort_order);
  return Number.isFinite(categorySortOrder) ? categorySortOrder : 0;
}

export function buildCatalogTableRows(
  categories: RuleCategory[],
  catalogEntries: ServiceCatalogEntry[],
  pinGroups: BusinessGroup[] = [],
): CatalogTableRow[] {
  const entryMap = getCatalogEntryMap(catalogEntries);
  const pinGroupMap = getPinGroupMap(pinGroups);

  return categories.map((category) => {
    const entry = entryMap.get(category.name);

    return {
      category,
      name: category.name,
      ruleCount: category.rule_count,
      categoryType: category.category_type,
      locked: category.locked,
      directnessOverride: category.directness_override,
      effectiveGroup: resolveEffectiveGroup(category, entry),
      contractDisplayName: resolveEffectiveContractDisplayName(category, entry),
      pinGroup: resolvePinGroup(category.name, pinGroupMap, category, entry),
      pinSortOrder: resolvePinSortOrder(category, entry),
    };
  });
}

export function buildCatalogSearchText(row: CatalogTableRow) {
  return [
    row.name,
    row.effectiveGroup,
    row.contractDisplayName,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

export function buildVisibleCatalogGroupNames(
  groups: Array<{ name: string }>,
  catalogEntries: ServiceCatalogEntry[],
): string[] {
  const seen = new Set<string>();

  groups.forEach((group) => {
    const name = String(group.name || "").trim();
    if (name) {
      seen.add(name);
    }
  });
  catalogEntries.forEach((entry) => {
    const name = String(entry.catalog_group || "").trim();
    if (name) {
      seen.add(name);
    }
  });

  return Array.from(seen).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
}
