import { useEffect, useMemo, useState } from "react";
import {
  Button,
  ExpandableSection,
  FormField,
  Input,
  SpaceBetween,
  Textarea,
} from "@cloudscape-design/components";
import { Section, Surface } from "@/components/Section";
import { Facts } from "@/components/Facts";
import { PaperNote } from "@/components/PaperNote";
import { ReasonText } from "@/components/ReasonText";
import { WorkflowStatus } from "./WorkflowStatus";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useApplyLlmImport, useExportLlmWorkflow, usePreviewLlmImport } from "@/api/mutations";
import { parseJsonValue } from "@/api/validators/json";
import { isRecord } from "@/api/validators/shared";
import { WorkflowChangesTable } from "./WorkflowChangesTable";
import type { LlmWorkflowExport, LlmWorkflowId, LlmWorkflowInvalidItem, LlmWorkflowPreview } from "@/types";

interface WorkflowPanelProps {
  workflowType: LlmWorkflowId;
}

function formatInvalidItems(items: LlmWorkflowInvalidItem[]) {
  return items.map((item) => `${item.name} (${item.reason})`).join(", ");
}

function summarizeNames(items: string[], emptyText: string) {
  return items.length > 0 ? items.join(", ") : emptyText;
}

export function WorkflowPanel({ workflowType }: WorkflowPanelProps) {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const exportWorkflow = useExportLlmWorkflow();
  const previewImport = usePreviewLlmImport();
  const applyImport = useApplyLlmImport();

  const [intentOverride, setIntentOverride] = useState("");
  const [sampleLimit, setSampleLimit] = useState("10");
  const [exportResult, setExportResult] = useState<LlmWorkflowExport | null>(null);
  const [importJson, setImportJson] = useState("");
  const [preview, setPreview] = useState<LlmWorkflowPreview | null>(null);
  const [previewResult, setPreviewResult] = useState<Record<string, unknown> | null>(null);
  const [selectedChangeIds, setSelectedChangeIds] = useState<string[]>([]);
  const [statusVariant, setStatusVariant] = useState<"info" | "success" | "warning" | "error">("info");
  const [statusTitle, setStatusTitle] = useState<string>(t("llm.state_export_required"));
  const [statusBody, setStatusBody] = useState<string>(t("llm.state_export_required_help"));

  useEffect(() => {
    setIntentOverride("");
    setSampleLimit("10");
    setExportResult(null);
    setImportJson("");
    setPreview(null);
    setPreviewResult(null);
    setSelectedChangeIds([]);
    setStatusVariant("info");
    setStatusTitle(t("llm.state_export_required"));
    setStatusBody(t("llm.state_export_required_help"));
  }, [t, workflowType]);

  const exportJson = useMemo(
    () => (exportResult ? JSON.stringify(exportResult, null, 2) : ""),
    [exportResult],
  );
  const templatePreview = exportResult?.template || "";

  const clearPreviewState = () => {
    setPreview(null);
    setPreviewResult(null);
    setSelectedChangeIds([]);
  };

  const parseImportResult = () => {
    const parsed = parseJsonValue(importJson);
    if (!isRecord(parsed)) {
      throw new Error(t("llm.invalid_json_object"));
    }
    return parsed;
  };

  const handleExport = () => {
    exportWorkflow.mutate(
      {
        workflow_type: workflowType,
        intent_override: intentOverride || undefined,
        sample_rule_limit: sampleLimit ? Number(sampleLimit) : undefined,
      },
      {
        onSuccess: (data) => {
          setExportResult(data);
          setImportJson("");
          clearPreviewState();
          setStatusVariant("success");
          setStatusTitle(t("llm.state_export_ready"));
          setStatusBody(t("llm.state_export_ready_help"));
          addToast("success", t("llm.export_ready"));
        },
        onError: (err) => {
          setStatusVariant("error");
          setStatusTitle(t("llm.state_run_failed"));
          setStatusBody(err.message);
          addToast("error", t("llm.export_failed"), err.message);
        },
      },
    );
  };

  const handlePreview = () => {
    if (!exportResult) {
      setStatusVariant("warning");
      setStatusTitle(t("llm.state_export_required"));
      setStatusBody(t("llm.preview_requires_export"));
      addToast("warning", t("llm.preview_requires_export"));
      return;
    }
    let result: Record<string, unknown>;
    try {
      result = parseImportResult();
    } catch (error) {
      const message = error instanceof Error ? error.message : t("llm.invalid_json_object");
      setStatusVariant("error");
      setStatusTitle(t("llm.state_run_failed"));
      setStatusBody(message);
      addToast("error", message);
      return;
    }

    previewImport.mutate(
      {
        workflow_type: workflowType,
        snapshot_fingerprint: exportResult.snapshot_fingerprint,
        result,
      },
      {
        onSuccess: (nextPreview) => {
          setPreview(nextPreview);
          setPreviewResult(result);
          setSelectedChangeIds(nextPreview.changes.map((item) => item.change_id));
          setStatusVariant(nextPreview.changes.length > 0 ? "success" : "info");
          setStatusTitle(nextPreview.changes.length > 0 ? t("llm.state_apply_ready") : t("llm.state_no_changes"));
          setStatusBody(
            nextPreview.changes.length > 0
              ? t("llm.state_apply_ready_help", { count: nextPreview.changes.length })
              : t("llm.no_changes"),
          );
        },
        onError: (err) => {
          const message =
            err.message.includes("snapshot drifted") ? t("llm.snapshot_drifted") : t("llm.preview_failed");
          setStatusVariant(err.message.includes("snapshot drifted") ? "warning" : "error");
          setStatusTitle(err.message.includes("snapshot drifted") ? t("llm.state_snapshot_drift") : t("llm.state_run_failed"));
          setStatusBody(message);
          addToast("error", message, err.message);
        },
      },
    );
  };

  const handleToggle = (changeId: string) => {
    setSelectedChangeIds((prev) =>
      prev.includes(changeId) ? prev.filter((item) => item !== changeId) : [...prev, changeId],
    );
  };

  const handleApply = () => {
    if (!exportResult || !previewResult || !preview) {
      return;
    }
    applyImport.mutate(
      {
        workflow_type: workflowType,
        snapshot_fingerprint: exportResult.snapshot_fingerprint,
        result: previewResult,
        selected_change_ids: selectedChangeIds,
      },
      {
        onSuccess: (data) => {
          addToast("success", t("llm.apply_success"), `${t("llm.applied_count")}: ${data.applied}`);
          setImportJson("");
          clearPreviewState();
          setStatusVariant("success");
          setStatusTitle(t("llm.state_applied"));
          setStatusBody(t("llm.state_applied_help", { count: data.applied }));
        },
        onError: (err) => {
          const message =
            err.message.includes("snapshot drifted") ? t("llm.snapshot_drifted") : t("llm.apply_failed");
          setStatusVariant(err.message.includes("snapshot drifted") ? "warning" : "error");
          setStatusTitle(err.message.includes("snapshot drifted") ? t("llm.state_snapshot_drift") : t("llm.state_run_failed"));
          setStatusBody(message);
          addToast("error", message, err.message);
        },
      },
    );
  };

  const handleImportChange = (value: string) => {
    setImportJson(value);
    if (preview) {
      clearPreviewState();
    }
    if (exportResult) {
      setStatusVariant("info");
      setStatusTitle(t("llm.state_preview_ready"));
      setStatusBody(t("llm.state_preview_ready_help"));
    }
  };

  return (
    <SpaceBetween size="xl">
      <WorkflowStatus variant={statusVariant} title={statusTitle} body={statusBody} />

      <Section
        title={t("llm.export")}
        actions={
          <Button variant={exportResult ? "normal" : "primary"} onClick={handleExport} loading={exportWorkflow.isPending}>
            {exportWorkflow.isPending ? t("llm.generating") : t("llm.generate")}
          </Button>
        }
      >
        <Surface>
          <div className="s-stack">
            <FormField label={t("llm.intent_override")}>
              <Input
                value={intentOverride}
                onChange={({ detail }) => setIntentOverride(detail.value)}
                placeholder={t("llm.intent_override_placeholder")}
              />
            </FormField>
            <ExpandableSection headerText={t("llm.default_prompt_section")}>
              <SpaceBetween size="m">
                <FormField label={t("llm.sample_limit")}>
                  <Input
                    type="number"
                    value={sampleLimit}
                    onChange={({ detail }) => setSampleLimit(detail.value)}
                  />
                </FormField>
                <FormField label={t("llm.default_prompt_label")}>
                  <Textarea value={templatePreview || t("llm.default_prompt_empty")} readOnly rows={8} />
                </FormField>
              </SpaceBetween>
            </ExpandableSection>
            {exportResult ? <Textarea ariaLabel={t("llm.export")} value={exportJson} readOnly rows={16} /> : null}
          </div>
        </Surface>
      </Section>

      <Section
        title={t("llm.import")}
        actions={
          <>
            <Button
              onClick={handlePreview}
              loading={previewImport.isPending}
              disabled={!exportResult || !importJson.trim()}
            >
              {t("llm.preview")}
            </Button>
            <Button
              variant="primary"
              onClick={handleApply}
              loading={applyImport.isPending}
              disabled={!preview || !previewResult}
            >
              {t("llm.apply")}
            </Button>
          </>
        }
      >
        <Surface>
          <div className="s-stack">
            <Textarea
              ariaLabel={t("llm.import")}
              value={importJson}
              onChange={({ detail }) => handleImportChange(detail.value)}
              rows={8}
              placeholder={t("llm.import_placeholder")}
            />

            {preview && (
              <>
                <Facts
                  compact
                  items={[
                    { label: t("llm.changes"), value: preview.changes.length },
                    { label: t("llm.selected_changes"), value: selectedChangeIds.length },
                    { label: t("llm.invalid_items"), value: preview.invalid_items.length },
                    { label: t("llm.skipped_locked"), value: preview.skipped_locked.length },
                    { label: t("llm.skipped_unchanged"), value: preview.skipped_unchanged.length },
                  ]}
                />

                {preview.invalid_items.length > 0 && (
                  <PaperNote>
                    <strong>{t("llm.invalid_items")}</strong>
                    <ReasonText text={formatInvalidItems(preview.invalid_items)} />
                  </PaperNote>
                )}

                {preview.skipped_locked.length > 0 && (
                  <div className="s-reason">
                    <strong>{t("llm.skipped_locked")}</strong>{" "}
                    <ReasonText text={summarizeNames(preview.skipped_locked, t("common.no_items"))} />
                  </div>
                )}

                {preview.skipped_unchanged.length > 0 && (
                  <div className="s-reason">
                    <strong>{t("llm.skipped_unchanged")}</strong>{" "}
                    <ReasonText text={summarizeNames(preview.skipped_unchanged, t("common.no_items"))} />
                  </div>
                )}

                {preview.changes.length > 0 ? (
                  <WorkflowChangesTable
                    workflowType={workflowType}
                    changes={preview.changes}
                    selectedChangeIds={selectedChangeIds}
                    onToggle={handleToggle}
                  />
                ) : null}
              </>
            )}
          </div>
        </Surface>
      </Section>
    </SpaceBetween>
  );
}
