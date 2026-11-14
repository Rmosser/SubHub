import { useEffect, useState } from "react";
import { Table, Pagination } from "@cloudscape-design/components";
import { Chip } from "@/components/Chip";
import { useLocale } from "@/contexts/LocaleContext";
import { useCategoryPreview } from "@/api/queries";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import { paginationLabels } from "@/utils/a11yLabels";

interface CategoryPreviewPanelProps {
  categoryName: string;
}

const PAGE_SIZE = 50;

export function CategoryPreviewPanel({ categoryName }: CategoryPreviewPanelProps) {
  const { t } = useLocale();
  const [page, setPage] = useState(1);
  const offset = (page - 1) * PAGE_SIZE;
  const preview = useCategoryPreview(categoryName, offset, PAGE_SIZE);

  useEffect(() => {
    setPage(1);
  }, [categoryName]);

  const totalPages = preview.data ? Math.max(1, Math.ceil(preview.data.count / PAGE_SIZE)) : 1;

  return (
    <WorkspaceLoader loading={preview.isLoading} error={preview.error} onRetry={() => preview.refetch()}>
      <Table
        variant="embedded"
        items={preview.data?.rules ?? []}
        columnDefinitions={[
          {
            id: "type",
            header: t("common.type"),
            cell: (item) => <Chip mono>{item.type}</Chip>,
          },
          {
            id: "value",
            header: t("common.value"),
            cell: (item) => <span className="s-mono">{item.value}</span>,
          },
          {
            id: "target",
            header: t("catalog.rule_target"),
            cell: (item) => item.target,
          },
        ]}
        pagination={
          <Pagination
            currentPageIndex={page}
            pagesCount={totalPages}
            onChange={({ detail }) => setPage(detail.currentPageIndex)}
            ariaLabels={paginationLabels(t)}
          />
        }
        empty={<div className="s-empty">{t("common.no_items")}</div>}
      />
    </WorkspaceLoader>
  );
}
