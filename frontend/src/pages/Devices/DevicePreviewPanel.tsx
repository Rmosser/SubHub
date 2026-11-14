import { useEffect, useMemo, useState } from "react";
import {
  Select,
  SpaceBetween,
  Box,
  FormField,
  Textarea,
  Table,
} from "@cloudscape-design/components";
import { useLocale } from "@/contexts/LocaleContext";
import { useDevicePreview, usePreviewSummary, usePreviewContent } from "@/api/queries";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import { StatusBadge, type StatusKind } from "@/components/StatusBadge";
import { Facts } from "@/components/Facts";
import { Chip } from "@/components/Chip";
import { PaperNote } from "@/components/PaperNote";
import { GlassTabs } from "@/components/GlassTabs";
import { CLIENT_TARGET_OPTIONS } from "@/constants/clients";
import type { ClientTarget } from "@/constants/clients";
import type { DeviceLinks, DeviceWithLinks } from "@/types";
import { isRecord } from "@/api/validators/shared";
import { severityLabel } from "@/utils/statusText";

interface DevicePreviewPanelProps {
  device: DeviceWithLinks;
  initialTarget?: ClientTarget;
}

function getRecommendedDeviceLink(links: DeviceLinks) {
  for (const target of ["surge", "clash", "shadowrocket"] as const) {
    const key = `${target}_url`;
    const url = String(links[key] || "").trim();
    if (url) {
      return { target, url };
    }
  }
  return null;
}

function getRecommendedPreviewTarget(links: DeviceLinks): ClientTarget | null {
  return getRecommendedDeviceLink(links)?.target ?? null;
}

function readPreviewSummaryMetrics(raw: unknown) {
  const payload = isRecord(raw) ? raw : {};
  const summary = isRecord(payload.summary) ? payload.summary : {};

  return {
    nodeCount: typeof summary.node_count === "number" ? summary.node_count : 0,
    ruleLineCount: typeof summary.rule_line_count === "number" ? summary.rule_line_count : 0,
    generalProfileName: typeof summary.general_profile_name === "string" ? summary.general_profile_name : "",
    contractCount: Array.isArray(summary.contracts) ? summary.contracts.length : 0,
    skippedCount: typeof summary.skipped_count === "number" ? summary.skipped_count : 0,
  };
}

export function DevicePreviewPanel({ device, initialTarget }: DevicePreviewPanelProps) {
  const { locale, t } = useLocale();
  const suggestedTarget = useMemo(() => initialTarget ?? getRecommendedPreviewTarget(device.links), [device.links, initialTarget]);
  const [target, setTarget] = useState<ClientTarget | null>(suggestedTarget);

  useEffect(() => {
    setTarget(suggestedTarget);
  }, [device.subscription_id, suggestedTarget]);

  const preview = useDevicePreview(device.subscription_id, target);
  const summary = usePreviewSummary(device.subscription_id, target);
  const content = usePreviewContent(device.subscription_id, target);
  const previewData = preview.data;
  const summaryMetrics = readPreviewSummaryMetrics(summary.data);
  const errorCount = previewData?.diagnostics.filter((item) => item.severity === "error").length ?? 0;
  const warningCount = previewData?.diagnostics.filter((item) => item.severity !== "error").length ?? 0;

  const previewState: { kind: StatusKind; label: string } = preview.isLoading
    ? { kind: "loading", label: t("common.loading") }
    : preview.error || !previewData
      ? { kind: "error", label: t("devices.preview_failed") }
      : previewData.blocked
        ? { kind: "error", label: t("devices.preview_blocked") }
        : errorCount + warningCount > 0
          ? { kind: "warning", label: t("devices.preview_with_diagnostics") }
          : { kind: "success", label: t("devices.preview_ready") };

  return (
    <SpaceBetween size="l">
      <div className="s-settings-grid">
        <FormField label={t("devices.target")}>
          <Select
            ariaLabel={t("devices.target")}
            selectedOption={CLIENT_TARGET_OPTIONS.find((o) => o.value === target) || null}
            options={CLIENT_TARGET_OPTIONS}
            placeholder={locale === "zh-CN" ? "先选择客户端" : "Choose a target client"}
            onChange={({ detail }) => setTarget((detail.selectedOption.value || null) as ClientTarget | null)}
          />
        </FormField>
      </div>

      {target ? (
        <SpaceBetween size="l">
          <Facts
            items={[
              { label: t("devices.preview_status"), value: <StatusBadge status={previewState.kind}>{previewState.label}</StatusBadge> },
              { label: t("devices.preview_scenario"), value: previewData?.scenario_name || summaryMetrics.generalProfileName || "-" },
              { label: t("devices.preview_assets"), value: `${previewData?.asset_counts.domain_sets ?? 0} / ${previewData?.asset_counts.rule_sets ?? 0}` },
              { label: t("devices.preview_diagnostic_count"), value: `${errorCount} / ${warningCount}` },
            ]}
          />

          <GlassTabs
            ariaLabel={t("devices.preview_panel")}
            tabs={[
              {
                id: "summary",
                label: t("devices.summary"),
                content: (
                  <WorkspaceLoader loading={preview.isLoading || summary.isLoading} error={preview.error ?? summary.error} onRetry={() => { void Promise.all([preview.refetch(), summary.refetch()]); }}>
                    <div className="s-stack">
                      <Facts
                        items={[
                          { label: t("devices.node_count"), value: summaryMetrics.nodeCount },
                          { label: t("devices.rule_line_count"), value: summaryMetrics.ruleLineCount },
                          { label: t("devices.contract_count"), value: summaryMetrics.contractCount },
                          { label: t("devices.skipped_items"), value: summaryMetrics.skippedCount },
                        ]}
                      />
                      {previewData?.blocked ? (
                        <PaperNote>{t("devices.preview_blocked_help")}</PaperNote>
                      ) : null}
                    </div>
                  </WorkspaceLoader>
                ),
              },
              {
                id: "content",
                label: t("devices.content"),
                content: (
                  <WorkspaceLoader loading={content.isLoading} error={content.error} onRetry={() => content.refetch()}>
                    {content.data && (
                      <SpaceBetween size="xs">
                        <Box fontSize="body-s" color="text-body-secondary">
                          {content.data.lineCount} {t("devices.lines")} / {content.data.charCount} {t("devices.chars")}
                        </Box>
                        <Textarea
                          ariaLabel={t("devices.content")}
                          value={content.data.text}
                          readOnly
                          rows={20}
                        />
                      </SpaceBetween>
                    )}
                  </WorkspaceLoader>
                ),
              },
              {
                id: "diagnostics",
                label: t("devices.diagnostics"),
                content: (
                  <WorkspaceLoader loading={preview.isLoading} error={preview.error} onRetry={() => preview.refetch()}>
                    {previewData && (
                      <SpaceBetween size="l">
                        {previewData.diagnostics.length > 0 ? (
                          <Table
                            variant="embedded"
                            items={previewData.diagnostics}
                            columnDefinitions={[
                              { id: "code", header: t("devices.col_code"), cell: (d) => <span className="s-mono">{d.code}</span> },
                              { id: "severity", header: t("devices.col_severity"), cell: (d) => <StatusBadge status={d.severity === "error" ? "error" : "warning"}>{severityLabel(d.severity, t)}</StatusBadge> },
                              { id: "message", header: t("devices.col_message"), cell: (d) => d.message },
                              { id: "target", header: t("devices.col_target"), cell: (d) => d.target || "-" },
                            ]}
                          />
                        ) : <StatusBadge status="success">{t("devices.no_diagnostics")}</StatusBadge>}
                        <section className="s-section">
                          <Box variant="h4">{t("devices.blockers")}</Box>
                          {previewData.blockers.length > 0 ? (
                            <Table
                              variant="embedded"
                              items={previewData.blockers}
                              columnDefinitions={[
                                { id: "code", header: t("devices.col_code"), cell: (d) => <span className="s-mono">{d.code}</span> },
                                { id: "message", header: t("devices.col_message"), cell: (d) => d.message },
                              ]}
                            />
                          ) : (
                            <span className="s-muted">{t("devices.none")}</span>
                          )}
                        </section>
                        <section className="s-section">
                          <Box variant="h4">{t("devices.skipped_items")}</Box>
                          {previewData.skipped.length > 0 ? (
                            <div className="s-chips">
                              {previewData.skipped.map((s, i) => <Chip key={i} mono>{s}</Chip>)}
                            </div>
                          ) : (
                            <span className="s-muted">{t("devices.none")}</span>
                          )}
                        </section>
                      </SpaceBetween>
                    )}
                  </WorkspaceLoader>
                ),
              },
            ]}
          />
        </SpaceBetween>
      ) : null}
    </SpaceBetween>
  );
}
