import { useState } from "react";
import {
  Table,
  Button,
  SpaceBetween,
  Input,
  FormField,
  Select,
  SelectProps,
} from "@cloudscape-design/components";
import { Section, Surface } from "@/components/Section";
import { IconAction } from "@/components/InlineAction";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useCustomRules, useContracts } from "@/api/queries";
import { useCreateCustomRule, useDeleteCustomRule } from "@/api/mutations";
import { ConfirmModal } from "@/components/ConfirmModal";
import { formatDateTime } from "@/utils/formatting";
import type { CustomRule } from "@/types";

const RULE_TYPE_OPTIONS: SelectProps.Option[] = [
  { value: "DOMAIN", label: "DOMAIN" },
  { value: "DOMAIN-SUFFIX", label: "DOMAIN-SUFFIX" },
  { value: "DOMAIN-KEYWORD", label: "DOMAIN-KEYWORD" },
  { value: "IP-CIDR", label: "IP-CIDR" },
  { value: "IP-CIDR6", label: "IP-CIDR6" },
  { value: "GEOIP", label: "GEOIP" },
  { value: "PROCESS-NAME", label: "PROCESS-NAME" },
];

export function CustomRulesTab() {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const rules = useCustomRules();
  const contracts = useContracts();
  const createRule = useCreateCustomRule();
  const deleteRule = useDeleteCustomRule();

  const [ruleType, setRuleType] = useState("DOMAIN-SUFFIX");
  const [value, setValue] = useState("");
  const [targetContractId, setTargetContractId] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<CustomRule | null>(null);

  const contractOptions: SelectProps.Option[] = (contracts.data ?? [])
    .filter((c) => c.enabled)
    .map((c) => ({ value: c.id, label: c.display_name }));

  const handleCreate = () => {
    if (!value.trim() || !targetContractId) return;
    createRule.mutate(
      { rule_type: ruleType, value: value.trim(), target_contract_id: targetContractId },
      {
        onSuccess: () => {
          addToast("success", t("toast.create_success"));
          setValue("");
        },
        onError: (err) => addToast("error", t("toast.create_error"), err.message),
      },
    );
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteRule.mutate(deleteTarget.id, {
      onSuccess: () => {
        addToast("success", t("toast.delete_success"));
        setDeleteTarget(null);
      },
      onError: (err) => addToast("error", t("toast.delete_error"), err.message),
    });
  };

  return (
    <SpaceBetween size="xl">
      <Section title={t("advanced.add_rule")}>
        <Surface>
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
                <Input value={value} onChange={({ detail }) => setValue(detail.value)} placeholder="example.com" />
              </FormField>
            </div>
            <div className="s-grow">
              <FormField label={t("advanced.target_group")}>
                <Select
                  selectedOption={contractOptions.find((o) => o.value === targetContractId) || null}
                  options={contractOptions}
                  onChange={({ detail }) => setTargetContractId(detail.selectedOption.value!)}
                  placeholder={t("advanced.select_target_group")}
                  filteringType="auto"
                />
              </FormField>
            </div>
            <Button variant="primary" onClick={handleCreate} loading={createRule.isPending}>
              {t("common.add")}
            </Button>
          </div>
        </Surface>
      </Section>

      <Table
        items={rules.data ?? []}
        loading={rules.isLoading}
        columnDefinitions={[
          { id: "rule_type", header: t("advanced.rule_type"), cell: (item) => item.rule_type },
          { id: "value", header: t("common.value"), cell: (item) => <span className="s-mono">{item.value}</span> },
          {
            id: "target_group",
            header: t("advanced.target_group"),
            cell: (item) => item.target_contract_display_name || item.target_group || "-",
          },
          { id: "category_name", header: t("catalog.title"), cell: (item) => item.category_name || "-" },
          { id: "created_at", header: t("common.updated_at"), cell: (item) => formatDateTime(item.created_at) },
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
