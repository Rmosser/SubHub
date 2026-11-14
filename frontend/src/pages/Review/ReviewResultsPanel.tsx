import { ExpandableSection, Table } from "@cloudscape-design/components";
import { useLocale } from "@/contexts/LocaleContext";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorNote } from "@/components/ErrorNote";
import { Chip } from "@/components/Chip";
import { Surface } from "@/components/Section";
import type { ReviewResult } from "@/types/review";

interface ReviewResultsPanelProps {
  results: ReviewResult[];
  runError?: string | null;
  onRetry?: () => void;
  retrying?: boolean;
}

const DIFF_DOT = { added: "teal", removed: "warm", changed: "flow" } as const;

// 结果的总体状态在分组标题行说一次；每个目标配置是一块可折叠面板，差异类型是带淡色点的中性标签。
export function ReviewResultSummary({ results }: { results: ReviewResult[] }) {
  const { t } = useLocale();
  if (results.length === 0) return null;
  const failedCount = results.filter((result) => result.error).length;
  const diffCount = results.reduce((count, result) => count + result.annotations.length, 0);
  if (failedCount > 0) {
    return <StatusBadge status="warning">{t("review.partial_failure_help", { failed: failedCount, total: results.length })}</StatusBadge>;
  }
  if (diffCount > 0) {
    return <StatusBadge status="success">{t("review.results_summary", { targets: results.length, changes: diffCount })}</StatusBadge>;
  }
  return <StatusBadge status="success">{t("review.clean_results")}</StatusBadge>;
}

export function ReviewResultsPanel({ results, runError, onRetry, retrying }: ReviewResultsPanelProps) {
  const { t } = useLocale();

  if (runError) {
    return (
      <Surface>
        <ErrorNote title={t("review.run_failed")} reason={runError} onRetry={onRetry} retrying={retrying} />
      </Surface>
    );
  }

  if (results.length === 0) {
    return (
      <Surface flush>
        <div className="s-empty">{t("review.no_results")}</div>
      </Surface>
    );
  }

  return (
    <div className="s-stack">
      {results.map((result) => (
        <ExpandableSection
          key={result.target_profile_id}
          headerText={result.target_profile_name}
          headerCounter={`(${result.annotations.length})`}
          variant="container"
          defaultExpanded
        >
          {result.error ? (
            <ErrorNote title={t("review.run_failed")} reason={result.error} />
          ) : (
            <Table
              variant="embedded"
              items={result.annotations}
              wrapLines
              columnDefinitions={[
                {
                  id: "key",
                  header: t("review.col_key"),
                  cell: (item) => <span className="s-mono">{item.key}</span>,
                },
                {
                  id: "diff_type",
                  header: t("common.type"),
                  cell: (item) => {
                    const kind = item.diff_type === "added" || item.diff_type === "removed" ? item.diff_type : "changed";
                    const label =
                      kind === "added"
                        ? t("review.diff_added")
                        : kind === "removed"
                          ? t("review.diff_removed")
                          : t("review.diff_changed");
                    return <Chip dot={DIFF_DOT[kind]}>{label}</Chip>;
                  },
                },
                {
                  id: "primary_value",
                  header: t("review.col_primary"),
                  cell: (item) => item.primary_value || "-",
                },
                {
                  id: "target_value",
                  header: t("review.col_target"),
                  cell: (item) => item.target_value || "-",
                },
                {
                  id: "explanation",
                  header: t("review.col_explanation"),
                  cell: (item) => item.explanation,
                },
              ]}
              empty={<div className="s-empty">{t("review.no_differences")}</div>}
            />
          )}
        </ExpandableSection>
      ))}
    </div>
  );
}
