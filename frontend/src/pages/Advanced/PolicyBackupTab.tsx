import { useMemo, useState } from "react";
import {
  Button,
  FormField,
  Input,
} from "@cloudscape-design/components";
import { Section, Surface } from "@/components/Section";
import { Facts } from "@/components/Facts";
import { PaperNote } from "@/components/PaperNote";
import { StatusBadge } from "@/components/StatusBadge";
import { ReasonText } from "@/components/ReasonText";
import { useLocale } from "@/contexts/LocaleContext";
import { t as translate } from "@/i18n/translations";
import { useNotifications } from "@/contexts/NotificationContext";
import { usePolicyBackupStatus } from "@/api/queries";
import { useApplyPolicyBackupRestore, usePreviewPolicyBackupRestore, useSyncPolicyBackup } from "@/api/mutations";
import { ConfirmModal } from "@/components/ConfirmModal";
import { formatDateTime } from "@/utils/formatting";
import type { PolicyRestorePreviewSection } from "@/types";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import { canApplyRestore } from "./restoreState";

function renderResultStatus(result: string) {
  switch (result) {
    case "ok":
      return <StatusBadge status="success">{translate("advanced.policy_backup_result_ok")}</StatusBadge>;
    case "error":
      return <StatusBadge status="error">{translate("advanced.policy_backup_result_error")}</StatusBadge>;
    case "syncing":
      return <StatusBadge status="in-progress">{translate("advanced.policy_backup_result_syncing")}</StatusBadge>;
    default:
      return <StatusBadge status="pending">{translate("advanced.policy_backup_result_idle")}</StatusBadge>;
  }
}

function renderSectionSummary(section: PolicyRestorePreviewSection) {
  const parts: string[] = [];
  if (section.added_count) {
    parts.push(`+${section.added_count}`);
  }
  if (section.removed_count) {
    parts.push(`-${section.removed_count}`);
  }
  if (section.changed_count) {
    parts.push(`~${section.changed_count}`);
  }
  return parts.join(" / ") || "0";
}

export function PolicyBackupTab() {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const status = usePolicyBackupStatus();
  const syncBackup = useSyncPolicyBackup();
  const previewRestore = usePreviewPolicyBackupRestore();
  const applyRestore = useApplyPolicyBackupRestore();
  const [ref, setRef] = useState("");
  const [previewRequestRef, setPreviewRequestRef] = useState<string | null>(null);
  const [applyConfirmVisible, setApplyConfirmVisible] = useState(false);

  const statusItem = status.data;
  const preview = previewRestore.data;
  const disabledReason = useMemo(() => {
    if (!statusItem?.enabled) {
      return t("advanced.policy_backup_disabled");
    }
    if (!statusItem.configured) {
      return t("advanced.policy_backup_unconfigured");
    }
    return "";
  }, [statusItem, t]);

  const busy = previewRestore.isPending || applyRestore.isPending || syncBackup.isPending || Boolean(statusItem?.syncing);
  const canOperate = Boolean(statusItem?.enabled && statusItem?.configured && !status.error);
  const normalizedRef = ref.trim();
  const hasPreviewForCurrentRef = canApplyRestore(preview, previewRequestRef, normalizedRef, busy);

  return (
    <WorkspaceLoader loading={status.isLoading} error={status.error} onRetry={() => status.refetch()}>
      <Section
        ariaLabel={t("advanced.policy_backup")}
        meta={canOperate ? (
          <StatusBadge status={hasPreviewForCurrentRef ? "success" : "pending"}>
            {hasPreviewForCurrentRef
              ? t("advanced.policy_backup_preview_ready")
              : t("advanced.policy_backup_preview_required")}
          </StatusBadge>
        ) : null}
        actions={
          <Button
            variant="primary"
            loading={syncBackup.isPending || Boolean(statusItem?.syncing)}
            disabled={!canOperate || busy}
            onClick={() =>
              syncBackup.mutate(undefined, {
                onSuccess: () => addToast("success", t("advanced.policy_backup_sync_success")),
                onError: (error) =>
                  addToast("error", t("advanced.policy_backup_sync_failed"), error.message),
              })
            }
          >
            {t("advanced.policy_backup_sync")}
          </Button>
        }
      >
        {!canOperate ? <PaperNote><strong>{disabledReason}</strong></PaperNote> : null}

        <Surface>
          <div className="s-stack">
            <Facts
              items={[
                { label: t("advanced.policy_backup_repo"), value: <span className="s-mono">{statusItem?.repo_url || "-"}</span> },
                { label: t("advanced.policy_backup_branch"), value: statusItem?.branch || "-" },
                { label: t("advanced.policy_backup_dirty"), value: statusItem?.dirty ? t("common.yes") : t("common.no") },
                { label: t("advanced.policy_backup_result"), value: renderResultStatus(statusItem?.syncing ? "syncing" : statusItem?.last_result || "idle") },
                { label: t("advanced.policy_backup_last_sync"), value: statusItem?.last_sync_at ? formatDateTime(statusItem.last_sync_at) : "-" },
                { label: t("advanced.policy_backup_last_commit"), value: statusItem?.last_commit_sha ? <span className="s-mono s-ellipsis" title={statusItem.last_commit_sha}>{statusItem.last_commit_sha}</span> : "-" },
              ]}
            />
            {statusItem?.last_error ? (
              <div className="s-error">
                <StatusBadge status="error">{t("advanced.policy_backup_last_error")}</StatusBadge>
                <ReasonText text={statusItem.last_error} lines={3} />
              </div>
            ) : null}

            <hr className="s-rule" />

            <div className="s-row">
              <div className="s-grow">
                <FormField stretch label={t("advanced.policy_backup_restore_ref")}>
                  <Input
                    value={ref}
                    placeholder={t("advanced.policy_backup_restore_ref_placeholder")}
                    disabled={busy || applyConfirmVisible}
                    onChange={({ detail }) => {
                      setRef(detail.value);
                      setPreviewRequestRef(null);
                      previewRestore.reset();
                    }}
                  />
                </FormField>
              </div>
              <Button
                loading={previewRestore.isPending}
                disabled={!canOperate || busy || applyConfirmVisible}
                onClick={() => {
                  setPreviewRequestRef(null);
                  previewRestore.reset();
                  previewRestore.mutate(
                    { ref: normalizedRef || undefined },
                    {
                      onSuccess: () => setPreviewRequestRef(normalizedRef),
                      onError: (error) =>
                        addToast("error", t("advanced.policy_backup_preview_failed"), error.message),
                    },
                  );
                }}
              >
                {t("advanced.policy_backup_preview")}
              </Button>
              <Button
                variant="normal"
                loading={applyRestore.isPending}
                disabled={!canOperate || busy || !hasPreviewForCurrentRef}
                onClick={() => setApplyConfirmVisible(true)}
              >
                {t("advanced.policy_backup_apply")}
              </Button>
            </div>

            {preview ? (
              <div className="s-stack">
                <StatusBadge status={preview.changed ? "info" : "success"}>
                  {preview.changed ? t("advanced.policy_backup_preview_changed") : t("advanced.policy_backup_preview_clean")}
                </StatusBadge>
                <Facts
                  compact
                  items={[
                    { label: t("advanced.policy_backup_restore_ref"), value: preview.ref || (previewRequestRef || "-") },
                    { label: t("advanced.policy_backup_snapshot_digest"), value: <span className="s-mono">{preview.snapshot_digest || "-"}</span> },
                    ...preview.sections.map((section) => ({ label: section.name, value: renderSectionSummary(section) })),
                  ]}
                />
                {preview.sections.length ? null : (
                  <span className="s-muted">{t("advanced.policy_backup_no_preview_changes")}</span>
                )}
              </div>
            ) : null}
          </div>
        </Surface>
      </Section>

      <ConfirmModal
        visible={applyConfirmVisible}
        header={t("advanced.policy_backup_apply_confirm_title")}
        confirmLabel={t("advanced.policy_backup_apply")}
        confirmDisabled={!canOperate || busy || !hasPreviewForCurrentRef}
        onConfirm={() => {
          if (!canOperate || busy || !hasPreviewForCurrentRef || previewRequestRef === null || !preview) return;
          applyRestore.mutate(
            { ref: previewRequestRef || undefined, expected_digest: preview.snapshot_digest },
            {
              onSuccess: () => {
                addToast("success", t("advanced.policy_backup_apply_success"));
                setApplyConfirmVisible(false);
                setPreviewRequestRef(null);
                previewRestore.reset();
              },
              onError: (error) => {
                addToast("error", t("advanced.policy_backup_apply_failed"), error.message);
                setApplyConfirmVisible(false);
                setPreviewRequestRef(null);
                previewRestore.reset();
              },
            },
          );
        }}
        onCancel={() => setApplyConfirmVisible(false)}
        description={t("advanced.policy_backup_apply_confirm_body")}
        details={preview ? [
          {
            label: t("advanced.policy_backup_restore_ref"),
            value: preview.ref || (previewRequestRef || "-"),
          },
          {
            label: t("advanced.policy_backup_snapshot_digest"),
            value: preview.snapshot_digest || "-",
          },
          {
            label: t("advanced.policy_backup_preview_result"),
            value: preview.changed ? t("advanced.policy_backup_preview_changed") : t("advanced.policy_backup_preview_clean"),
          },
        ] : undefined}
        consequences={preview?.sections.map((section) => `${section.name}: ${renderSectionSummary(section)}`)}
      >
        <p className="s-dialog-lead">{t("advanced.policy_backup_apply_confirm_hint")}</p>
      </ConfirmModal>
    </WorkspaceLoader>
  );
}
