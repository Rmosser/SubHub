import { useState } from "react";
import { motion } from "motion/react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Button from "@cloudscape-design/components/button";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useSplitPanel } from "@/contexts/SplitPanelContext";
import { useCategories, useServiceCatalog } from "@/api/queries";
import { useRefreshCatalog } from "@/api/mutations";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import { PageHeader } from "@/components/PageHeader";
import { CatalogTable } from "./CatalogTable";
import { CategoryDetailPanel } from "./CategoryDetailPanel";
import { GroupManagementModal } from "./GroupManagementModal";
import { PinManagementModal } from "./PinManagementModal";
import { BulkAssignModal } from "./BulkAssignModal";
import { ManualCategoryModal } from "./ManualCategoryModal";
import { DirectnessReviewBanner } from "./DirectnessReviewBanner";
import { SLIDE_UP, SPRING_DEFAULT } from "@/motion";
import type { RuleCategory } from "@/types";

export function CatalogPage() {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const { openSplitPanel } = useSplitPanel();
  const categories = useCategories();
  const catalog = useServiceCatalog();
  const refreshCatalog = useRefreshCatalog();

  const [groupModal, setGroupModal] = useState(false);
  const [pinModal, setPinModal] = useState(false);
  const [bulkAssignModal, setBulkAssignModal] = useState(false);
  const [manualModal, setManualModal] = useState(false);

  const handleSelect = (category: RuleCategory) => {
    openSplitPanel(
      category.name,
      <CategoryDetailPanel categoryName={category.name} />,
    );
  };

  const handleRefresh = () => {
    refreshCatalog.mutate(undefined, {
      onSuccess: () => addToast("success", t("refresh.done")),
      onError: (err) => addToast("error", err.message),
    });
  };

  return (
    <ContentLayout
      header={
        <PageHeader
          title={t("catalog.title")}
          actions={
            <>
              <Button onClick={() => setManualModal(true)}>{t("catalog.create_manual")}</Button>
              <ButtonDropdown items={[
                { id: "groups", text: t("catalog.manage_groups") }, { id: "pins", text: t("catalog.manage_pins") }, { id: "bulk", text: t("catalog.bulk_assign") },
              ]} onItemClick={({ detail }) => {
                if (detail.id === "groups") setGroupModal(true);
                if (detail.id === "pins") setPinModal(true);
                if (detail.id === "bulk") setBulkAssignModal(true);
              }}>{t("common.manage")}</ButtonDropdown>
              <Button variant="primary" onClick={handleRefresh} loading={refreshCatalog.isPending}>
                {t("catalog.refresh_catalog")}
              </Button>
            </>
          }
        />
      }
    >
      <WorkspaceLoader
        loading={categories.isLoading}
        error={categories.error}
        onRetry={() => categories.refetch()}
      >
        <motion.div initial={SLIDE_UP.initial} animate={SLIDE_UP.animate} transition={SPRING_DEFAULT}>
          <SpaceBetween size="l">
            <DirectnessReviewBanner />
            <CatalogTable
              categories={categories.data ?? []}
              catalogEntries={catalog.data ?? []}
              loading={categories.isLoading}
              onSelect={handleSelect}
            />
          </SpaceBetween>
        </motion.div>
      </WorkspaceLoader>

      <GroupManagementModal visible={groupModal} onClose={() => setGroupModal(false)} />
      <PinManagementModal
        visible={pinModal}
        categories={categories.data ?? []}
        catalogEntries={catalog.data ?? []}
        onClose={() => setPinModal(false)}
      />
      <BulkAssignModal
        visible={bulkAssignModal}
        categories={categories.data ?? []}
        catalogEntries={catalog.data ?? []}
        onClose={() => setBulkAssignModal(false)}
      />
      <ManualCategoryModal visible={manualModal} onClose={() => setManualModal(false)} />
    </ContentLayout>
  );
}
