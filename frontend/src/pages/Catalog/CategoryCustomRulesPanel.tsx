import { useEffect, useState } from "react";
import {
  Table,
  Button,
  SpaceBetween,
  Input,
  FormField,
  Select,
  SelectProps,
} from "@cloudscape-design/components";
import { IconAction } from "@/components/InlineAction";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useCategories, useCategoryCustomRules, useContracts, useServiceCatalog } from "@/api/queries";
import { useAddCategoryCustomRule, useDeleteCategoryCustomRule, useUpdateCategoryBinding } from "@/api/mutations";
import { ConfirmModal } from "@/components/ConfirmModal";
import type { CategoryCustomRuleItem } from "@/types";

const RULE_TYPE_OPTIONS: SelectProps.Option[] = [
  { value: "DOMAIN", label: "DOMAIN" },
  { value: "DOMAIN-SUFFIX", label: "DOMAIN-SUFFIX" },
  { value: "DOMAIN-KEYWORD", label: "DOMAIN-KEYWORD" },
  { value: "IP-CIDR", label: "IP-CIDR" },
  { value: "IP-CIDR6", label: "IP-CIDR6" },
];

interface CategoryCustomRulesPanelProps {
  categoryName: string;
}

export function CategoryCustomRulesPanel({ categoryName }: CategoryCustomRulesPanelProps) {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const categories = useCategories();
  const rules = useCategoryCustomRules(categoryName);
  const contracts = useContracts();
  const serviceCatalog = useServiceCatalog();
  const addRule = useAddCategoryCustomRule();
  const deleteRule = useDeleteCategoryCustomRule();
  const updateBinding = useUpdateCategoryBinding();

  const [ruleType, setRuleType] = useState("DOMAIN-SUFFIX");
  const [value, setValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<CategoryCustomRuleItem | null>(null);
  const [selectedContractId, setSelectedContractId] = useState("");
  const [lastCommittedContractId, setLastCommittedContractId] = useState("");
  const effectiveContractId = rules.data?.effectiveContractId ?? "";
  const effectiveContractDisplayName = rules.data?.effectiveContractDisplayName ?? "";
  const hasEffectiveContract = Boolean(effectiveContractId);
  const currentCategory = (categories.data ?? []).find((item) => item.name === categoryName);
  const currentBinding = (serviceCatalog.data ?? []).find((entry) => entry.category_name === categoryName);
  const storedContractId = String(currentBinding?.contract_id ?? currentCategory?.stored_contract_id ?? "").trim();

  useEffect(() => {
    setSelectedContractId(storedContractId);
    setLastCommittedContractId(storedContractId);
  }, [storedContractId]);

  const contractOptions: SelectProps.Option[] = (contracts.data ?? [])
    .filter((contract) => contract.enabled)
    .map((contract) => ({ value: contract.id, label: contract.display_name }));

  const handleAdd = () => {
    if (!value.trim()) return;
    addRule.mutate(
      { name: categoryName, rule_type: ruleType, value: value.trim() },
      {
        onSuccess: () => {
          addToast("success", t("toast.create_success"));
          setValue("");
        },
        onError: (err) => addToast("error", t("toast.create_error"), err.message),
      },
    );
  };

  const handleContractChange = (nextContractId: string) => {
    setSelectedContractId(nextContractId);
    updateBinding.mutate(
      {
        name: categoryName,
        contract_id: nextContractId,
      },
      {
        onSuccess: () => {
          setLastCommittedContractId(nextContractId);
          addToast("success", t("toast.update_success"), t("catalog.contract_group_updated"));
        },
        onError: (err) => {
          setSelectedContractId(lastCommittedContractId);
          addToast("error", t("toast.update_error"), err.message || t("catalog.contract_group_update_failed"));
        },
      },
    );
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteRule.mutate(
      { name: categoryName, ruleId: deleteTarget.id },
      {
        onSuccess: () => {
          addToast("success", t("toast.delete_success"));
          setDeleteTarget(null);
        },
        onError: (err) => addToast("error", t("toast.delete_error"), err.message),
      },
    );
  };

  return (
    <SpaceBetween size="m">
      <div className="s-row">
        <FormField label={t("advanced.rule_type")}>
          <Select
            selectedOption={RULE_TYPE_OPTIONS.find((o) => o.value === ruleType) || null}
            options={RULE_TYPE_OPTIONS}
            onChange={({ detail }) => setRuleType(detail.selectedOption.value!)}
          />
        </FormField>
        <div className="s-grow">
          <FormField label={t("common.value")}>
            <Input value={value} onChange={({ detail }) => setValue(detail.value)} />
          </FormField>
        </div>
        <FormField
          label={t("catalog.contract_group")}
          description={t("catalog.custom_rules_contract_group_help")}
        >
          <Select
            selectedOption={contractOptions.find((option) => option.value === selectedContractId) ?? null}
            options={contractOptions}
            placeholder={t("catalog.select_contract_group_placeholder")}
            filteringType="auto"
            filteringPlaceholder={t("catalog.contract_group_select_search_placeholder")}
            expandToViewport
            statusType={contracts.isLoading ? "loading" : "finished"}
            disabled={contracts.isLoading || categories.isLoading || updateBinding.isPending}
            onChange={({ detail }) => {
              const nextContractId = detail.selectedOption.value ?? "";
              if (!nextContractId || nextContractId === selectedContractId) {
                return;
              }
              handleContractChange(nextContractId);
            }}
          />
        </FormField>
        <Button
          variant="primary"
          onClick={handleAdd}
          loading={addRule.isPending}
          disabled={!hasEffectiveContract}
        >
          {t("common.add")}
        </Button>
      </div>

      {!hasEffectiveContract && (
        <span className="s-muted s-small">{t("catalog.custom_rules_pending_contract_group_help")}</span>
      )}

      <Table
        variant="embedded"
        items={rules.data?.items ?? []}
        loading={rules.isLoading}
        columnDefinitions={[
          { id: "rule_type", header: t("advanced.rule_type"), cell: (item) => item.rule_type },
          { id: "value", header: t("common.value"), cell: (item) => <span className="s-mono">{item.value}</span> },
          {
            id: "contract",
            header: t("catalog.contract_group"),
            cell: (item) => item.effective_contract_display_name || effectiveContractDisplayName || "-",
          },
          {
            id: "actions",
            header: "",
            cell: (item) => (
              <IconAction iconName="remove" ariaLabel={`${t("common.delete")} ${item.value}`} onClick={() => setDeleteTarget(item)} />
            ),
          },
        ]}
        empty={<div className="s-empty">{t("common.no_items")}</div>}
      />

      <ConfirmModal visible={!!deleteTarget} onConfirm={handleDelete} onCancel={() => setDeleteTarget(null)}>
        {deleteTarget && `${deleteTarget.rule_type} ${deleteTarget.value}`}
      </ConfirmModal>
    </SpaceBetween>
  );
}
