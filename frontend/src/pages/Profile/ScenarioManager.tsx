import { useEffect, useRef, useState } from "react";
import { SpaceBetween, Box, Input, FormField, Toggle, Spinner } from "@cloudscape-design/components";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useScenario } from "@/contexts/ScenarioContext";
import { useScenarios } from "@/api/queries";
import { useCreateScenario, useUpdateScenario, useDeleteScenario } from "@/api/mutations";
import { FormModal } from "@/components/FormModal";
import { ConfirmModal } from "@/components/ConfirmModal";
import type { ScenarioProfile } from "@/types";
import "./scenarios.css";

interface ScenarioManagerProps {
  createRequestToken?: number;
  onCreateRequestHandled?: () => void;
  /** Folds the section away (the heading gets an etched collapse control). */
  onClose?: () => void;
}

export function ScenarioManager({ createRequestToken = 0, onCreateRequestHandled, onClose }: ScenarioManagerProps) {
  const { t, locale } = useLocale();
  const { addToast } = useNotifications();
  const { selectedScenario, requestedScenario, hasSelectionMismatch, selectionIssue } = useScenario();
  const scenarios = useScenarios();
  const createScenario = useCreateScenario();
  const updateScenario = useUpdateScenario();
  const deleteScenario = useDeleteScenario();

  const [editModal, setEditModal] = useState(false);
  const [editing, setEditing] = useState<ScenarioProfile | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ScenarioProfile | null>(null);
  const [disableTarget, setDisableTarget] = useState<ScenarioProfile | null>(null);

  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [enabled, setEnabled] = useState(true);
  const lastCreateRequestRef = useRef(0);

  const handleCreate = () => {
    setEditing(null);
    setSlug("");
    setName("");
    setDescription("");
    setEnabled(true);
    setEditModal(true);
  };

  const handleEdit = (s: ScenarioProfile) => {
    setEditing(s);
    setSlug(s.slug);
    setName(s.name);
    setDescription(s.description);
    setEnabled(s.enabled);
    setEditModal(true);
  };

  const handleSave = () => {
    if (editing) {
      if (editing.enabled && !enabled) {
        setDisableTarget(editing);
        return;
      }
      updateScenario.mutate(
        { id: editing.id, slug, name, description, enabled },
        {
          onSuccess: () => { addToast("success", t("toast.save_success")); setEditModal(false); },
          onError: (err) => addToast("error", t("toast.save_error"), err.message),
        },
      );
    } else {
      createScenario.mutate(
        { slug, name, description, enabled },
        {
          onSuccess: () => { addToast("success", t("toast.create_success")); setEditModal(false); },
          onError: (err) => addToast("error", t("toast.create_error"), err.message),
        },
      );
    }
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteScenario.mutate(deleteTarget.id, {
      onSuccess: () => { addToast("success", t("toast.delete_success")); setDeleteTarget(null); },
      onError: (err) => addToast("error", t("toast.delete_error"), err.message),
    });
  };

  const handleDisable = () => {
    if (!disableTarget) {
      return;
    }
    updateScenario.mutate(
      { id: disableTarget.id, slug, name, description, enabled: false },
      {
        onSuccess: () => {
          addToast("success", t("toast.save_success"));
          setDisableTarget(null);
          setEditModal(false);
        },
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    );
  };

  useEffect(() => {
    if (!createRequestToken || createRequestToken === lastCreateRequestRef.current) {
      return;
    }
    lastCreateRequestRef.current = createRequestToken;
    setEditing(null);
    setSlug("");
    setName("");
    setDescription("");
    setEnabled(true);
    setEditModal(true);
    onCreateRequestHandled?.();
  }, [createRequestToken, onCreateRequestHandled]);

  return (
    <>
      <div className="scn">
        <div className="scn-head">
          <h2 data-glass-etch>{t("scenario.title")}</h2>
          <span className="scn-fill" />
          <button type="button" className="glass-chip scn-new" onClick={handleCreate}>{t("scenario.create")}</button>
          {onClose ? (
            <button type="button" className="scn-close" onClick={onClose}
              aria-label={locale === "zh-CN" ? `收起${t("scenario.title")}` : `Collapse ${t("scenario.title")}`}>
              <svg viewBox="0 0 14 8" aria-hidden="true"><path d="M1.5 6.5 7 1.5l5.5 5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </button>
          ) : null}
        </div>
        {hasSelectionMismatch ? (
          <p className="scn-paper" role="note">
            {selectionIssue === "disabled"
              ? t("scenario.selection_disabled", {
                requested: requestedScenario?.name || requestedScenario?.slug || t("scenario.current"),
                active: selectedScenario?.name || t("scenario.current"),
              })
              : t("scenario.selection_missing", { active: selectedScenario?.name || t("scenario.current") })}
          </p>
        ) : null}
        <div className="scn-sheet" aria-busy={scenarios.isLoading}>
          {scenarios.isLoading ? (
            <div className="scn-empty"><Spinner /></div>
          ) : (scenarios.data ?? []).length ? (scenarios.data ?? []).map((item) => {
            const current = item.id === selectedScenario?.id;
            return (
              <div key={item.id} className={`scn-row${current ? " current" : ""}${item.enabled ? "" : " off"}`} aria-current={current ? "true" : undefined}>
                <span className="scn-dot" aria-hidden="true" />
                <div className="scn-main">
                  <div className="scn-name">
                    {item.name}
                    {item.enabled ? null : <span className="scn-off">{t("common.disabled")}</span>}
                  </div>
                  <div className="scn-meta"><code>{item.slug}</code>{item.description ? <span>{item.description}</span> : null}</div>
                </div>
                <div className="scn-actions">
                  <button type="button" className="scn-icon" aria-label={`${t("common.edit")} ${item.name}`} onClick={() => handleEdit(item)}>
                    <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10.6 2.6l2.8 2.8M3 13l.6-3.2 7.4-7.4 2.6 2.6-7.4 7.4z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" /></svg>
                  </button>
                  <button type="button" className="scn-icon" aria-label={`${t("common.delete")} ${item.name}`} onClick={() => setDeleteTarget(item)}>
                    <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 4h11M6 4V2.6h4V4M4 4l.7 9.4h6.6L12 4M6.6 6.5v4.5M9.4 6.5v4.5" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" /></svg>
                  </button>
                </div>
              </div>
            );
          }) : (
            <div className="scn-empty">{t("scenario.no_scenarios")}</div>
          )}
        </div>
      </div>

      <FormModal
        visible={editModal}
        header={editing ? t("scenario.edit") : t("scenario.create")}
        loading={createScenario.isPending || updateScenario.isPending}
        confirmLabel={t("common.save")}
        onSubmit={handleSave}
        onCancel={() => setEditModal(false)}
      >
        <SpaceBetween size="l">
          <FormField label={t("scenario.slug")}>
            <Input value={slug} onChange={({ detail }) => setSlug(detail.value)} disabled={!!editing} />
          </FormField>
          <FormField label={t("common.name")}>
            <Input value={name} onChange={({ detail }) => setName(detail.value)} />
          </FormField>
          <FormField label={t("common.description")}>
            <Input value={description} onChange={({ detail }) => setDescription(detail.value)} />
          </FormField>
          <FormField label={t("common.enabled")}>
            <Toggle checked={enabled} onChange={({ detail }) => setEnabled(detail.checked)} />
          </FormField>
        </SpaceBetween>
      </FormModal>

      <ConfirmModal
        visible={!!disableTarget}
        header={t("scenario.disable_confirm_title")}
        confirmLabel={t("scenario.disable")}
        onConfirm={handleDisable}
        onCancel={() => setDisableTarget(null)}
        description={t("scenario.disable_confirm_body")}
        details={disableTarget ? [
          { label: t("common.name"), value: disableTarget.name },
          { label: t("scenario.slug"), value: disableTarget.slug },
        ] : undefined}
        consequences={[
          disableTarget?.id === selectedScenario?.id
            ? t("scenario.disable_confirm_current")
            : t("scenario.disable_confirm_other"),
          t("scenario.selection_reselect_hint"),
        ]}
      >
        <Box>{disableTarget?.description || "-"}</Box>
      </ConfirmModal>

      <ConfirmModal
        visible={!!deleteTarget}
        header={t("scenario.delete_confirm_title")}
        confirmLabel={t("scenario.delete")}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
        description={t("scenario.delete_confirm_body")}
        details={deleteTarget ? [
          { label: t("common.name"), value: deleteTarget.name },
          { label: t("scenario.slug"), value: deleteTarget.slug },
        ] : undefined}
        consequences={[
          deleteTarget?.id === selectedScenario?.id
            ? t("scenario.delete_confirm_current")
            : t("scenario.delete_confirm_other"),
          t("scenario.selection_reselect_hint"),
        ]}
      >
        <Box>{deleteTarget?.description || "-"}</Box>
      </ConfirmModal>
    </>
  );
}
