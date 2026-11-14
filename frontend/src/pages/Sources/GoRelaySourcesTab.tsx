import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  ColumnLayout,
  FormField,
  Input,
  Select,
  SpaceBetween,
  Table,
  Textarea,
} from "@cloudscape-design/components";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import {
  useStatus,
  useGorelaySources,
  useGorelayAccountStatus,
  useGorelayAccountDevices,
  useGorelayPendingBindings,
  useGorelayEntryUsage,
  useGorelayImportHistories,
  useGorelaySnapshots,
  useGorelaySubscriptions,
} from "@/api/queries";
import {
  useCreateGorelaySource,
  useUpdateGorelaySource,
  useDeleteGorelaySource,
  useRefreshGorelayAccounts,
  useCrawlGorelayAccount,
  useUpdateGorelayAccountProxyCredentials,
  useUpdateGorelayDeviceProxyCredentials,
  useUpdateGorelayDeviceStrategyPreset,
  useImportGorelayDomainBindings,
  useImportGorelayEntryMultipliers,
  useUpdateGorelayDomainBinding,
  useDeleteGorelayImportHistory,
  useActivateGorelaySnapshot,
  useDisableGorelaySubscription,
} from "@/api/mutations";
import { CopyButton } from "@/components/CopyButton";
import { InlineAction } from "@/components/InlineAction";
import { StatusBadge, StatusDot } from "@/components/StatusBadge";
import { GlassButton } from "@/components/GlassButton";
import { GlassMenu, type GlassMenuEntry } from "@/components/GlassMenu";
import { Chip } from "@/components/Chip";
import { Facts } from "@/components/Facts";
import { ErrorNote } from "@/components/ErrorNote";
import { Section, Surface } from "@/components/Section";
import { ConfirmModal } from "@/components/ConfirmModal";
import { FormModal } from "@/components/FormModal";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import { ReasonText } from "@/components/ReasonText";
import { GlassTabs } from "@/components/GlassTabs";
import { GoRelaySourceEditModal } from "./GoRelaySourceEditModal";
import { proxyBridgeNote } from "./proxyBridge";
import { gorelayHealth, needsAttention, shortUrl, type SourceHealth } from "./sourceHealth";
import { formatDateTime } from "@/utils/formatting";
import "./sources.css";
import type {
  GoRelaySource,
  GoRelayAccountDevice,
  GoRelayBinding,
  GoRelayDomainImportHistory,
  GoRelayEntryUsage,
  GoRelaySnapshot,
  GoRelaySubscription,
} from "@/types";

const EMPTY_ACCOUNTS: GoRelaySource[] = [];
const STRATEGY_PRESETS = ["balanced", "latency_first", "stability_first", "bulk"] as const;
const STRATEGY_PRESET_OPTIONS = STRATEGY_PRESETS.map((preset) => ({ label: preset, value: preset }));

interface CredentialModalState {
  accountId: string;
  deviceKey?: string;
  title: string;
  usernameLabel: string;
  passwordLabel: string;
  username: string;
  password: string;
}

interface PresetModalState {
  accountId: string;
  deviceKey: string;
  deviceName: string;
  preset: string;
}

interface BindingApprovalModalState {
  accountId: string;
  bindingId: string;
  entryName: string;
  hostValue: string;
}

export function GoRelaySourcesTab() {
  const { t, locale } = useLocale();
  const { addToast } = useNotifications();
  const isZh = locale === "zh-CN";
  const sources = useGorelaySources();
  const systemStatus = useStatus();
  const bridge = proxyBridgeNote(systemStatus.data);
  const refreshAccounts = useRefreshGorelayAccounts();
  const createSource = useCreateGorelaySource();
  const updateSource = useUpdateGorelaySource();
  const deleteSource = useDeleteGorelaySource();
  const crawlAccount = useCrawlGorelayAccount();
  const updateAccountProxy = useUpdateGorelayAccountProxyCredentials();
  const updateDeviceProxy = useUpdateGorelayDeviceProxyCredentials();
  const updateStrategyPreset = useUpdateGorelayDeviceStrategyPreset();
  const importDomainBindings = useImportGorelayDomainBindings();
  const importEntryMultipliers = useImportGorelayEntryMultipliers();
  const updateDomainBinding = useUpdateGorelayDomainBinding();
  const deleteImportHistory = useDeleteGorelayImportHistory();
  const activateSnapshot = useActivateGorelaySnapshot();
  const disableSubscription = useDisableGorelaySubscription();

  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingSource, setEditingSource] = useState<GoRelaySource | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<GoRelaySource | null>(null);
  const [domainImportText, setDomainImportText] = useState("");
  const [multiplierImportText, setMultiplierImportText] = useState("");
  const [credentialModal, setCredentialModal] = useState<CredentialModalState | null>(null);
  const [presetModal, setPresetModal] = useState<PresetModalState | null>(null);
  const [bindingApprovalModal, setBindingApprovalModal] = useState<BindingApprovalModalState | null>(null);

  const status = useGorelayAccountStatus(selectedAccountId);
  const devices = useGorelayAccountDevices(selectedAccountId);
  const bindings = useGorelayPendingBindings(selectedAccountId);
  const entryUsage = useGorelayEntryUsage(selectedAccountId);
  const histories = useGorelayImportHistories(selectedAccountId);
  const snapshots = useGorelaySnapshots(selectedAccountId);
  const subscriptions = useGorelaySubscriptions(selectedAccountId);

  useEffect(() => {
    if (!selectedAccountId && sources.data?.length) {
      setSelectedAccountId(sources.data[0].id);
    }
  }, [selectedAccountId, sources.data]);

  const selectedAccount = (sources.data ?? []).find((item) => item.id === selectedAccountId) || null;
  const crawlFailedReason = status.data?.latest_error || "";
  const renderCrawlStatus = (value: string | undefined) => {
    if (value === "success") return <StatusBadge status="success">{t("sources.gorelay_status_success")}</StatusBadge>;
    if (value === "empty") return <StatusBadge status="warning">{t("sources.gorelay_status_empty")}</StatusBadge>;
    if (value === "failed") return <StatusBadge status="error">{t("sources.gorelay_status_failed")}</StatusBadge>;
    return value ? <span className="s-mono s-muted">{value}</span> : "-";
  };

  const accountRows = useMemo(
    () => (sources.data ?? EMPTY_ACCOUNTS).map((account) => ({ account, health: gorelayHealth(account, t, { formatAbsolute: formatDateTime }) })),
    [sources.data, t],
  );
  const accountAttention = accountRows.filter((row) => needsAttention(row.health)).length;
  const crawlingId = crawlAccount.isPending ? crawlAccount.variables : undefined;

  // 账号行刻在玻璃上：点名称在下方展开这个账号，当前展开的那个名称亮着。要处理的事在下方那片玻璃上说。
  const renderAccountRow = ({ account, health }: { account: GoRelaySource; health: SourceHealth }) => {
    const current = account.id === selectedAccountId;
    const busy = crawlingId === account.id;
    const menu: GlassMenuEntry[] = [
      { id: "crawl", text: t("sources.crawl_now"), narrowOnly: true },
      { id: "edit", text: t("common.edit") },
      "separator",
      { id: "delete", text: t("common.delete"), danger: true },
    ];
    const host = account.login_url ? shortUrl(account.login_url) : "";
    return (
      <article className={account.enabled ? "src-row" : "src-row is-off"} key={account.id} aria-label={account.name}>
        <div className="src-id">
          <h3>
            <button type="button" className="src-name" aria-current={current ? "true" : undefined} onClick={() => setSelectedAccountId(account.id)}>
              {account.name}
            </button>
          </h3>
          <div className="src-meta">
            {account.gorelay_username ? <span>{account.gorelay_username}</span> : null}
            {host ? <span className="s-mono" title={account.login_url}>{host}</span> : null}
          </div>
        </div>
        <div className="src-st" title={health.tip || undefined}>
          <StatusBadge tone={busy ? "busy" : health.tone}>{busy ? t("sources.crawling") : health.phrase}</StatusBadge>
          {health.sub ? <div className="src-st-sub">{health.sub}</div> : null}
        </div>
        <div className="src-n">
          {health.nodes}<span className="src-n-unit">{t("sources.col_nodes")}</span>
        </div>
        <div className="src-act">
          <GlassButton variant="ghost" busy={busy} onClick={() => handleCrawl(account.id)}>{t("sources.crawl_now")}</GlassButton>
          <GlassMenu size="row" ariaLabel={t("sources.more_actions", { name: account.name })} items={menu} onItem={(id) => {
            if (id === "crawl") handleCrawl(account.id);
            else if (id === "edit") handleEdit(account);
            else if (id === "delete") setDeleteTarget(account);
          }} />
        </div>
      </article>
    );
  };

  const handleCreate = () => {
    setEditingSource(null);
    setEditModalVisible(true);
  };

  const handleEdit = (source: GoRelaySource) => {
    setEditingSource(source);
    setEditModalVisible(true);
  };

  const handleSave = (data: Record<string, unknown>) => {
    const isEdit = !!data.id;
    const callbacks = {
      onSuccess: (result: { item: GoRelaySource | null }) => {
        addToast("success", isEdit ? t("toast.update_success") : t("toast.create_success"));
        setEditModalVisible(false);
        setSelectedAccountId(result.item?.id ?? selectedAccountId);
      },
      onError: (err: Error) => addToast("error", t("toast.save_error"), err.message),
    };
    if (isEdit) {
      updateSource.mutate(data as { id: string } & Record<string, unknown>, callbacks);
      return;
    }
    createSource.mutate(data, callbacks);
  };

  const handleDelete = () => {
    if (!deleteTarget) {
      return;
    }
    deleteSource.mutate(deleteTarget.id, {
      onSuccess: () => {
        addToast("success", t("toast.delete_success"));
        if (selectedAccountId === deleteTarget.id) {
          setSelectedAccountId(null);
        }
        setDeleteTarget(null);
      },
      onError: (err) => addToast("error", t("toast.delete_error"), err.message),
    });
  };

  const handleRefreshAll = () => {
    refreshAccounts.mutate(undefined, {
      onSuccess: () => addToast("success", isZh ? "GoRelay 全量刷新已触发" : "GoRelay refresh started"),
      onError: (err) => addToast("error", t("sources.pull_failed"), err.message),
    });
  };

  const handleCrawl = (accountId: string) => {
    crawlAccount.mutate(accountId, {
      onSuccess: () => addToast("success", isZh ? "抓取完成" : "Crawl completed"),
      onError: (err) => addToast("error", isZh ? "抓取失败" : "Crawl failed", err.message),
    });
  };

  const handleUpdateAccountProxy = () => {
    if (!selectedAccount) {
      return;
    }
    setCredentialModal({
      accountId: selectedAccount.id,
      title: isZh ? "账号代理凭据" : "Account proxy credentials",
      usernameLabel: isZh ? "账号默认代理用户名" : "Default proxy username",
      passwordLabel: isZh ? "账号默认代理密码" : "Default proxy password",
      username: selectedAccount.proxy_username || "",
      password: "",
    });
  };

  const handleUpdateDeviceProxy = (item: GoRelayAccountDevice) => {
    if (!selectedAccountId) {
      return;
    }
    setCredentialModal({
      accountId: selectedAccountId,
      deviceKey: item.device_key,
      title: isZh ? `设备 ${item.device_name} 代理凭据` : `Proxy credentials for ${item.device_name}`,
      usernameLabel: isZh ? "设备代理用户名" : "Device proxy username",
      passwordLabel: isZh ? "设备代理密码" : "Device proxy password",
      username: item.proxy_username_override || "",
      password: "",
    });
  };

  const handleUpdateStrategyPreset = (item: GoRelayAccountDevice) => {
    if (!selectedAccountId) {
      return;
    }
    setPresetModal({
      accountId: selectedAccountId,
      deviceKey: item.device_key,
      deviceName: item.device_name,
      preset: item.strategy_preset || STRATEGY_PRESETS[0],
    });
  };

  const handleImportDomains = () => {
    if (!selectedAccountId || !domainImportText.trim()) {
      return;
    }
    importDomainBindings.mutate(
      { accountId: selectedAccountId, reply_text: domainImportText },
      {
        onSuccess: () => {
          addToast("success", isZh ? "域名绑定已导入" : "Domain bindings imported");
          setDomainImportText("");
        },
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    );
  };

  const handleImportMultipliers = () => {
    if (!selectedAccountId || !multiplierImportText.trim()) {
      return;
    }
    importEntryMultipliers.mutate(
      { accountId: selectedAccountId, text: multiplierImportText },
      {
        onSuccess: () => {
          addToast("success", isZh ? "倍率导入完成" : "Entry multipliers imported");
          setMultiplierImportText("");
        },
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    );
  };

  const handleApproveBinding = (item: GoRelayBinding) => {
    if (!selectedAccountId) {
      return;
    }
    const bindingId = item.binding_id || item.id;
    if (!bindingId) {
      return;
    }
    setBindingApprovalModal({
      accountId: selectedAccountId,
      bindingId,
      entryName: item.entry_name,
      hostValue: item.host_value || "",
    });
  };

  const handleDeleteHistory = (historyId: string) => {
    if (!selectedAccountId) {
      return;
    }
    deleteImportHistory.mutate(
      { accountId: selectedAccountId, historyId },
      {
        onSuccess: () => addToast("success", t("toast.delete_success")),
        onError: (err) => addToast("error", t("toast.delete_error"), err.message),
      },
    );
  };

  const handleActivateSnapshot = (snapshotId: string) => {
    if (!selectedAccountId) {
      return;
    }
    activateSnapshot.mutate(
      { accountId: selectedAccountId, snapshotId },
      {
        onSuccess: () => addToast("success", isZh ? "快照已激活" : "Snapshot activated"),
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    );
  };

  const handleDisableSubscription = (subscriptionId: string) => {
    if (!selectedAccountId) {
      return;
    }
    disableSubscription.mutate(
      { accountId: selectedAccountId, subscriptionId },
      {
        onSuccess: () => addToast("success", isZh ? "订阅已禁用" : "Subscription disabled"),
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    );
  };

  const detailError =
    (status.error as Error | null) ||
    (devices.error as Error | null) ||
    (bindings.error as Error | null) ||
    (entryUsage.error as Error | null) ||
    (histories.error as Error | null) ||
    (snapshots.error as Error | null) ||
    (subscriptions.error as Error | null);

  const handleCredentialSubmit = () => {
    if (!credentialModal) {
      return;
    }
    const username = credentialModal.username.trim();
    const password = credentialModal.password;

    if (credentialModal.deviceKey) {
      updateDeviceProxy.mutate(
        {
          accountId: credentialModal.accountId,
          deviceKey: credentialModal.deviceKey,
          username,
          password,
        },
        {
          onSuccess: () => {
            addToast("success", t("toast.save_success"));
            setCredentialModal(null);
          },
          onError: (err) => addToast("error", t("toast.save_error"), err.message),
        },
      );
      return;
    }

    updateAccountProxy.mutate(
      {
        accountId: credentialModal.accountId,
        username,
        password,
      },
      {
        onSuccess: () => {
          addToast("success", t("toast.save_success"));
          setCredentialModal(null);
        },
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    );
  };

  const handlePresetSubmit = () => {
    if (!presetModal) {
      return;
    }
    updateStrategyPreset.mutate(
      {
        accountId: presetModal.accountId,
        deviceKey: presetModal.deviceKey,
        strategy_preset: presetModal.preset,
      },
      {
        onSuccess: () => {
          addToast("success", t("toast.save_success"));
          setPresetModal(null);
        },
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    );
  };

  const handleBindingApprovalSubmit = () => {
    if (!bindingApprovalModal) {
      return;
    }
    const hostValue = bindingApprovalModal.hostValue.trim();
    if (!hostValue) {
      return;
    }
    updateDomainBinding.mutate(
      {
        accountId: bindingApprovalModal.accountId,
        bindingId: bindingApprovalModal.bindingId,
        host_value: hostValue,
        status: "approved",
      },
      {
        onSuccess: () => {
          addToast("success", isZh ? "绑定已批准并触发重建" : "Binding approved and rebuild triggered");
          setBindingApprovalModal(null);
        },
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    );
  };

  return (
    <>
      {systemStatus.error ? (
        <div className="src-page-sheet">
          <ErrorNote title={t("sources.environment_unavailable")} reason={systemStatus.error.message} onRetry={() => systemStatus.refetch()} />
        </div>
      ) : bridge ? (
        // 出站代理是整个 GoRelay 页的前提：页面最上方一片玻璃，说清楚是什么、怎么修
        <div className="s-sheet src-page-sheet" role="note">
          <div>
            <StatusBadge status={bridge.severity === "error" ? "error" : bridge.severity === "warning" ? "warning" : "info"}>{bridge.summary}</StatusBadge>
            {bridge.repair_hint ? <div className="s-sheet-text"><ReasonText text={bridge.repair_hint} /></div> : null}
          </div>
        </div>
      ) : null}
      <SpaceBetween size="l">
        <Section
          actions={
            <>
              <Button onClick={handleRefreshAll} loading={refreshAccounts.isPending}>
                {isZh ? "全量刷新" : "Refresh all"}
              </Button>
              <Button onClick={handleCreate}>
                {t("sources.add_gorelay")}
              </Button>
            </>
          }
        >
          <WorkspaceLoader loading={sources.isLoading} error={sources.error} onRetry={() => sources.refetch()}>
            {accountRows.length === 0 ? (
              <div className="src-empty"><p>{t("common.no_items")}</p></div>
            ) : (
              <div className="src-list" aria-label={t("sources.gorelay_accounts")}>
                <div className="src-colh">
                  <span>{t("sources.col_account")}</span>
                  <span>{t("sources.latest_result")}</span>
                  <span className="r">{t("sources.col_nodes")}</span>
                  <span className="r">
                    <span className="sum">
                      <StatusDot tone={accountAttention ? "amber" : "ok"} />
                      {accountAttention ? t("sources.attention_count", { count: accountAttention }) : t("sources.all_healthy")}
                    </span>
                  </span>
                </div>
                <div className="src-rows">{accountRows.map(renderAccountRow)}</div>
              </div>
            )}
          </WorkspaceLoader>
        </Section>

        {selectedAccount && (
          <WorkspaceLoader
            loading={status.isLoading || devices.isLoading}
            error={detailError}
            onRetry={() => {
              void status.refetch();
              void devices.refetch();
              void bindings.refetch();
              void entryUsage.refetch();
              void histories.refetch();
              void snapshots.refetch();
              void subscriptions.refetch();
            }}
          >
            <SpaceBetween size="xl">
              <Section
                title={selectedAccount.name}
                actions={
                  <Button onClick={handleUpdateAccountProxy}>
                    {isZh ? "账号代理凭据" : "Account proxy"}
                  </Button>
                }
              >
                <Surface>
                  <div className="s-stack">
                    <Facts items={[
                      // 失败时由下方的错误说明讲一次，状态不再作为事实重复
                      ...(crawlFailedReason ? [] : [{ label: isZh ? "最新状态" : "Latest status", value: renderCrawlStatus(status.data?.latest_status) }]),
                      { label: isZh ? "节点数" : "Nodes", value: status.data?.latest_node_count || 0 },
                      { label: isZh ? "设备数" : "Devices", value: status.data?.latest_device_count || 0 },
                      { label: isZh ? "待处理绑定" : "Pending bindings", value: status.data?.pending_domain_count || 0 },
                    ]} />
                    {crawlFailedReason ? (
                      <ErrorNote title={t("sources.gorelay_crawl_failed")} reason={crawlFailedReason} />
                    ) : null}
                  </div>
                </Surface>
              </Section>

              <Section title={isZh ? "账号设备" : "Account devices"}>
                <Table
                  wrapLines
                  items={devices.data ?? []}
                  columnDefinitions={[
                    { id: "device_name", header: t("devices.device_name"), cell: (item) => item.device_name },
                    { id: "node_count", header: isZh ? "节点数" : "Nodes", cell: (item) => item.node_count },
                    {
                      id: "entries",
                      header: isZh ? "入口" : "Entries",
                      // 入口多时限两行，完整列表在 title 里，操作列不被挤出视口
                      cell: (item) => {
                        const text = item.entries.join(", ");
                        return text ? <span className="s-clamp-2" title={text}>{text}</span> : "-";
                      },
                    },
                    { id: "strategy_preset", header: "Preset", cell: (item) => item.strategy_preset || "-" },
                    {
                      id: "subscription",
                      header: isZh ? "订阅" : "Subscription",
                      cell: (item) =>
                        item.subscription_enabled ? (
                          <StatusBadge status="success">{isZh ? "已启用" : "Enabled"}</StatusBadge>
                        ) : (
                          <StatusBadge status="stopped">{isZh ? "已禁用" : "Disabled"}</StatusBadge>
                        ),
                    },
                    {
                      id: "actions",
                      header: t("common.actions"),
                      cell: (item) => (
                        <SpaceBetween direction="horizontal" size="xs">
                          <InlineAction onClick={() => handleUpdateStrategyPreset(item)}>
                            {isZh ? "Preset" : "Preset"}
                          </InlineAction>
                          <InlineAction onClick={() => handleUpdateDeviceProxy(item)}>
                            {isZh ? "代理" : "Proxy"}
                          </InlineAction>
                        </SpaceBetween>
                      ),
                    },
                  ]}
                  empty={<div className="s-empty">{t("common.no_items")}</div>}
                />
              </Section>

              <GlassTabs
                ariaLabel={selectedAccount.name}
                tabs={[
                  {
                    id: "bindings",
                    label: isZh ? "绑定工作区" : "Bindings",
                    content: (
                      <SpaceBetween size="l">
                        <ColumnLayout columns={2}>
                          <FormField label={isZh ? "导入域名绑定回复" : "Import domain binding reply"}>
                            <Textarea
                              rows={8}
                              value={domainImportText}
                              onChange={({ detail }) => setDomainImportText(detail.value)}
                            />
                          </FormField>
                          <FormField label={isZh ? "导入倍率文本" : "Import entry multipliers"}>
                            <Textarea
                              rows={8}
                              value={multiplierImportText}
                              onChange={({ detail }) => setMultiplierImportText(detail.value)}
                            />
                          </FormField>
                        </ColumnLayout>
                        <SpaceBetween direction="horizontal" size="xs">
                          <Button onClick={handleImportDomains} loading={importDomainBindings.isPending}>
                            {isZh ? "导入域名" : "Import domains"}
                          </Button>
                          <Button onClick={handleImportMultipliers} loading={importEntryMultipliers.isPending}>
                            {isZh ? "导入倍率" : "Import multipliers"}
                          </Button>
                        </SpaceBetween>
                        <Section title={isZh ? "待处理绑定" : "Pending bindings"}>
                          <Table
                            wrapLines
                            items={bindings.data?.pending ?? []}
                            columnDefinitions={[
                              { id: "entry_name", header: isZh ? "入口" : "Entry", cell: (item) => item.entry_name },
                              { id: "isp", header: "ISP", cell: (item) => item.isp },
                              { id: "ip_version", header: "IP", cell: (item) => item.ip_version },
                              { id: "host_value", header: "Host", cell: (item) => item.host_value || "-" },
                              { id: "ports", header: isZh ? "端口" : "Ports", cell: (item) => item.ports.join(", ") || "-" },
                              {
                                id: "actions",
                                header: t("common.actions"),
                                cell: (item) => (
                                  <InlineAction onClick={() => handleApproveBinding(item)}>
                                    {isZh ? "批准并重建" : "Approve"}
                                  </InlineAction>
                                ),
                              },
                            ]}
                            empty={<div className="s-empty">{t("common.no_items")}</div>}
                          />
                        </Section>
                        <Section title={isZh ? "已批准绑定" : "Approved bindings"}>
                          <Table
                            wrapLines
                            items={bindings.data?.bindings ?? []}
                            columnDefinitions={[
                              { id: "entry_name", header: isZh ? "入口" : "Entry", cell: (item) => item.entry_name },
                              { id: "isp", header: "ISP", cell: (item) => item.isp },
                              { id: "ip_version", header: "IP", cell: (item) => item.ip_version },
                              { id: "host_value", header: "Host", cell: (item) => item.host_value || "-" },
                              {
                                id: "devices",
                                header: isZh ? "设备" : "Devices",
                                cell: (item) => item.devices.map((device) => device.device_name).join(", ") || "-",
                              },
                            ]}
                            empty={<div className="s-empty">{t("common.no_items")}</div>}
                          />
                        </Section>
                      </SpaceBetween>
                    ),
                  },
                  {
                    id: "entries",
                    label: isZh ? "入口使用" : "Entry usage",
                    content: (
                      <Table
                        wrapLines
                        items={entryUsage.data ?? []}
                        columnDefinitions={[
                          { id: "entry_name", header: isZh ? "入口" : "Entry", cell: (item: GoRelayEntryUsage) => item.entry_name },
                          { id: "isp", header: "ISP", cell: (item: GoRelayEntryUsage) => item.isp },
                          { id: "ip_version", header: "IP", cell: (item: GoRelayEntryUsage) => item.ip_version },
                          { id: "ports", header: isZh ? "端口" : "Ports", cell: (item: GoRelayEntryUsage) => item.ports.join(", ") || "-" },
                          {
                            id: "devices",
                            header: isZh ? "设备" : "Devices",
                            cell: (item: GoRelayEntryUsage) => item.devices.map((device) => device.device_name).join(", ") || "-",
                          },
                        ]}
                      />
                    ),
                  },
                  {
                    id: "histories",
                    label: isZh ? "导入历史" : "Import history",
                    content: (
                      <Table
                        wrapLines
                        items={histories.data ?? []}
                        columnDefinitions={[
                          { id: "created_at", header: t("common.updated_at"), cell: (item: GoRelayDomainImportHistory) => formatDateTime(item.created_at) },
                          { id: "source_type", header: isZh ? "来源" : "Source", cell: (item: GoRelayDomainImportHistory) => item.source_type || "-" },
                          {
                            id: "applied",
                            header: isZh ? "应用数" : "Applied",
                            cell: (item: GoRelayDomainImportHistory) => item.applied_bindings?.length || 0,
                          },
                          {
                            id: "actions",
                            header: t("common.actions"),
                            cell: (item: GoRelayDomainImportHistory) => (
                              <InlineAction onClick={() => handleDeleteHistory(item.id)}>
                                {t("common.delete")}
                              </InlineAction>
                            ),
                          },
                        ]}
                      />
                    ),
                  },
                  {
                    id: "snapshots",
                    label: isZh ? "快照" : "Snapshots",
                    content: (
                      <Table
                        wrapLines
                        items={snapshots.data?.items ?? []}
                        columnDefinitions={[
                          {
                            id: "snapshot_id",
                            header: "Snapshot",
                            cell: (item: GoRelaySnapshot) => (
                              <SpaceBetween direction="horizontal" size="xs">
                                <Box variant="code">{item.snapshot_id}</Box>
                                {item.active && <Chip lit>{isZh ? "当前" : "Active"}</Chip>}
                              </SpaceBetween>
                            ),
                          },
                          { id: "status", header: t("common.status"), cell: (item: GoRelaySnapshot) => item.status },
                          { id: "node_count", header: isZh ? "节点数" : "Nodes", cell: (item: GoRelaySnapshot) => item.node_count },
                          { id: "device_count", header: isZh ? "设备数" : "Devices", cell: (item: GoRelaySnapshot) => item.device_count },
                          { id: "created_at", header: t("common.updated_at"), cell: (item: GoRelaySnapshot) => formatDateTime(item.created_at) },
                          {
                            id: "actions",
                            header: t("common.actions"),
                            cell: (item: GoRelaySnapshot) =>
                              item.active ? null : (
                                <InlineAction onClick={() => handleActivateSnapshot(item.snapshot_id)}>
                                  {isZh ? "激活" : "Activate"}
                                </InlineAction>
                              ),
                          },
                        ]}
                      />
                    ),
                  },
                  {
                    id: "subscriptions",
                    label: isZh ? "订阅" : "Subscriptions",
                    content: (
                      <Table
                        wrapLines
                        items={subscriptions.data ?? []}
                        columnDefinitions={[
                          { id: "device_name", header: t("devices.device_name"), cell: (item: GoRelaySubscription) => item.device_name },
                          {
                            id: "enabled",
                            header: t("common.status"),
                            cell: (item: GoRelaySubscription) =>
                              item.enabled ? (
                                <StatusBadge status="success">{t("common.enabled")}</StatusBadge>
                              ) : (
                                <StatusBadge status="stopped">{t("common.disabled")}</StatusBadge>
                              ),
                          },
                          {
                            id: "link",
                            header: isZh ? "导入链接" : "Import link",
                            cell: (item: GoRelaySubscription) => (
                              <CopyButton text={item.links?.clash_url || ""} />
                            ),
                          },
                          {
                            id: "actions",
                            header: t("common.actions"),
                            cell: (item: GoRelaySubscription) =>
                              item.enabled ? (
                                <InlineAction onClick={() => handleDisableSubscription(item.id)}>
                                  {isZh ? "禁用" : "Disable"}
                                </InlineAction>
                              ) : null,
                          },
                        ]}
                      />
                    ),
                  },
                ]}
              />
            </SpaceBetween>
          </WorkspaceLoader>
        )}
      </SpaceBetween>

      <GoRelaySourceEditModal
        visible={editModalVisible}
        source={editingSource}
        loading={createSource.isPending || updateSource.isPending}
        onSave={handleSave}
        onCancel={() => setEditModalVisible(false)}
      />

      <ConfirmModal visible={!!deleteTarget} onConfirm={handleDelete} onCancel={() => setDeleteTarget(null)}>
        {deleteTarget?.name}
      </ConfirmModal>

      <FormModal
        visible={!!credentialModal}
        header={credentialModal?.title ?? ""}
        loading={updateAccountProxy.isPending || updateDeviceProxy.isPending}
        confirmLabel={t("common.save")}
        onSubmit={handleCredentialSubmit}
        onCancel={() => setCredentialModal(null)}
      >
        <SpaceBetween size="l">
          <FormField label={credentialModal?.usernameLabel ?? ""}>
            <Input
              value={credentialModal?.username ?? ""}
              onChange={({ detail }) =>
                setCredentialModal((current) =>
                  current ? { ...current, username: detail.value } : current,
                )
              }
            />
          </FormField>
          <FormField label={credentialModal?.passwordLabel ?? ""}>
            <Input
              type="password"
              value={credentialModal?.password ?? ""}
              onChange={({ detail }) =>
                setCredentialModal((current) =>
                  current ? { ...current, password: detail.value } : current,
                )
              }
            />
          </FormField>
        </SpaceBetween>
      </FormModal>

      <FormModal
        visible={!!presetModal}
        header={isZh ? "更新策略 preset" : "Update strategy preset"}
        loading={updateStrategyPreset.isPending}
        confirmLabel={t("common.save")}
        onSubmit={handlePresetSubmit}
        onCancel={() => setPresetModal(null)}
      >
        <FormField label={presetModal ? `${isZh ? "设备" : "Device"}: ${presetModal.deviceName}` : ""}>
          <Select
            selectedOption={STRATEGY_PRESET_OPTIONS.find((option) => option.value === presetModal?.preset) ?? null}
            options={STRATEGY_PRESET_OPTIONS}
            onChange={({ detail }) =>
              setPresetModal((current) =>
                current ? { ...current, preset: detail.selectedOption.value ?? STRATEGY_PRESETS[0] } : current,
              )
            }
          />
        </FormField>
      </FormModal>

      <FormModal
        visible={!!bindingApprovalModal}
        header={isZh ? "批准域名绑定" : "Approve binding"}
        loading={updateDomainBinding.isPending}
        confirmLabel={isZh ? "批准并重建" : "Approve"}
        onSubmit={handleBindingApprovalSubmit}
        onCancel={() => setBindingApprovalModal(null)}
      >
        <SpaceBetween size="l">
          <FormField label={isZh ? "入口" : "Entry"}>
            <Input value={bindingApprovalModal?.entryName ?? ""} readOnly />
          </FormField>
          <FormField label="Host">
            <Input
              value={bindingApprovalModal?.hostValue ?? ""}
              onChange={({ detail }) =>
                setBindingApprovalModal((current) =>
                  current ? { ...current, hostValue: detail.value } : current,
                )
              }
            />
          </FormField>
        </SpaceBetween>
      </FormModal>
    </>
  );
}
