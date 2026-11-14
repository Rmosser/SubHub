import { motion } from "motion/react";
import { useNavigate } from "react-router-dom";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useLocale } from "@/contexts/LocaleContext";
import { useSplitPanel } from "@/contexts/SplitPanelContext";
import { useDevices } from "@/api/queries";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import { PageHeader } from "@/components/PageHeader";
import { PaperNote } from "@/components/PaperNote";
import { InlineAction } from "@/components/InlineAction";
import { ReasonText } from "@/components/ReasonText";
import { DevicesTable } from "./DevicesTable";
import { DeviceLinksPanel } from "./DeviceLinksPanel";
import { DevicePreviewPanel } from "./DevicePreviewPanel";
import { SLIDE_UP, SPRING_DEFAULT } from "@/motion";
import { overlayReasonText } from "@/utils/statusText";
import type { ClientTarget } from "@/constants/clients";
import type { DeviceWithLinks } from "@/types";

export function DevicesPage() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const devices = useDevices();
  const { openSplitPanel } = useSplitPanel();
  // overlay 状态是场景级的，所有设备相同：页面顶部说一次，不在每张卡片上重复。
  const overlay = devices.data?.[0]?.overlay_status;
  const overlayReason = overlay ? overlayReasonText(overlay, t) : "";

  const handleCopyLinks = (device: DeviceWithLinks) => {
    openSplitPanel(
      `${t("devices.links_panel")} — ${device.device_name}`,
      <DeviceLinksPanel device={device} />,
    );
  };

  const handlePreview = (device: DeviceWithLinks, target: ClientTarget) => {
    openSplitPanel(
      `${t("devices.preview_panel")} — ${device.device_name}`,
      <DevicePreviewPanel device={device} initialTarget={target} />,
    );
  };

  return (
    <ContentLayout header={<PageHeader title={t("devices.title")} />}>
      <WorkspaceLoader loading={devices.isLoading} error={devices.error} onRetry={() => devices.refetch()}>
        <motion.div initial={SLIDE_UP.initial} animate={SLIDE_UP.animate} transition={SPRING_DEFAULT}>
          <div className="s-stack">
            {overlay && overlay.available === false ? (
              <PaperNote action={<InlineAction href="/manage/advanced" onFollow={(event) => { event.preventDefault(); navigate("/advanced"); }}>{t("devices.overlay_open_advanced")}</InlineAction>}>
                <strong>{t("devices.overlay_attention")}</strong>
                {overlayReason ? <ReasonText text={overlayReason} /> : null}
              </PaperNote>
            ) : null}
            <DevicesTable
              items={devices.data ?? []}
              loading={devices.isLoading}
              onPreview={handlePreview}
              onCopyLinks={handleCopyLinks}
            />
          </div>
        </motion.div>
      </WorkspaceLoader>
    </ContentLayout>
  );
}
