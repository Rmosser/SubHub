import { motion } from "motion/react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Table from "@cloudscape-design/components/table";
import { useLocale } from "@/contexts/LocaleContext";
import { usePools } from "@/api/queries";
import { useContracts } from "@/api/queries";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import { PageHeader } from "@/components/PageHeader";
import { Chip } from "@/components/Chip";
import { PoolSources } from "./PoolSources";
import { SLIDE_UP, SPRING_DEFAULT } from "@/motion";
import { formatDateTime } from "@/utils/formatting";
import type { PoolStatus } from "@/types";

// 节点池是一张表：数字等宽右对齐，来源和引用它的契约是中性标签；停用的契约用弱色。
export function PoolsPage() {
  const { t } = useLocale();
  const pools = usePools();
  const contracts = useContracts();

  const getReferencingContracts = (poolId: string) => {
    if (!contracts.data) return [];
    return contracts.data.filter(
      (c) => c.primary_pools.includes(poolId) || c.fallback_pools.includes(poolId),
    );
  };

  return (
    <ContentLayout header={<PageHeader title={t("pools.title")} />}>
      <WorkspaceLoader loading={pools.isLoading} error={pools.error} onRetry={() => pools.refetch()}>
        <motion.div initial={SLIDE_UP.initial} animate={SLIDE_UP.animate} transition={SPRING_DEFAULT}>
          <Table<PoolStatus>
            items={pools.data ?? []}
            trackBy="id"
            wrapLines
            cellVerticalAlign="top"
            columnDefinitions={[
              {
                id: "name",
                header: t("common.name"),
                minWidth: 160,
                cell: (pool) => (
                  <div className="s-cell-stack">
                    <span className="s-cell-title">{pool.display_name}</span>
                    {pool.pseudo ? <span className="s-cell-label">{t("pools.pseudo")}</span> : null}
                  </div>
                ),
              },
              { id: "node_count", header: t("pools.node_count"), minWidth: 96, cell: (pool) => <span className="s-num">{pool.node_count}</span> },
              { id: "renderable", header: t("pools.renderable"), minWidth: 96, cell: (pool) => <span className="s-num">{pool.renderable_node_count}</span> },
              {
                id: "sources",
                header: t("pools.sources"),
                minWidth: 200,
                cell: (pool) => <PoolSources sources={pool.sources} />,
              },
              {
                id: "referenced_by",
                header: t("pools.referenced_by"),
                minWidth: 200,
                cell: (pool) => {
                  const refs = getReferencingContracts(pool.id);
                  return refs.length === 0 ? <span className="s-muted">-</span> : (
                    <div className="s-chips">
                      {refs.map((c) => <Chip key={c.id} muted={!c.enabled} title={c.enabled ? undefined : t("common.disabled")}>{c.display_name}</Chip>)}
                    </div>
                  );
                },
              },
              { id: "last_refresh", header: t("pools.last_refresh"), minWidth: 170, cell: (pool) => <span className="s-num">{formatDateTime(pool.last_refresh_at)}</span> },
            ]}
            empty={<div className="s-empty">{t("pools.no_pools")}</div>}
          />
        </motion.div>
      </WorkspaceLoader>
    </ContentLayout>
  );
}
