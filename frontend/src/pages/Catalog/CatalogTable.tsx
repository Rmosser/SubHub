import { Table, TextFilter, Pagination } from "@cloudscape-design/components";
import { NameAction } from "@/components/InlineAction";
import { Chip } from "@/components/Chip";
import { useLocale } from "@/contexts/LocaleContext";
import { useSplitPanelControls } from "@/contexts/SplitPanelContext";
import { paginationLabels } from "@/utils/a11yLabels";
import { useCloudscapeTable } from "@/hooks/useCloudscapeTable";
import type { RuleCategory, ServiceCatalogEntry } from "@/types";
import { buildCatalogSearchText, buildCatalogTableRows } from "./catalogView";

interface CatalogTableProps {
  categories: RuleCategory[];
  catalogEntries: ServiceCatalogEntry[];
  loading: boolean;
  onSelect: (category: RuleCategory) => void;
}

export function CatalogTable({ categories, catalogEntries, loading, onSelect }: CatalogTableProps) {
  const drawerId = useSplitPanelControls();
  const { t, locale } = useLocale();
  const rows = buildCatalogTableRows(categories, catalogEntries);

  const { items, filterProps, paginationProps, collectionProps } = useCloudscapeTable({
    items: rows,
    filteringFunction: (item, text) =>
      buildCatalogSearchText(item).includes(text.toLowerCase()),
    pagination: { pageSize: 25 },
  });

  return (
    <Table
      {...collectionProps}
      items={items}
      loading={loading}
      filter={
        <TextFilter
          {...filterProps}
          filteringPlaceholder={t("catalog.search_placeholder_rich")}
        />
      }
      pagination={<Pagination {...paginationProps} ariaLabels={paginationLabels(t)} />}
      onRowClick={({ detail }) => onSelect(detail.item.category)}
      columnDefinitions={[
        {
          id: "name",
          header: t("common.name"),
          cell: (item) => (
            <div className="s-chips">
              <NameAction ariaControls={drawerId} onClick={(event) => { event.stopPropagation(); onSelect(item.category); }}>{item.name}</NameAction>
              {item.locked && <Chip muted>{t("catalog.locked")}</Chip>}
              {item.directnessOverride && <Chip mono dot={item.directnessOverride === "DIRECT" ? "teal" : "flow"}>{item.directnessOverride}</Chip>}
            </div>
          ),
          sortingField: "name",
        },
        {
          id: "rule_count",
          header: t("catalog.rule_count"),
          cell: (item) => <span className="s-num">{item.ruleCount}</span>,
          sortingField: "ruleCount",
        },
        {
          id: "assigned_group",
          header: t("catalog.assigned_group"),
          cell: (item) => item.effectiveGroup || "-",
        },
        {
          id: "contract",
          header: t("catalog.contract"),
          cell: (item) => item.contractDisplayName || "-",
        },
        {
          id: "category_type",
          header: t("catalog.category_type"),
          cell: (item) => (
            <span className={item.categoryType === "auto" ? "s-muted" : undefined}>
              {item.categoryType === "auto" ? t("catalog.auto") : t("catalog.manual")}
            </span>
          ),
        },
      ]}
      empty={
        <div className="s-empty">
          <strong>{t("catalog.no_categories")}</strong>
          {locale === "zh-CN" ? "刷新以导入服务分类，或创建一个手动分类来整理自己的规则。" : "Refresh to import service categories, or create a manual category for your own rules."}
        </div>
      }
    />
  );
}
