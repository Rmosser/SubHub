import { useEffect, useMemo, useState } from "react";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useStandardSources } from "@/api/queries";
import {
  useCreateStandardSource,
  useUpdateStandardSource,
  useDeleteStandardSource,
  usePullStandardSource,
} from "@/api/mutations";
import { StatusBadge, StatusDot } from "@/components/StatusBadge";
import { Chip } from "@/components/Chip";
import { GlassButton } from "@/components/GlassButton";
import { GlassMenu, type GlassMenuEntry } from "@/components/GlassMenu";
import { ReasonTable } from "@/components/ReasonTable";
import { ReasonText } from "@/components/ReasonText";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import { ConfirmModal } from "@/components/ConfirmModal";
import { StandardSourceEditModal } from "./StandardSourceEditModal";
import { formatDateTime } from "@/utils/formatting";
import { compatibilityCounts, MANUAL_NODES, needsAttention, pullReasons, sourceHealth, type SourceHealth } from "./sourceHealth";
import type { StandardSource, StandardSourcePullResponse, StandardSourceWarningItem } from "@/types";
import "./sources.css";

export const INGEST_KIND_REMOTE_SUBSCRIPTION = "remote_subscription";
export const INGEST_KIND_MANUAL_NODES = MANUAL_NODES;
const EMPTY_SOURCES: StandardSource[] = [];
const LIT_MS = 2400;

// 计数已在状态短语里，这里只说一句含义与下一步
function compatibilityHint(source: StandardSource, t: ReturnType<typeof useLocale>["t"]) {
  const { refused, pending } = compatibilityCounts(source);
  if (refused > 0 && pending > 0) return t("sources.compatibility_mixed_hint");
  if (refused > 0) return t("sources.compatibility_refused_hint");
  if (pending > 0) return t("sources.compatibility_pending_hint");
  return "";
}

function warningDescription(warnings: StandardSourceWarningItem[] | undefined) {
  const messages = (warnings || []).map((item) => item.message.trim()).filter(Boolean);
  return messages.length ? messages.slice(0, 2).join("；") : undefined;
}

export interface CreateRequest {
  kind: string;
  at: number;
}

interface Props {
  /** The page header's 添加来源 menu asks this tab to open its editor. */
  createRequest?: CreateRequest | null;
  onCreateHandled?(): void;
}

export function StandardSourcesTab({ createRequest, onCreateHandled }: Props) {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const sources = useStandardSources();
  const createSource = useCreateStandardSource();
  const updateSource = useUpdateStandardSource();
  const deleteSource = useDeleteStandardSource();
  const pullSource = usePullStandardSource();

  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingSource, setEditingSource] = useState<StandardSource | null>(null);
  const [creatingIngestKind, setCreatingIngestKind] = useState(INGEST_KIND_REMOTE_SUBSCRIPTION);
  const [deleteTarget, setDeleteTarget] = useState<StandardSource | null>(null);
  const [pullingIds, setPullingIds] = useState<string[]>([]);
  // 拉取请求本身失败（不是拉取结果）时，原因贴在那一行上，旁边就是重试
  const [pullErrors, setPullErrors] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState<string | undefined>();
  // 刚完成的那一行短暂亮起：光只表达此刻的状态
  const [litId, setLitId] = useState<string | null>(null);

  useEffect(() => {
    if (!litId) return;
    const timer = window.setTimeout(() => setLitId(null), LIT_MS);
    return () => window.clearTimeout(timer);
  }, [litId]);

  useEffect(() => {
    if (!createRequest) return;
    setEditingSource(null);
    setCreatingIngestKind(createRequest.kind);
    setSaveError(undefined);
    setEditModalVisible(true);
    onCreateHandled?.();
  }, [createRequest, onCreateHandled]);

  const items = sources.data ?? EMPTY_SOURCES;

  // 要人处理的排在前面，其余保持后端给的顺序。拉取中只换状态短语，行不挪位、片不收起。
  const rows = useMemo(() => {
    const withHealth = items.map((source, index) => ({
      source,
      index,
      health: sourceHealth(source, t, { requestError: pullErrors[source.id], formatAbsolute: formatDateTime }),
    }));
    return withHealth.sort((a, b) => Number(needsAttention(b.health)) - Number(needsAttention(a.health)) || a.index - b.index);
  }, [items, pullErrors, t]);
  const attention = rows.filter((row) => needsAttention(row.health)).length;

  const handleEdit = (source: StandardSource) => {
    setEditingSource(source);
    setSaveError(undefined);
    setEditModalVisible(true);
  };

  const handleSave = (data: Record<string, unknown>) => {
    const isEdit = !!data.id;
    setSaveError(undefined);
    const callbacks = {
      onSuccess: (response: StandardSourcePullResponse) => {
        const pullResult = response.pull_result;
        if (pullResult?.ok === false) {
          addToast("warning", t("sources.save_pull_failed"), pullResult.error || undefined);
        } else if (pullResult?.warning_count > 0) {
          addToast("warning", t("sources.save_warning"), warningDescription(pullResult.warnings));
        } else {
          addToast("success", isEdit ? t("toast.update_success") : t("toast.create_success"));
          setLitId(response.item.id);
        }
        setPullErrors((current) => {
          const next = { ...current };
          delete next[response.item.id];
          return next;
        });
        setEditModalVisible(false);
      },
      onError: (err: Error) => {
        addToast("error", t("toast.save_error"), err.message);
        setSaveError(err.message);
      },
    };
    if (isEdit) {
      updateSource.mutate(data as { id: string } & Record<string, unknown>, callbacks);
    } else {
      createSource.mutate(data, callbacks);
    }
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteSource.mutate(deleteTarget.id, {
      onSuccess: () => {
        addToast("success", t("toast.delete_success"));
        setDeleteTarget(null);
      },
      onError: (err) => addToast("error", t("toast.delete_error"), err.message),
    });
  };

  const handlePull = (source: StandardSource) => {
    if (pullingIds.includes(source.id)) return;
    setPullingIds((current) => [...current, source.id]);
    setPullErrors((current) => {
      const next = { ...current };
      delete next[source.id];
      return next;
    });
    pullSource.mutate(source.id, {
      onSuccess: (response: StandardSourcePullResponse) => {
        const pullResult = response.pull_result;
        if (pullResult?.warning_count > 0) {
          addToast("warning", t("sources.pull_warning"), warningDescription(pullResult.warnings));
        } else if (pullResult?.ok === false) {
          addToast("warning", t("sources.pull_failed"));
        } else {
          addToast("success", t("sources.pull_success"));
          setLitId(response.item.id);
        }
        setPullingIds((current) => current.filter((id) => id !== source.id));
      },
      onError: (err) => {
        addToast("error", t("sources.pull_failed"), err.message);
        setPullErrors((current) => ({ ...current, [source.id]: err.message }));
        setPullingIds((current) => current.filter((id) => id !== source.id));
      },
    });
  };

  // 片的第二行：拉取失败时逐个客户端列出原因；告警与兼容性给一句含义；编辑在操作列
  const renderReasons = (source: StandardSource) => {
    const requestError = pullErrors[source.id];
    let body: React.ReactNode = null;
    if (requestError) {
      body = <div className="src-reason-text"><ReasonText text={requestError} /></div>;
    } else if (source.last_pull_ok === false) {
      const hint = compatibilityHint(source, t);
      body = <ReasonTable reasons={pullReasons(source, t)} ariaLabel={t("sources.failure_reasons")}>{hint ? <span className="s-muted">{hint}</span> : null}</ReasonTable>;
    } else {
      const warnings = source.pull_warning_count > 0 ? warningDescription(source.pull_warnings) : "";
      const hint = compatibilityHint(source, t);
      if (!warnings && !hint) return null;
      body = (
        <div className="src-reason-text">
          {warnings ? <ReasonText text={warnings} /> : null}
          {hint ? <div className={warnings ? "s-muted" : undefined}>{hint}</div> : null}
        </div>
      );
    }
    return (
      <div className="src-l2">
        {body}
        <div className="src-l2-act">
          <GlassButton variant="quiet" onClick={() => handleEdit(source)}>{t("sources.edit_source")}</GlassButton>
        </div>
      </div>
    );
  };

  const renderRow = ({ source, health }: { source: StandardSource; health: SourceHealth }) => {
    const plate = needsAttention(health);
    const manual = source.ingest_kind === INGEST_KIND_MANUAL_NODES;
    const busy = pullingIds.includes(source.id);
    const menu: GlassMenuEntry[] = [
      { id: "pull", text: t("sources.pull"), narrowOnly: true },
      { id: "edit", text: t("sources.edit_source") },
      "separator",
      { id: "delete", text: t("common.delete"), danger: true },
    ];
    const className = ["src-row", plate ? "plate" : "", litId === source.id ? "is-lit" : "", source.enabled ? "" : "is-off"].filter(Boolean).join(" ");
    return (
      <article className={className} key={source.id} aria-label={source.name}>
        <div className="src-id">
          <h3>{source.name}</h3>
          <div className="src-meta">
            {manual ? <span>{t("sources.manual_nodes")}</span> : null}
            {source.quality_group ? <Chip>{source.quality_group}</Chip> : null}
          </div>
        </div>
        <div className="src-st" title={health.tip || undefined}>
          <StatusBadge tone={busy ? "busy" : health.tone}>{busy ? t("sources.pulling") : health.phrase}</StatusBadge>
          {health.sub ? <div className="src-st-sub">{health.sub}</div> : null}
        </div>
        <div className={`src-n${health.nodes === 0 && plate ? " zero" : ""}`}>
          {health.nodes}<span className="src-n-unit">{t("sources.col_nodes")}</span>
        </div>
        <div className="src-act">
          <GlassButton variant={plate ? "glass" : "ghost"} busy={busy} onClick={() => handlePull(source)}>
            {plate ? t("sources.retry_pull") : t("sources.pull")}
          </GlassButton>
          <GlassMenu size="row" ariaLabel={t("sources.more_actions", { name: source.name })} items={menu} onItem={(id) => {
            if (id === "pull") handlePull(source);
            else if (id === "edit") handleEdit(source);
            else if (id === "delete") setDeleteTarget(source);
          }} />
        </div>
        {plate ? renderReasons(source) : null}
      </article>
    );
  };

  return (
    <>
      <WorkspaceLoader loading={sources.isLoading} error={sources.error} onRetry={() => sources.refetch()}>
        {items.length === 0 ? (
          <div className="src-empty">
            <h3>{t("sources.empty_title")}</h3>
            <p>{t("sources.empty_body")}</p>
          </div>
        ) : (
          <div className="src-list">
            <div className="src-colh">
              <span>{t("sources.col_source")}</span>
              <span>{t("sources.latest_result")}</span>
              <span className="r">{t("sources.col_nodes")}</span>
              <span className="r">
                <span className="sum">
                  <StatusDot tone={attention ? "amber" : "ok"} />
                  {attention ? t("sources.attention_count", { count: attention }) : t("sources.all_healthy")}
                </span>
              </span>
            </div>
            <div className="src-rows">{rows.map(renderRow)}</div>
          </div>
        )}
      </WorkspaceLoader>

      <StandardSourceEditModal
        visible={editModalVisible}
        source={editingSource}
        initialIngestKind={creatingIngestKind}
        loading={createSource.isPending || updateSource.isPending}
        errorText={saveError}
        onSave={handleSave}
        onCancel={() => setEditModalVisible(false)}
      />

      <ConfirmModal
        visible={!!deleteTarget}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      >
        {deleteTarget?.name}
      </ConfirmModal>
    </>
  );
}
