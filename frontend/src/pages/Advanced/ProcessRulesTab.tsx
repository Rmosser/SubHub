import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useProcessRules, useContracts } from "@/api/queries";
import { useSaveProcessRules } from "@/api/mutations";
import { EditableTable, type EditableColumn } from "@/components/EditableTable";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import type { ProcessRuleTemplate } from "@/types";
import { PROCESS_RULE_TYPES, validateProcessRules } from "./formValidation";

export function ProcessRulesTab() {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const processRules = useProcessRules();
  const contracts = useContracts();
  const saveRules = useSaveProcessRules();

  const contractOptions = (contracts.data ?? [])
    .filter((c) => c.enabled)
    .map((c) => ({ value: c.id, label: c.display_name }));

  const columns: EditableColumn<ProcessRuleTemplate>[] = [
    {
      id: "match_type",
      header: t("advanced.match_type"),
      editType: "select",
      selectOptions: PROCESS_RULE_TYPES.map((value) => ({ value, label: value })),
      cell: (item) => item.match_type,
    },
    {
      id: "value",
      header: t("common.value"),
      editType: "text",
      cell: (item) => item.value,
    },
    {
      id: "contract_id",
      header: t("catalog.contract"),
      editType: "select",
      selectOptions: contractOptions,
      cell: (item) => item.contract_display_name,
    },
    {
      id: "sort_order",
      header: "Order",
      editType: "number",
      width: 80,
      cell: (item) => String(item.sort_order),
    },
    {
      id: "enabled",
      header: t("common.status"),
      editType: "toggle",
      width: 80,
      cell: (item) => item.enabled ? "Yes" : "No",
    },
  ];

  const handleSave = (items: ProcessRuleTemplate[]) => {
    return saveRules.mutateAsync(
      { items: items.map((item) => ({ ...item })) },
      {
        onSuccess: () => addToast("success", t("toast.save_success")),
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    ).then((response) => response.items);
  };

  return (
    <WorkspaceLoader loading={processRules.isLoading || contracts.isLoading} error={processRules.error ?? contracts.error} onRetry={() => { void Promise.all([processRules.refetch(), contracts.refetch()]); }}>
      <EditableTable
        items={processRules.data ?? []}
        columns={columns}
        header={t("advanced.process_rules")}
        loading={processRules.isLoading}
        saving={saveRules.isPending}
        onSave={handleSave}
        validateItems={(items) => {
          const error = validateProcessRules(items);
          return error ? t("validation.row", { row: error.row, field: error.field, reason: t(error.reason) }) : undefined;
        }}
        onAddRow={() =>
          ({
            id: `new-${Date.now()}`,
            match_type: "PROCESS-NAME",
            value: "",
            contract_id: "",
            contract_display_name: "",
            business_group: "",
            sort_order: (processRules.data?.length ?? 0) + 1,
            enabled: true,
            needs_rebind: false,
            migration_warning: "",
          }) as ProcessRuleTemplate
        }
      />
    </WorkspaceLoader>
  );
}
