import type { PaginationProps } from "@cloudscape-design/components/pagination";

type Translate = (key: string, vars?: Record<string, string | number>) => string;

// Cloudscape Pagination 的读屏名称：上一页、下一页、第 N 页
export function paginationLabels(t: Translate): PaginationProps.Labels {
  return {
    paginationLabel: t("common.pagination"),
    previousPageLabel: t("common.previous_page"),
    nextPageLabel: t("common.next_page"),
    pageLabel: (page) => t("common.page_number", { page }),
  };
}
