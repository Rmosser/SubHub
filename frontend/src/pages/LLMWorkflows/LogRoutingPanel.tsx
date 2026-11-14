import { useEffect, useId, useMemo, useState } from "react";
import {
  Button,
  FormField,
  Input,
  SpaceBetween,
  Table,
  Textarea,
} from "@cloudscape-design/components";
import { Section, Surface } from "@/components/Section";
import { Facts } from "@/components/Facts";
import { PaperNote } from "@/components/PaperNote";
import { ReasonText } from "@/components/ReasonText";
import { Chip } from "@/components/Chip";
import { CopyButton } from "@/components/CopyButton";
import { WorkflowStatus } from "./WorkflowStatus";
import { useApplyLogRoutingPatch, useCreateLogRoutingSession, useExportLogRoutingSession, useUploadLogRoutingFile, usePreviewLogRoutingPatch } from "@/api/mutations";
import { useLogRoutingCandidates } from "@/api/queries";
import { parseJsonValue } from "@/api/validators/json";
import { isRecord } from "@/api/validators/shared";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { LogRoutingChangesTable } from "./LogRoutingChangesTable";
import type { LogRoutingExport, LogRoutingPreview } from "@/types";

function summarizeList(items: string[], emptyText: string) {
  return items.length > 0 ? items.join(", ") : emptyText;
}

export function LogRoutingPanel() {
  const { t } = useLocale();
  const uploadId = useId();
  const { addToast } = useNotifications();
  const createSession = useCreateLogRoutingSession();
  const uploadFile = useUploadLogRoutingFile();
  const exportSession = useExportLogRoutingSession();
  const previewPatch = usePreviewLogRoutingPatch();
  const applyPatch = useApplyLogRoutingPatch();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [intentOverride, setIntentOverride] = useState("");
  const [sampleLimit, setSampleLimit] = useState("3");
  const [exportResult, setExportResult] = useState<LogRoutingExport | null>(null);
  const [patchJson, setPatchJson] = useState("");
  const [preview, setPreview] = useState<LogRoutingPreview | null>(null);
  const [previewPatchPayload, setPreviewPatchPayload] = useState<Record<string, unknown> | null>(null);
  const [selectedActionIds, setSelectedActionIds] = useState<string[]>([]);
  const [sessionInitAttempted, setSessionInitAttempted] = useState(false);
  const [statusVariant, setStatusVariant] = useState<"info" | "success" | "warning" | "error">("info");
  const [statusTitle, setStatusTitle] = useState<string>(t("llm.log_state_session_start"));
  const [statusBody, setStatusBody] = useState<string>(t("llm.log_state_session_start_help"));

  const candidates = useLogRoutingCandidates(sessionId);

  useEffect(() => {
    if (sessionId || createSession.isPending || sessionInitAttempted) {
      return;
    }
    setSessionInitAttempted(true);
    createSession.mutate(undefined, {
      onSuccess: (data) => {
        setSessionId(data.session_id);
        setStatusVariant("info");
        setStatusTitle(t("llm.log_state_upload_needed"));
        setStatusBody(t("llm.log_state_upload_needed_help"));
      },
      onError: (err) => {
        setStatusVariant("error");
        setStatusTitle(t("llm.state_run_failed"));
        setStatusBody(err.message);
        addToast("error", t("llm.log_session_create_failed"), err.message);
      },
    });
  }, [addToast, createSession, sessionId, sessionInitAttempted, t]);

  const exportJson = useMemo(() => (exportResult ? JSON.stringify(exportResult, null, 2) : ""), [exportResult]);

  const clearPreview = () => {
    setPreview(null);
    setPreviewPatchPayload(null);
    setSelectedActionIds([]);
  };

  const ensureSessionId = async () => {
    if (sessionId) {
      return sessionId;
    }
    const created = await createSession.mutateAsync();
    setSessionId(created.session_id);
    return created.session_id;
  };

  const handleUploadFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) {
      return;
    }
    const nextSessionId = await ensureSessionId();
    try {
      for (const file of Array.from(files)) {
        await uploadFile.mutateAsync({ sessionId: nextSessionId, file });
      }
      setStatusVariant("success");
      setStatusTitle(t("llm.log_state_upload_ready"));
      setStatusBody(t("llm.log_state_upload_ready_help"));
      addToast("success", t("llm.log_upload_success"));
    } catch (error) {
      const message = error instanceof Error ? error.message : t("llm.log_upload_failed");
      setStatusVariant("error");
      setStatusTitle(t("llm.state_run_failed"));
      setStatusBody(message);
      addToast("error", t("llm.log_upload_failed"), message);
    }
  };

  const handleExport = () => {
    if (!sessionId) {
      setStatusVariant("warning");
      setStatusTitle(t("llm.log_state_session_start"));
      setStatusBody(t("llm.log_state_session_start_help"));
      addToast("warning", t("llm.log_session_missing"));
      return;
    }
    exportSession.mutate(
      {
        sessionId,
        intent_override: intentOverride || undefined,
        sample_evidence_limit: sampleLimit ? Number(sampleLimit) : undefined,
      },
      {
        onSuccess: (data) => {
          setExportResult(data);
          setPatchJson("");
          clearPreview();
          setStatusVariant("success");
          setStatusTitle(t("llm.state_export_ready"));
          setStatusBody(t("llm.log_state_export_ready_help"));
          addToast("success", t("llm.log_export_success"));
        },
        onError: (err) => {
          setStatusVariant("error");
          setStatusTitle(t("llm.state_run_failed"));
          setStatusBody(err.message);
          addToast("error", t("llm.log_export_failed"), err.message);
        },
      },
    );
  };

  const parsePatch = () => {
    const parsed = parseJsonValue(patchJson);
    if (!isRecord(parsed)) {
      throw new Error(t("llm.invalid_json_object"));
    }
    return parsed;
  };

  const handlePreview = () => {
    if (!sessionId || !exportResult) {
      setStatusVariant("warning");
      setStatusTitle(t("llm.state_export_required"));
      setStatusBody(t("llm.log_export_required_help"));
      addToast("warning", t("llm.log_export_required"));
      return;
    }
    let patch: Record<string, unknown>;
    try {
      patch = parsePatch();
    } catch (error) {
      const message = error instanceof Error ? error.message : t("llm.invalid_json_object");
      setStatusVariant("error");
      setStatusTitle(t("llm.state_run_failed"));
      setStatusBody(message);
      addToast("error", message);
      return;
    }
    previewPatch.mutate(
      {
        sessionId,
        snapshot_id: exportResult.snapshot_id,
        patch,
      },
      {
        onSuccess: (data) => {
          setPreview(data);
          setPreviewPatchPayload(patch);
          setSelectedActionIds(data.changes.map((item) => item.id));
          setStatusVariant(data.blockers.length > 0 ? "warning" : "success");
          setStatusTitle(data.blockers.length > 0 ? t("llm.state_run_blocked") : t("llm.state_apply_ready"));
          setStatusBody(
            data.blockers.length > 0
              ? t("llm.log_state_blocked_help", { count: data.blockers.length })
              : t("llm.log_state_apply_ready_help", { count: data.changes.length }),
          );
        },
        onError: (err) => {
          const isDrift = err.message.includes("snapshot drifted");
          setStatusVariant(isDrift ? "warning" : "error");
          setStatusTitle(isDrift ? t("llm.state_snapshot_drift") : t("llm.state_run_failed"));
          setStatusBody(isDrift ? t("llm.snapshot_drifted") : err.message);
          addToast("error", isDrift ? t("llm.snapshot_drifted") : t("llm.log_preview_failed"), err.message);
        },
      },
    );
  };

  const handleApply = () => {
    if (!sessionId || !exportResult || !previewPatchPayload || !preview) {
      return;
    }
    applyPatch.mutate(
      {
        sessionId,
        snapshot_id: exportResult.snapshot_id,
        patch: previewPatchPayload,
        selected_action_ids: selectedActionIds,
      },
      {
        onSuccess: (data) => {
          setStatusVariant("success");
          setStatusTitle(t("llm.state_applied"));
          setStatusBody(t("llm.log_state_applied_help", { count: data.applied_count }));
          addToast("success", t("llm.log_apply_success"), `${t("llm.applied_count")}: ${data.applied_count}`);
          setPatchJson("");
          setExportResult(null);
          clearPreview();
        },
        onError: (err) => {
          const isDrift = err.message.includes("snapshot drifted");
          setStatusVariant(isDrift ? "warning" : "error");
          setStatusTitle(isDrift ? t("llm.state_snapshot_drift") : t("llm.state_run_failed"));
          setStatusBody(isDrift ? t("llm.snapshot_drifted") : err.message);
          addToast("error", isDrift ? t("llm.snapshot_drifted") : t("llm.log_apply_failed"), err.message);
        },
      },
    );
  };

  const handleToggle = (changeId: string) => {
    setSelectedActionIds((prev) =>
      prev.includes(changeId) ? prev.filter((item) => item !== changeId) : [...prev, changeId],
    );
  };

  return (
    <SpaceBetween size="xl">
      <WorkflowStatus variant={statusVariant} title={statusTitle} body={statusBody} />

      <Section
        title={t("llm.export")}
        actions={
          <Button variant={exportResult ? "normal" : "primary"} onClick={handleExport} loading={exportSession.isPending}>
            {exportSession.isPending ? t("llm.generating") : t("llm.generate")}
          </Button>
        }
      >
        <Surface>
          <div className="s-stack">
            <div className="s-row">
              <div className="s-grow">
                <FormField controlId={uploadId} label={t("llm.log_upload_label")}>
                  <input
                    id={uploadId}
                    className="s-file-input"
                    type="file"
                    multiple
                    onChange={(event) => {
                      void handleUploadFiles(event.target.files);
                      event.currentTarget.value = "";
                    }}
                  />
                </FormField>
              </div>
              <div className="s-grow">
                <FormField label={t("llm.intent_override")}>
                  <Input
                    value={intentOverride}
                    onChange={({ detail }) => setIntentOverride(detail.value)}
                    placeholder={t("llm.log_intent_placeholder")}
                  />
                </FormField>
              </div>
              <FormField label={t("llm.log_sample_limit")}>
                <Input type="number" value={sampleLimit} onChange={({ detail }) => setSampleLimit(detail.value)} />
              </FormField>
            </div>
            {(candidates.data?.files ?? []).length > 0 || candidates.isLoading || uploadFile.isPending ? (
              <Table
                variant="embedded"
                items={candidates.data?.files ?? []}
                columnDefinitions={[
                  { id: "filename", header: t("llm.log_file"), cell: (item) => item.filename },
                  { id: "client", header: t("llm.log_client"), cell: (item) => <Chip mono>{item.detected_client}</Chip> },
                  { id: "evidence", header: t("llm.log_evidence_count"), cell: (item) => <span className="s-num">{item.evidence_count}</span> },
                  { id: "candidates", header: t("llm.log_candidate_count"), cell: (item) => <span className="s-num">{item.candidate_count}</span> },
                ]}
                loading={candidates.isLoading || uploadFile.isPending}
                empty={<div className="s-empty">{t("llm.log_files_empty")}</div>}
              />
            ) : null}
            {(candidates.data?.candidates ?? []).length > 0 || candidates.isLoading ? (
              <Table
                variant="embedded"
                items={candidates.data?.candidates ?? []}
                wrapLines
                columnDefinitions={[
                  { id: "root_domain", header: t("llm.log_candidate_domain"), cell: (item) => <span className="s-mono">{item.root_domain}</span> },
                  { id: "hits", header: t("llm.log_fallback_hits"), cell: (item) => <span className="s-num">{item.fallback_hits}</span> },
                  { id: "hosts", header: t("llm.log_hosts"), cell: (item) => summarizeList(item.hosts.slice(0, 4), t("llm.empty_value")) },
                  { id: "existing", header: t("llm.log_existing_category"), cell: (item) => item.existing_category || t("llm.unassigned") },
                  {
                    id: "route",
                    header: t("llm.log_existing_route"),
                    cell: (item) => item.existing_route_display_name || item.existing_route || t("llm.unassigned"),
                  },
                  { id: "status", header: t("common.status"), cell: (item) => item.current_match_status },
                ]}
                loading={candidates.isLoading}
                empty={<div className="s-empty">{t("llm.log_candidates_empty")}</div>}
              />
            ) : null}
            {exportResult ? (
              <div className="s-export-json">
                <Textarea ariaLabel={t("llm.export")} value={exportJson} readOnly rows={16} />
                <CopyButton text={exportJson} label={t("llm.copy_export_json")} />
              </div>
            ) : null}
          </div>
        </Surface>
      </Section>

      <Section
        title={t("llm.import")}
        actions={
          <>
            <Button onClick={handlePreview} loading={previewPatch.isPending} disabled={!exportResult || !patchJson.trim()}>
              {t("llm.preview")}
            </Button>
            <Button
              variant="primary"
              onClick={handleApply}
              loading={applyPatch.isPending}
              disabled={!preview || !previewPatchPayload}
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
              value={patchJson}
              onChange={({ detail }) => {
                setPatchJson(detail.value);
                if (preview) {
                  clearPreview();
                }
                if (exportResult) {
                  setStatusVariant("info");
                  setStatusTitle(t("llm.state_preview_ready"));
                  setStatusBody(t("llm.log_preview_ready_help"));
                }
              }}
              rows={10}
              placeholder={t("llm.log_import_placeholder")}
            />

            {preview && (
              <>
                <Facts
                  compact
                  items={[
                    { label: t("llm.changes"), value: preview.changes.length },
                    { label: t("llm.selected_changes"), value: selectedActionIds.length },
                    { label: t("devices.diagnostics"), value: preview.warnings.length },
                    { label: t("devices.blockers"), value: preview.blockers.length },
                  ]}
                />

                {preview.blockers.length > 0 && (
                  <PaperNote>
                    <strong>{t("devices.blockers")}</strong>
                    <ReasonText text={preview.blockers.map((item) => item.message).join("\n")} lines={3} />
                  </PaperNote>
                )}

                {preview.warnings.length > 0 && (
                  <div className="s-reason">
                    <strong>{t("devices.diagnostics")}</strong>
                    <ReasonText text={preview.warnings.map((item) => item.message).join("\n")} lines={3} />
                  </div>
                )}

                <LogRoutingChangesTable
                  changes={preview.changes}
                  selectedActionIds={selectedActionIds}
                  onToggle={handleToggle}
                />
              </>
            )}
          </div>
        </Surface>
      </Section>
    </SpaceBetween>
  );
}
