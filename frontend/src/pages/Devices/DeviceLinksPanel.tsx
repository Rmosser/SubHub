import { CopyButton } from "@/components/CopyButton";
import { Chip } from "@/components/Chip";
import { PaperNote } from "@/components/PaperNote";
import { useLocale } from "@/contexts/LocaleContext";
import type { DeviceLinks, DeviceWithLinks } from "@/types";
import { CLIENT_TARGETS, type ClientTarget } from "@/constants/clients";
import { useDevices } from "@/api/queries";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";

interface DeviceLinksPanelProps {
  device: DeviceWithLinks;
}

interface LinkVariant {
  target: ClientTarget;
  url: string;
}

function buildScenarioUrl(links: Partial<DeviceLinks>, target: string): string {
  const normalizedTarget = String(target || "").trim();
  const key = `${normalizedTarget}_url`;
  return String(links[key] || "").trim();
}

function buildLinkVariants(links: Partial<DeviceLinks>): LinkVariant[] {
  return CLIENT_TARGETS.map((target) => ({ target, url: buildScenarioUrl(links, target) }));
}

// 推荐链接是第一条可用的客户端链接：在列表里点亮它，不再单独用提示框重复一遍。
export function DeviceLinksPanel({ device }: DeviceLinksPanelProps) {
  const { t } = useLocale();
  const devices = useDevices();
  const currentDevice = devices.data?.find((item) => item.subscription_id === device.subscription_id);
  const links = currentDevice?.enabled ? currentDevice.links : {};
  const variants = buildLinkVariants(links);
  const recommended = variants.find((variant) => variant.url)?.target ?? null;

  return (
    <WorkspaceLoader loading={devices.isLoading} error={devices.error} onRetry={() => devices.refetch()}>
      <div className="s-stack">
        {recommended ? null : (
          <PaperNote>
            <strong>{t("devices.no_recommended_link")}</strong>
            <div className="s-muted">{t("devices.no_recommended_link_help")}</div>
          </PaperNote>
        )}
        <ul className="s-link-list" aria-label={t("devices.current_scenario_links")}>
          {variants.map((variant) => (
            <li key={variant.target}>
              <div className="s-link-head">
                <span className="s-cell-title">{variant.target}</span>
                {variant.target === recommended ? <Chip lit>{t("devices.recommended_link")}</Chip> : null}
              </div>
              {variant.url ? (
                <div className="s-link-value">
                  <code className="s-mono" title={variant.url}>{variant.url}</code>
                  <CopyButton
                    text={variant.url}
                    label={variant.target === recommended ? t("devices.copy_recommended") : `${t("common.copy")} ${variant.target}`}
                  />
                </div>
              ) : (
                <span className="s-muted s-small">{t("devices.link_unavailable")}</span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </WorkspaceLoader>
  );
}
