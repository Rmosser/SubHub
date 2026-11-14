import { motion } from "motion/react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { PageHeader } from "@/components/PageHeader";
import { GlassTabs } from "@/components/GlassTabs";
import { useLocale } from "@/contexts/LocaleContext";
import { CustomRulesTab } from "./CustomRulesTab";
import { ProcessRulesTab } from "./ProcessRulesTab";
import { ExternalProxyProgramsTab } from "./ExternalProxyProgramsTab";
import { PolicyBackupTab } from "./PolicyBackupTab";
import { SystemStatusTab } from "./SystemStatusTab";
import { SLIDE_UP, SPRING_DEFAULT } from "@/motion";

export function AdvancedPage() {
  const { t } = useLocale();

  return (
    <ContentLayout
      header={<PageHeader title={t("advanced.title")} />}
    >
      <motion.div initial={SLIDE_UP.initial} animate={SLIDE_UP.animate} transition={SPRING_DEFAULT}>
        <GlassTabs
          ariaLabel={t("advanced.title")}
          tabs={[
            {
              id: "system-status",
              label: t("advanced.system_status"),
              content: <SystemStatusTab />,
            },
            {
              id: "custom-rules",
              label: t("advanced.custom_rules"),
              content: <CustomRulesTab />,
            },
            {
              id: "process-rules",
              label: t("advanced.process_rules"),
              content: <ProcessRulesTab />,
            },
            {
              id: "external-proxy",
              label: t("advanced.external_proxy"),
              content: <ExternalProxyProgramsTab />,
            },
            {
              id: "policy-backup",
              label: t("advanced.policy_backup"),
              content: <PolicyBackupTab />,
            },
          ]}
        />
      </motion.div>
    </ContentLayout>
  );
}
