import { useEffect, useState } from "react";
import { motion } from "motion/react";
import {
  Button,
  FormField,
  Select,
  Spinner,
} from "@cloudscape-design/components";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { PageHeader } from "@/components/PageHeader";
import { PaperNote } from "@/components/PaperNote";
import { ErrorNote } from "@/components/ErrorNote";
import { useContractReferences, useContracts } from "@/api/queries";
import { useCreateContract, useDeleteContract, useUpdateContract } from "@/api/mutations";
import { ConfirmModal } from "@/components/ConfirmModal";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useScenario } from "@/contexts/ScenarioContext";
import { SLIDE_UP, SPRING_DEFAULT } from "@/motion";
import { ContractEditModal } from "./ContractEditModal";
import { ContractsTable } from "./ContractsTable";
import type { ContractMutationPayload, RouteContract } from "@/types";

const DEFAULT_SCENARIO_ID = "scenario-default";

const REFERENCE_KIND_TRANSLATIONS: Record<string, string> = {
  service_catalog: "contracts.reference_kind_service_catalog",
  custom_rules: "contracts.reference_kind_custom_rules",
  process_rules: "contracts.reference_kind_process_rules",
  external_proxy_programs: "contracts.reference_kind_external_proxy_programs",
  standard_sources: "contracts.reference_kind_standard_sources",
  default: "contracts.reference_kind_default",
};

export function ContractsPage() {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const { selectedScenarioId } = useScenario();
  const contracts = useContracts();
  const createContract = useCreateContract();
  const updateContract = useUpdateContract();
  const deleteContract = useDeleteContract();

  const [editingContract, setEditingContract] = useState<RouteContract | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<RouteContract | null>(null);
  const [replacementContractId, setReplacementContractId] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const contractReferences = useContractReferences(deleteTarget?.id, Boolean(deleteTarget));

  const referenceData = contractReferences.data;
  const activeReferences = (referenceData?.references ?? []).filter((item) => item.count > 0);
  const hasStandardSourceReferences = activeReferences.some((item) => item.kind === "standard_sources");
  const hasDefaultReference = referenceData?.is_default === true;
  const deletingGlobalContract = Boolean(deleteTarget && !deleteTarget.owner_scenario_id);
  const replacementContracts = (contracts.data ?? []).filter(
    (item) =>
      item.id !== deleteTarget?.id &&
      item.enabled &&
      (!deletingGlobalContract || !item.owner_scenario_id) &&
      (!hasStandardSourceReferences || item.can_bind_standard_source === true) &&
      (!hasDefaultReference || item.routing_action !== "reject"),
  );
  const replacementRequired = referenceData ? !referenceData.can_delete : true;
  const deleteReady = Boolean(
    referenceData &&
      !contractReferences.isLoading &&
      !contractReferences.isFetching &&
      !contractReferences.isError &&
      (!replacementRequired || replacementContractId),
  );

  useEffect(() => {
    setReplacementContractId("");
    setDeleteError(null);
  }, [deleteTarget]);

  const modalLoading = createContract.isPending || updateContract.isPending;
  const createLabel =
    selectedScenarioId === DEFAULT_SCENARIO_ID
      ? t("contracts.add_contract")
      : t("contracts.add_scenario_contract");

  const handleSave = (data: ContractMutationPayload) => {
    if (editingContract && "id" in data) {
      updateContract.mutate(data, {
        onSuccess: () => {
          addToast("success", t("toast.save_success"));
          setEditingContract(null);
          setCreating(false);
        },
        onError: (err: Error) => addToast("error", t("toast.save_error"), err.message),
      });
      return;
    }
    createContract.mutate(data, {
      onSuccess: () => {
        addToast("success", t("toast.save_success"));
        setEditingContract(null);
        setCreating(false);
      },
      onError: (err: Error) => addToast("error", t("toast.save_error"), err.message),
    });
  };

  const openDeleteModal = (contract: RouteContract) => {
    setDeleteError(null);
    setReplacementContractId("");
    setDeleteTarget(contract);
  };

  const closeDeleteModal = () => {
    setDeleteTarget(null);
    setReplacementContractId("");
    setDeleteError(null);
  };

  const handleDelete = () => {
    if (!deleteTarget || !deleteReady) {
      return;
    }
    deleteContract.mutate(
      {
        id: deleteTarget.id,
        replacement_contract_id: replacementContractId || undefined,
      },
      {
        onSuccess: () => {
          addToast("success", t("toast.delete_success"));
          closeDeleteModal();
        },
        onError: (err: Error) => setDeleteError(err.message),
      },
    );
  };

  return (
    <ContentLayout
      header={(
        <PageHeader
          title={t("contracts.title")}
          actions={<Button variant="primary" onClick={() => setCreating(true)}>{createLabel}</Button>}
        />
      )}
    >
      <WorkspaceLoader
        loading={contracts.isLoading}
        error={contracts.error}
        onRetry={() => contracts.refetch()}
      >
        <motion.div initial={SLIDE_UP.initial} animate={SLIDE_UP.animate} transition={SPRING_DEFAULT}>
          <ContractsTable
            items={contracts.data ?? []}
            loading={contracts.isLoading}
            onEdit={setEditingContract}
            onDelete={openDeleteModal}
          />
        </motion.div>
      </WorkspaceLoader>

      <ContractEditModal
        visible={creating || !!editingContract}
        contract={editingContract}
        loading={modalLoading}
        onSave={handleSave}
        onCancel={() => {
          setCreating(false);
          setEditingContract(null);
        }}
      />

      <ConfirmModal
        visible={!!deleteTarget}
        header={t("contracts.delete_contract")}
        confirmDisabled={!deleteReady || deleteContract.isPending}
        onConfirm={handleDelete}
        onCancel={closeDeleteModal}
      >
        <p className="s-dialog-lead">{deleteTarget?.display_name}</p>
        {contractReferences.isLoading || contractReferences.isFetching ? (
          <div className="s-row s-muted" role="status">
            <Spinner size="normal" />
            <span>{t("contracts.references_loading")}</span>
          </div>
        ) : null}
        {contractReferences.isError ? (
          <ErrorNote
            title={t("contracts.references_load_error")}
            reason={(contractReferences.error as Error)?.message}
            onRetry={() => contractReferences.refetch()}
          />
        ) : null}
        {deleteError ? <ErrorNote title={t("contracts.delete_failure")} reason={deleteError} /> : null}
        {referenceData ? (
          <>
            {referenceData.is_default ? (
              referenceData.can_delete ? (
                <p className="s-dialog-lead">{t("contracts.default_delete_impact")}</p>
              ) : (
                <PaperNote>{t("contracts.default_delete_impact")}</PaperNote>
              )
            ) : null}
            {activeReferences.length > 0 ? (
              <PaperNote>
                <strong>{t("contracts.references_found")}</strong>
                <ul className="s-dialog-list">
                  {activeReferences.map((reference) => (
                    <li key={`${reference.kind}-${reference.scenario_id || "global"}`}>
                      {t("contracts.reference_count", {
                        kind: REFERENCE_KIND_TRANSLATIONS[reference.kind]
                          ? t(REFERENCE_KIND_TRANSLATIONS[reference.kind])
                          : reference.kind,
                        count: reference.count,
                      })}
                      {reference.scenario_id
                        ? ` (${t("contracts.reference_scenario", {
                            id:
                              reference.scenario_id === DEFAULT_SCENARIO_ID
                                ? t("contracts.default")
                                : reference.scenario_id,
                          })})`
                        : ""}
                    </li>
                  ))}
                </ul>
              </PaperNote>
            ) : null}
            {replacementRequired && replacementContracts.length === 0 ? (
              <ErrorNote title={t("contracts.no_replacement_available")} />
            ) : null}
            {replacementContracts.length > 0 ? (
              <FormField
                label={t("contracts.replacement_contract")}
                description={replacementRequired ? undefined : t("contracts.replacement_contract_help")}
                errorText={replacementRequired && !replacementContractId ? t("contracts.replacement_contract_required") : undefined}
              >
                <Select
                  selectedOption={
                    replacementContracts
                      .map((item) => ({ value: item.id, label: item.display_name }))
                      .find((item) => item.value === replacementContractId) || null
                  }
                  options={replacementContracts.map((item) => ({
                    value: item.id,
                    label: item.display_name,
                    description: item.scope === "scenario" ? t("contracts.scope_scenario") : t("contracts.scope_global"),
                  }))}
                  placeholder={t("contracts.replacement_contract_placeholder")}
                  onChange={({ detail }) => {
                    setReplacementContractId(detail.selectedOption.value || "");
                    setDeleteError(null);
                  }}
                />
              </FormField>
            ) : null}
            {referenceData.can_delete && activeReferences.length === 0 ? (
              <p className="s-dialog-lead">{t("contracts.delete_safe")}</p>
            ) : null}
          </>
        ) : null}
      </ConfirmModal>
    </ContentLayout>
  );
}
