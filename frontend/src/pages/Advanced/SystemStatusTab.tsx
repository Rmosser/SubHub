import { SpaceBetween, Table } from "@cloudscape-design/components";
import { useDevices, usePools, useStatus } from "@/api/queries";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import { StatusBadge, type StatusKind } from "@/components/StatusBadge";
import { Facts } from "@/components/Facts";
import { Chip } from "@/components/Chip";
import { PaperNote } from "@/components/PaperNote";
import { ReasonText } from "@/components/ReasonText";
import { Section, Surface } from "@/components/Section";
import { useLocale } from "@/contexts/LocaleContext";
import { formatDateTime } from "@/utils/formatting";
import { overlayReasonText, overlayStatusKind, proxyBridgeLabel } from "@/utils/statusText";
import { PoolSources } from "@/pages/Pools/PoolSources";
import type { DeviceWithLinks, PoolStatus } from "@/types";

// 严重级别对应语义状态色：警告不再借用信息蓝。
function severityKind(severity: string): StatusKind {
  if (severity === "error") return "error";
  if (severity === "warning") return "warning";
  return "success";
}

function poolStatusKind(item: PoolStatus): StatusKind {
  if (item.renderable_node_count === 0) return "error";
  if (item.renderable_node_count < item.node_count) return "warning";
  return "success";
}

function scenarioOverlayStatus(devices: DeviceWithLinks[]) {
  // parseDeviceListResponse verifies every device has the same selected-scenario snapshot.
  return devices.length > 0 ? devices[0].overlay_status : null;
}

export function SystemStatusTab() {
  const { t } = useLocale();
  const status = useStatus();
  const pools = usePools();
  const devices = useDevices();
  const loading = status.isLoading || pools.isLoading || devices.isLoading;
  const error = status.error ?? pools.error ?? devices.error;
  const content = status.data && pools.data && devices.data
    ? {
        status: status.data,
        pools: pools.data,
        devices: devices.data,
      }
    : null;
  const overlayStatus = content ? scenarioOverlayStatus(content.devices) : null;
  const proxyCode = content?.status.egress.proxy_bridge.code ?? "";
  const proxyKind = severityKind(content?.status.egress.proxy_bridge.severity ?? "");

  return (
    <WorkspaceLoader
      loading={loading}
      error={error}
      onRetry={() => {
        void Promise.all([status.refetch(), pools.refetch(), devices.refetch()]);
      }}
    >
      {content && (
        <SpaceBetween size="xxl">
          <Surface>
            <div className="s-stack">
              <Facts
                items={[
                  { label: t("advanced.status_last_refresh"), value: formatDateTime(content.status.hub_runtime.last_refresh_at) },
                  { label: t("sources.standard"), value: content.status.source_summary.standard_count },
                  { label: t("sources.gorelay"), value: content.status.source_summary.gorelay_count },
                  { label: t("advanced.status_expired_sources"), value: content.status.source_summary.standard_expired },
                  { label: t("advanced.status_failed_sources"), value: content.status.source_summary.standard_failed },
                ]}
              />
              {content.status.hub_runtime.last_error ? (
                <div className="s-error">
                  <StatusBadge status="error">{t("advanced.status_runtime_error")}</StatusBadge>
                  <ReasonText text={content.status.hub_runtime.last_error} lines={3} />
                </div>
              ) : (
                <StatusBadge status="success">{t("advanced.status_runtime_ok")}</StatusBadge>
              )}
            </div>
          </Surface>

          <Section title={t("advanced.status_proxy_bridge")}>
            <Surface>
              <div className="s-stack">
                <div className="s-chips">
                  <StatusBadge status={proxyKind}>
                    {proxyBridgeLabel(proxyCode, t) ?? (
                      <>
                        {proxyKind === "success" ? t("advanced.status_ok") : t("advanced.status_attention")}
                        {proxyCode ? <span className="s-mono s-muted"> {proxyCode}</span> : null}
                      </>
                    )}
                  </StatusBadge>
                  {!content.status.egress.proxy_bridge.required && <Chip muted>{t("advanced.status_optional")}</Chip>}
                </div>
                {content.status.egress.proxy_bridge.summary || content.status.egress.proxy_bridge.meaning ? (
                  <div className="s-cell-stack">
                    {content.status.egress.proxy_bridge.summary ? <span>{content.status.egress.proxy_bridge.summary}</span> : null}
                    {content.status.egress.proxy_bridge.meaning ? <span className="s-muted">{content.status.egress.proxy_bridge.meaning}</span> : null}
                  </div>
                ) : null}
                {content.status.egress.proxy_bridge.repair_hint ? (
                  <PaperNote>{content.status.egress.proxy_bridge.repair_hint}</PaperNote>
                ) : null}
                {content.status.egress.proxy_bridge.actions.length > 0 && (
                  <div className="s-cell-stack">
                    <span className="s-cell-label">{t("advanced.status_repair_actions")}</span>
                    <ol className="s-ordered">
                      {content.status.egress.proxy_bridge.actions.map((action, index) => (
                        <li key={`${action}-${index}`}>{action}</li>
                      ))}
                    </ol>
                  </div>
                )}
                {content.status.egress.proxy_bridge.last_error && (
                  <div className="s-reason s-err-text">
                    <ReasonText text={content.status.egress.proxy_bridge.last_error} lines={3} />
                  </div>
                )}
              </div>
            </Surface>
          </Section>

          <Section title={t("advanced.status_pools")}>
            <Table
              items={content.pools}
              wrapLines
              columnDefinitions={[
                { id: "name", header: t("common.name"), cell: (item) => item.display_name },
                {
                  id: "status",
                  header: t("pools.renderable"),
                  // 伪池（直连）没有节点是常态，不给状态色
                  cell: (item) => item.pseudo ? <span className="s-muted">{t("pools.pseudo")}</span> : (
                    <StatusBadge status={poolStatusKind(item)}>
                      <span className="s-num">{item.renderable_node_count}/{item.node_count}</span>
                    </StatusBadge>
                  ),
                },
                {
                  id: "sources",
                  header: t("pools.sources"),
                  cell: (item) => <PoolSources sources={item.sources} />,
                },
                { id: "last_refresh", header: t("pools.last_refresh"), cell: (item) => <span className="s-num">{formatDateTime(item.last_refresh_at)}</span> },
              ]}
              empty={<div className="s-empty">{t("pools.no_pools")}</div>}
            />
          </Section>

          <Section title={t("advanced.status_overlay")}>
            <Surface>
              {overlayStatus ? (
                <Facts
                  items={[
                    {
                      label: t("common.status"),
                      value: (
                        <StatusBadge status={overlayStatusKind(overlayStatus)}>
                          {overlayStatus.available ? t("advanced.status_ok") : t("advanced.status_attention")}
                        </StatusBadge>
                      ),
                    },
                    { label: t("advanced.status_reason"), value: <ReasonText text={overlayReasonText(overlayStatus, t) || "-"} /> },
                    {
                      label: t("advanced.status_renderable_rules"),
                      value: `${overlayStatus.renderable_process_rule_count} / ${overlayStatus.renderable_external_proxy_program_count}`,
                    },
                  ]}
                />
              ) : (
                <StatusBadge status="stopped">{t("advanced.status_overlay_unavailable")}</StatusBadge>
              )}
            </Surface>
          </Section>
        </SpaceBetween>
      )}
    </WorkspaceLoader>
  );
}
