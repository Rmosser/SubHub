import { motion } from "motion/react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { PageHeader } from "@/components/PageHeader";
import { GlassTabs } from "@/components/GlassTabs";
import { useLocale } from "@/contexts/LocaleContext";
import { LogRoutingPanel } from "./LogRoutingPanel";
import { WorkflowPanel } from "./WorkflowPanel";
import { LlmSettingsPanel } from "./LlmSettingsPanel";
import { SLIDE_UP, SPRING_DEFAULT } from "@/motion";

export function LLMWorkflowsPage() {
  const { t } = useLocale();

  return (
    <ContentLayout header={<PageHeader title={t("llm.title")} description={t("llm.page_purpose")} />}>
      <motion.div initial={SLIDE_UP.initial} animate={SLIDE_UP.animate} transition={SPRING_DEFAULT}>
        <SpaceBetween size="l">
          <GlassTabs
            ariaLabel={t("llm.title")}
            tabs={[
              {
                id: "log-routing",
                label: t("llm.log_routing"),
                content: <LogRoutingPanel />,
              },
              {
                id: "directness",
                label: t("llm.directness_review"),
                content: <WorkflowPanel workflowType="directness" />,
              },
              {
                id: "routing",
                label: t("llm.routing_assignment"),
                content: <WorkflowPanel workflowType="routing" />,
              },
              {
                id: "grouping",
                label: t("llm.grouping"),
                content: <WorkflowPanel workflowType="grouping" />,
              },
            ]}
          />
          <LlmSettingsPanel />
        </SpaceBetween>
      </motion.div>
    </ContentLayout>
  );
}
