import { useState } from "react";
import {
  Table,
  Select,
  FormField,
  Input,
  SelectProps,
} from "@cloudscape-design/components";
import { FormModal } from "@/components/FormModal";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useBusinessGroups } from "@/api/queries";
import { useBulkAssignCatalogGroups } from "@/api/mutations";
import type { RuleCategory, ServiceCatalogEntry } from "@/types";
import { buildVisibleCatalogGroupNames } from "./catalogView";

interface BulkAssignModalProps {
  visible: boolean;
  categories: RuleCategory[];
  catalogEntries: ServiceCatalogEntry[];
  onClose: () => void;
}

export function BulkAssignModal({ visible, categories, catalogEntries, onClose }: BulkAssignModalProps) {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const groups = useBusinessGroups();
  const bulkAssign = useBulkAssignCatalogGroups();

  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [searchText, setSearchText] = useState("");

  const groupOptions: SelectProps.Option[] = [
    { value: "", label: "-" },
    ...buildVisibleCatalogGroupNames(groups.data ?? [], catalogEntries)
      .map((groupName) => ({ value: groupName, label: groupName })),
  ];
  const currentCatalogGroupByName = new Map(
    catalogEntries.map((entry) => [entry.category_name, String(entry.catalog_group || "").trim()]),
  );
  const rows = categories.map((category) => ({
    name: category.name,
    currentGroup: currentCatalogGroupByName.get(category.name) ?? "",
  }));
  const normalizedSearchText = searchText.trim().toLowerCase();
  const filteredRows = rows.filter((row) => {
    if (!normalizedSearchText) {
      return true;
    }

    const pendingGroup = String(assignments[row.name] ?? "").trim();

    return [row.name, row.currentGroup, pendingGroup]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(normalizedSearchText);
  });

  const handleAssign = (name: string, group: string, currentGroup: string) => {
    setAssignments((prev) => {
      if (group === currentGroup) {
        const next = { ...prev };
        delete next[name];
        return next;
      }
      return { ...prev, [name]: group };
    });
  };

  const handleClose = () => {
    setAssignments({});
    setSearchText("");
    onClose();
  };

  const handleSubmit = () => {
    if (Object.keys(assignments).length === 0) {
      handleClose();
      return;
    }
    bulkAssign.mutate(
      { assignments },
      {
        onSuccess: () => {
          addToast("success", t("toast.update_success"));
          handleClose();
        },
        onError: (err) => addToast("error", t("toast.update_error"), err.message),
      },
    );
  };

  return (
    <FormModal
      visible={visible}
      header={t("catalog.bulk_assign")}
      confirmLabel={t("common.save")}
      loading={bulkAssign.isPending}
      onSubmit={handleSubmit}
      onCancel={handleClose}
      size="large"
    >
      <FormField label={t("common.search")}>
        <Input
          value={searchText}
          onChange={({ detail }) => setSearchText(detail.value)}
          placeholder={t("catalog.bulk_assign_search_placeholder")}
        />
      </FormField>

      <Table
        variant="embedded"
        items={filteredRows}
        columnDefinitions={[
          {
            id: "name",
            header: t("common.name"),
            cell: (item) => item.name,
          },
          {
            id: "current",
            header: t("catalog.current_group"),
            cell: (item) => item.currentGroup || "-",
          },
          {
            id: "assign",
            header: t("catalog.assign_to_group"),
            cell: (item) => (
              <Select
                selectedOption={
                  Object.prototype.hasOwnProperty.call(assignments, item.name)
                    ? (groupOptions.find((option) => option.value === assignments[item.name]) ?? groupOptions[0])
                    : null
                }
                options={groupOptions}
                placeholder={t("catalog.select_group_placeholder")}
                filteringType="auto"
                filteringPlaceholder={t("catalog.group_select_search_placeholder")}
                expandToViewport
                statusType={groups.isLoading ? "loading" : "finished"}
                disabled={groups.isLoading}
                onChange={({ detail }) => handleAssign(item.name, detail.selectedOption.value ?? "", item.currentGroup)}
              />
            ),
          },
        ]}
        empty={<div className="s-empty">{t("common.no_items")}</div>}
      />
    </FormModal>
  );
}
