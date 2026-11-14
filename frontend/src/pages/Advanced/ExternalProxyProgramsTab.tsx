import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useExternalProxyPrograms, useContracts } from "@/api/queries";
import { useSaveExternalProxyPrograms } from "@/api/mutations";
import { EditableTable, type EditableColumn } from "@/components/EditableTable";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";
import type { ExternalProxyProgramTemplate } from "@/types";
import { Textarea } from "@cloudscape-design/components";
import { validateExternalProxyPrograms } from "./formValidation";

export function ExternalProxyProgramsTab() {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const programs = useExternalProxyPrograms();
  const contracts = useContracts();
  const savePrograms = useSaveExternalProxyPrograms();

  const contractOptions = (contracts.data ?? [])
    .filter((c) => c.enabled)
    .map((c) => ({ value: c.id, label: c.display_name }));

  const columns: EditableColumn<ExternalProxyProgramTemplate>[] = [
    {
      id: "name",
      header: t("common.name"),
      editType: "text",
      cell: (item) => item.name,
    },
    {
      id: "program_path",
      header: t("advanced.program_path"),
      editType: "text",
      cell: (item) => item.program_path,
    },
    {
      id: "args",
      header: t("advanced.args"),
      cell: (item) => item.args.join("\n"),
      editCell: (item, _value, onChange, disabled) => (
        <Textarea
          value={item.args.join("\n")}
          rows={3}
          placeholder={t("advanced.args_help")}
          disabled={disabled}
          onChange={({ detail }) => onChange(detail.value.split("\n"))}
        />
      ),
    },
    {
      id: "local_port",
      header: t("advanced.local_port"),
      editType: "number",
      width: 100,
      cell: (item) => String(item.local_port),
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

  const handleSave = (items: ExternalProxyProgramTemplate[]) => {
    return savePrograms.mutateAsync(
      { items: items.map((item) => ({ ...item })) },
      {
        onSuccess: () => addToast("success", t("toast.save_success")),
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    ).then((response) => response.items);
  };

  return (
    <WorkspaceLoader loading={programs.isLoading || contracts.isLoading} error={programs.error ?? contracts.error} onRetry={() => { void Promise.all([programs.refetch(), contracts.refetch()]); }}>
      <EditableTable
        items={programs.data ?? []}
        columns={columns}
        header={t("advanced.external_proxy")}
        loading={programs.isLoading}
        saving={savePrograms.isPending}
        onSave={handleSave}
        validateItems={(items) => {
          const error = validateExternalProxyPrograms(items);
          return error ? t("validation.row", { row: error.row, field: error.field, reason: t(error.reason) }) : undefined;
        }}
        onAddRow={() =>
          ({
            id: `new-${Date.now()}`,
            name: "",
            program_path: "",
            args: [],
            local_port: 0,
            contract_id: "",
            contract_display_name: "",
            business_group: "",
            sort_order: (programs.data?.length ?? 0) + 1,
            enabled: true,
            needs_rebind: false,
            migration_warning: "",
          }) as ExternalProxyProgramTemplate
        }
      />
    </WorkspaceLoader>
  );
}
