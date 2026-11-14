import { useCallback, useMemo, useState } from "react";
import { motion } from "motion/react";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useLocale } from "@/contexts/LocaleContext";
import { useGorelaySources, useStandardSources, useStatus } from "@/api/queries";
import { PageHeader } from "@/components/PageHeader";
import { GlassTabs } from "@/components/GlassTabs";
import { INGEST_KIND_MANUAL_NODES, INGEST_KIND_REMOTE_SUBSCRIPTION, StandardSourcesTab, type CreateRequest } from "./StandardSourcesTab";
import { GoRelaySourcesTab } from "./GoRelaySourcesTab";
import { RefreshPolicySection } from "./RefreshPolicySection";
import { gorelayHealth, needsAttention, sourceHealth } from "./sourceHealth";
import { proxyBridgeNote } from "./proxyBridge";
import { SLIDE_UP, SPRING_DEFAULT } from "@/motion";

export function SourcesPage() {
  const { t } = useLocale();
  const standard = useStandardSources();
  const gorelay = useGorelaySources();
  const status = useStatus();
  const [tab, setTab] = useState("standard");
  const [createRequest, setCreateRequest] = useState<CreateRequest | null>(null);

  const standardAttention = useMemo(
    () => (standard.data ?? []).filter((source) => needsAttention(sourceHealth(source, t))).length,
    [standard.data, t],
  );
  const bridgeBlocked = !!proxyBridgeNote(status.data);
  const gorelayAttention = useMemo(
    () => (gorelay.data ?? []).filter((account) => needsAttention(gorelayHealth(account, t))).length + (bridgeBlocked ? 1 : 0),
    [gorelay.data, t, bridgeBlocked],
  );
  const clearCreateRequest = useCallback(() => setCreateRequest(null), []);

  return (
    <ContentLayout header={
      <PageHeader
        title={t("sources.title")}
        actions={
          <ButtonDropdown variant="primary" items={[
            { id: INGEST_KIND_REMOTE_SUBSCRIPTION, text: t("sources.add_remote") },
            { id: INGEST_KIND_MANUAL_NODES, text: t("sources.add_manual") },
          ]} onItemClick={({ detail }) => {
            setTab("standard");
            setCreateRequest({ kind: detail.id, at: Date.now() });
          }}>{t("sources.add_source")}</ButtonDropdown>
        }
      />
    }>
      <motion.div initial={SLIDE_UP.initial} animate={SLIDE_UP.animate} transition={SPRING_DEFAULT}>
        <GlassTabs
          ariaLabel={t("sources.title")}
          activeId={tab}
          onChange={setTab}
          tabs={[
            {
              id: "standard",
              label: t("sources.tab_standard"),
              count: standard.data?.length,
              attention: standardAttention > 0,
              attentionLabel: t("sources.tab_attention", { name: t("sources.tab_standard"), count: standardAttention }),
              content: <StandardSourcesTab createRequest={createRequest} onCreateHandled={clearCreateRequest} />,
            },
            {
              id: "gorelay",
              label: "GoRelay",
              count: gorelay.data?.length,
              attention: gorelayAttention > 0,
              attentionLabel: t("sources.tab_attention", { name: "GoRelay", count: gorelayAttention }),
              content: <GoRelaySourcesTab />,
            },
          ]}
        />
        <RefreshPolicySection />
      </motion.div>
    </ContentLayout>
  );
}
