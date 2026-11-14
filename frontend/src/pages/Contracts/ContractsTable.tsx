import { SpaceBetween, Table } from "@cloudscape-design/components";
import { Chip } from "@/components/Chip";
import { IconAction } from "@/components/InlineAction";
import { useLocale } from "@/contexts/LocaleContext";
import { useScenario } from "@/contexts/ScenarioContext";
import { useCoarsePointer } from "@/hooks/useMediaQuery";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime } from "@/utils/formatting";
import type { RouteContract } from "@/types";
import "@/styles/contracts-table.css";

interface ContractsTableProps {
  items: RouteContract[];
  loading: boolean;
  onEdit: (contract: RouteContract) => void;
  onDelete: (contract: RouteContract) => void;
}

function routingActionLabel(action: RouteContract["routing_action"], translate: (key: string) => string) {
  return translate(`contracts.routing_action_${action}`);
}

// 路由动作是唯一需要一眼区分的类别：代理、直连、拦截各带一个淡色点；其余属性是弱文字。
const ROUTING_DOT = { proxy: "flow", direct: "teal", reject: "warm" } as const;

export function ContractsTable({ items, loading, onEdit, onDelete }: ContractsTableProps) {
  const { t } = useLocale();
  const { selectedScenarioId } = useScenario();
  // 列宽调整柄在触屏上只有 24×36、靠拖动，手指用不了：触屏不开，鼠标设备保持可调
  const coarsePointer = useCoarsePointer();

  const canDelete = (item: RouteContract) => {
    if (item.scope === "scenario") {
      return item.owner_scenario_id === selectedScenarioId;
    }
    return selectedScenarioId === "scenario-default";
  };

  return (
    <div className="contracts-table-shell">
      <Table
        items={items}
        loading={loading}
        loadingText={t("common.loading")}
        trackBy="id"
        wrapLines
        resizableColumns={!coarsePointer}
        cellVerticalAlign="top"
        columnDefinitions={[
          {
            id: "contract",
            header: t("contracts.contract"),
            minWidth: 200,
            width: 240,
            cell: (item) => (
              <div className="contracts-table__stack">
                <div className="contracts-table__contract-name">{item.display_name}</div>
                <div className="contracts-table__badge-wrap">
                  <Chip dot={ROUTING_DOT[item.routing_action || "proxy"] ?? "flow"}>
                    {routingActionLabel(item.routing_action || "proxy", t)}
                  </Chip>
                  {item.is_default ? <Chip lit>{t("contracts.default")}</Chip> : null}
                </div>
                <div className="contracts-table__meta">
                  <span>{item.scope === "scenario" ? t("contracts.scope_scenario") : t("contracts.scope_global")}</span>
                  {(item.routing_action || "proxy") === "proxy" ? (
                    <>
                      <span>{item.strategy_type}</span>
                      <span>{item.failure_action}</span>
                    </>
                  ) : null}
                </div>
              </div>
            ),
            sortingField: "display_name",
          },
          {
            id: "intent_description",
            header: t("contracts.intent_description"),
            minWidth: 240,
            width: 300,
            cell: (item) => (
              <div className="contracts-table__stack">
                {item.llm_routing_intent ? (
                  <div className="contracts-table__field-block">
                    <div className="contracts-table__field-label">{t("contracts.llm_intent")}</div>
                    <div className="contracts-table__multiline">{item.llm_routing_intent}</div>
                  </div>
                ) : null}
                {item.description && item.description !== item.llm_routing_intent ? (
                  <div className="contracts-table__field-block">
                    <div className="contracts-table__field-label">{t("common.description")}</div>
                    <div className="contracts-table__multiline">{item.description}</div>
                  </div>
                ) : null}
                {!item.llm_routing_intent && !item.description ? <span className="s-muted">-</span> : null}
              </div>
            ),
          },
          {
            id: "pool_topology",
            header: t("contracts.pool_topology"),
            minWidth: 200,
            width: 250,
            cell: (item) => (
              <div className="contracts-table__stack">
                {item.primary_pool_display_names.length > 0 ? (
                  <div className="contracts-table__field-block">
                    <div className="contracts-table__field-label">{t("contracts.primary_pools")}</div>
                    <div className="contracts-table__badge-wrap">
                      {item.primary_pool_display_names.map((name, index) => (
                        <Chip key={`${name}-${index}`}>{name}</Chip>
                      ))}
                    </div>
                  </div>
                ) : null}
                {item.fallback_pool_display_names.length > 0 ? (
                  <div className="contracts-table__field-block">
                    <div className="contracts-table__field-label">{t("contracts.fallback_pools")}</div>
                    <div className="contracts-table__badge-wrap">
                      {item.fallback_pool_display_names.map((name, index) => (
                        <Chip key={`${name}-${index}`} muted>{name}</Chip>
                      ))}
                    </div>
                  </div>
                ) : null}
                {item.primary_pool_display_names.length === 0 && item.fallback_pool_display_names.length === 0 ? (
                  <span className="s-muted">-</span>
                ) : null}
              </div>
            ),
          },
          {
            id: "status",
            header: t("common.status"),
            minWidth: 100,
            width: 110,
            cell: (item) => (
              <StatusBadge status={item.enabled ? "success" : "stopped"}>
                {item.enabled ? t("common.enabled") : t("common.disabled")}
              </StatusBadge>
            ),
          },
          {
            id: "updated_at",
            header: t("common.updated_at"),
            minWidth: 150,
            width: 170,
            cell: (item) => formatDateTime(item.updated_at),
            sortingField: "updated_at",
          },
          {
            id: "actions",
            header: t("common.actions"),
            minWidth: 84,
            width: 92,
            cell: (item) => (
              <SpaceBetween direction="horizontal" size="xs">
                <IconAction
                  iconName="edit"
                  ariaLabel={`${t("common.edit")} ${item.display_name}`}
                  onClick={() => onEdit(item)}
                />
                {canDelete(item) ? (
                  <IconAction
                    iconName="remove"
                    ariaLabel={`${t("common.delete")} ${item.display_name}`}
                    onClick={() => onDelete(item)}
                  />
                ) : null}
              </SpaceBetween>
            ),
          },
        ]}
        sortingDisabled={false}
        empty={<div className="s-empty">{t("common.no_items")}</div>}
      />
    </div>
  );
}
