import { useState } from "react";
import { Button, Select, Icon } from "@cloudscape-design/components";
import { useLocale } from "@/contexts/LocaleContext";
import { useSplitPanelControls } from "@/contexts/SplitPanelContext";
import { StatusBadge } from "@/components/StatusBadge";
import { CopyButton } from "@/components/CopyButton";
import { InlineAction } from "@/components/InlineAction";
import { formatDateTime } from "@/utils/formatting";
import type { DeviceWithLinks } from "@/types";
import { CLIENT_TARGETS, CLIENT_TARGET_OPTIONS, type ClientTarget } from "@/constants/clients";

interface DevicesTableProps {
  items: DeviceWithLinks[];
  loading: boolean;
  onPreview: (device: DeviceWithLinks, target: ClientTarget) => void;
  onCopyLinks: (device: DeviceWithLinks) => void;
}

function DeviceDelivery({ device, onPreview, onCopyLinks }: { device: DeviceWithLinks; onPreview: (target: ClientTarget) => void; onCopyLinks: () => void }) {
  const { t, locale } = useLocale();
  const isZh = locale === "zh-CN";
  const drawerId = useSplitPanelControls();
  const [client, setClient] = useState<ClientTarget>(() => CLIENT_TARGETS.find((target) => device.links[`${target}_url`]) ?? "surge");
  const url = String(device.links[`${client}_url`] || "").trim();
  const subscriptionId = device.subscription_id;
  const mask = subscriptionId.length > 8 ? `${subscriptionId.slice(0,4)}••••${subscriptionId.slice(-4)}` : "••••";
  return <article className="device-card">
    <div className="device-card-header">
      <div className="device-card-identity"><div className="device-glyph" aria-hidden="true"><Icon name="multiscreen" /></div><div><h2>{device.device_name}</h2><div className="device-card-key">{device.device_key}</div></div></div>
      <StatusBadge status={device.enabled ? "success" : "stopped"}>{device.enabled ? t("common.enabled") : t("common.disabled")}</StatusBadge>
    </div>
    <div className="device-delivery">
      <div><span className="device-delivery-label">{isZh ? "客户端" : "CLIENT"}</span><Select ariaLabel={`${device.device_name} ${isZh ? "客户端" : "client"}`} options={CLIENT_TARGET_OPTIONS} selectedOption={CLIENT_TARGET_OPTIONS.find((item) => item.value === client) ?? null} onChange={({ detail }) => setClient(detail.selectedOption.value as ClientTarget)} /></div>
      <div><span className="device-delivery-label">{isZh ? "订阅链接" : "SUBSCRIPTION LINK"}</span>{url ? <code className="device-url" title={url}>{url}</code> : <StatusBadge status="stopped">{t("devices.no_recommended_link")}</StatusBadge>}</div>
      <div className="device-delivery-actions">{url && <CopyButton text={url} label={isZh ? "复制链接" : "Copy link"} variant="normal" />}<Button ariaControls={drawerId} onClick={() => onPreview(client)}>{t("devices.preview")}</Button></div>
    </div>
    <div className="device-card-footer"><span>{t("devices.last_seen")}: {formatDateTime(device.last_seen_at)}</span><InlineAction ariaControls={drawerId} onClick={onCopyLinks}>{t("devices.more_links")}</InlineAction><details><summary>{isZh ? "订阅凭据" : "Subscription credentials"}</summary><div className="device-secret"><code>{mask}</code><CopyButton text={subscriptionId} label={isZh ? "复制订阅 ID" : "Copy subscription ID"} /></div></details></div>
  </article>;
}

export function DevicesTable({ items, onPreview, onCopyLinks }: DevicesTableProps) {
  const { locale } = useLocale();
  const isZh = locale === "zh-CN";
  if (items.length === 0) return <div className="workbench-list workbench-empty"><div className="workbench-empty-mark" aria-hidden="true">▣</div><h3>{isZh ? "等待你的第一台设备" : "Ready for your first device"}</h3><p>{isZh ? "设备会在连接服务后出现。先添加来源，随后为设备生成订阅。" : "Devices appear after connecting to the service. Add a source, then generate a subscription for your device."}</p><div style={{ marginTop: 20 }}><Button href="/manage/sources">{isZh ? "管理来源" : "Manage sources"}</Button></div></div>;
  return <div className="device-list">{items.map((device) => <DeviceDelivery key={device.device_key} device={device} onPreview={(target) => onPreview(device, target)} onCopyLinks={() => onCopyLinks(device)} />)}</div>;
}
