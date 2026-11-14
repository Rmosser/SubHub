import { useState } from "react";
import {
  Table,
  Button,
  SpaceBetween,
  Box,
  Input,
  FormField,
  Select,
  SelectProps,
} from "@cloudscape-design/components";
import { FormModal } from "@/components/FormModal";
import { Chip } from "@/components/Chip";
import { ConfirmModal } from "@/components/ConfirmModal";
import { IconAction } from "@/components/InlineAction";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { usePins } from "@/api/queries";
import {
  useCreatePinGroup,
  usePinCategory,
  useRenamePinGroup,
  useDeletePinGroup,
  useUnpinCategory,
} from "@/api/mutations";
import type { BusinessGroup, RuleCategory, ServiceCatalogEntry } from "@/types";
import { buildCatalogTableRows, buildVisibleCatalogGroupNames } from "./catalogView";

interface PinManagementModalProps {
  visible: boolean;
  categories: RuleCategory[];
  catalogEntries: ServiceCatalogEntry[];
  onClose: () => void;
}

export function PinManagementModal({ visible, categories, catalogEntries, onClose }: PinManagementModalProps) {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const pins = usePins();
  const createGroup = useCreatePinGroup();
  const pinCategory = usePinCategory();
  const renameGroup = useRenamePinGroup();
  const deleteGroup = useDeletePinGroup();
  const unpinCategory = useUnpinCategory();

  const [searchText, setSearchText] = useState("");
  const [newName, setNewName] = useState("");
  const [renameTarget, setRenameTarget] = useState<BusinessGroup | null>(null);
  const [renameTo, setRenameTo] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<BusinessGroup | null>(null);

  const pinGroups = pins.data?.groups ?? [];
  const rows = buildCatalogTableRows(categories, catalogEntries, pinGroups);
  const normalizedSearchText = searchText.trim().toLowerCase();
  const filteredRows = rows.filter((row) => {
    if (!normalizedSearchText) {
      return true;
    }

    return [row.name, row.pinGroup]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(normalizedSearchText);
  });
  const pinGroupOptions: SelectProps.Option[] = buildVisibleCatalogGroupNames(pinGroups, catalogEntries).map((groupName) => ({
    value: groupName,
    label: groupName,
  }));

  const handleCreate = () => {
    if (!newName.trim()) return;
    createGroup.mutate(
      { group_name: newName.trim() },
      {
        onSuccess: () => {
          addToast("success", t("toast.create_success"));
          setNewName("");
        },
        onError: (err) => addToast("error", t("toast.create_error"), err.message),
      },
    );
  };

  const handleClose = () => {
    setSearchText("");
    setNewName("");
    setRenameTarget(null);
    setRenameTo("");
    setDeleteTarget(null);
    onClose();
  };

  const handlePin = (name: string, pinGroup: string) => {
    if (!pinGroup) return;
    const targetSortOrder = rows
      .filter((row) => row.name !== name && row.pinGroup === pinGroup)
      .reduce((maxOrder, row) => Math.max(maxOrder, row.pinSortOrder), -1) + 1;
    pinCategory.mutate(
      { name, pin_group: pinGroup, sort_order: targetSortOrder },
      {
        onSuccess: () => addToast("success", t("toast.update_success")),
        onError: (err) => addToast("error", t("toast.update_error"), err.message),
      },
    );
  };

  const handleRename = () => {
    if (!renameTarget || !renameTo.trim()) return;
    renameGroup.mutate(
      { name: renameTarget.name, new_name: renameTo.trim() },
      {
        onSuccess: () => {
          addToast("success", t("toast.update_success"));
          setRenameTarget(null);
        },
        onError: (err) => addToast("error", t("toast.update_error"), err.message),
      },
    );
  };

  const handleUnpin = (name: string) => {
    unpinCategory.mutate(name, {
      onSuccess: () => addToast("success", t("toast.delete_success")),
      onError: (err) => addToast("error", t("toast.delete_error"), err.message),
    });
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteGroup.mutate(deleteTarget.name, {
      onSuccess: () => {
        addToast("success", t("toast.delete_success"));
        setDeleteTarget(null);
      },
      onError: (err) => addToast("error", t("toast.delete_error"), err.message),
    });
  };

  return (
    <>
      <FormModal
        visible={visible}
        header={t("catalog.pin_management")}
        confirmLabel={t("common.close")}
        hideCancel
        size="large"
        onSubmit={handleClose}
        onCancel={handleClose}
      >
        <SpaceBetween size="m">
          <FormField label={t("common.search")}>
            <Input
              value={searchText}
              onChange={({ detail }) => setSearchText(detail.value)}
              placeholder={t("catalog.pin_search_placeholder")}
            />
          </FormField>

          <Table
            variant="embedded"
            items={filteredRows}
            loading={pins.isLoading}
            columnDefinitions={[
              {
                id: "name",
                header: t("common.name"),
                cell: (item) => item.name,
              },
              {
                id: "pin_group",
                header: t("catalog.current_pin_group"),
                cell: (item) => item.pinGroup || "-",
              },
              {
                id: "assign_to",
                header: t("catalog.assign_pin_group"),
                cell: (item) => (
                  <Select
                    selectedOption={pinGroupOptions.find((option) => option.value === item.pinGroup) || null}
                    options={pinGroupOptions}
                    filteringType="auto"
                    filteringPlaceholder={t("catalog.group_select_search_placeholder")}
                    expandToViewport
                    statusType={pins.isLoading ? "loading" : "finished"}
                    placeholder={t("catalog.select_pin_group_placeholder")}
                    disabled={pins.isLoading || pinCategory.isPending || unpinCategory.isPending || pinGroups.length === 0}
                    onChange={({ detail }) => {
                      const nextGroup = detail.selectedOption.value ?? "";
                      if (nextGroup && nextGroup !== item.pinGroup) {
                        handlePin(item.name, nextGroup);
                      }
                    }}
                  />
                ),
              },
              {
                id: "actions",
                header: t("common.actions"),
                cell: (item) => (
                  <Button
                    disabled={!item.pinGroup || pinCategory.isPending || unpinCategory.isPending}
                    onClick={() => handleUnpin(item.name)}
                  >
                    {t("catalog.unpin")}
                  </Button>
                ),
              },
            ]}
            empty={<div className="s-empty">{t("common.no_items")}</div>}
          />

          <hr className="s-rule" />
          <Box variant="h3">{t("catalog.pin_group_management_section")}</Box>

          <div className="s-row">
            <div className="s-grow">
              <FormField label={t("catalog.add_pin_group")}>
                <Input
                  value={newName}
                  onChange={({ detail }) => setNewName(detail.value)}
                  placeholder={t("catalog.pin_group_name_placeholder")}
                />
              </FormField>
            </div>
            <Button onClick={handleCreate} loading={createGroup.isPending}>
              {t("common.add")}
            </Button>
          </div>

          <Table
            variant="embedded"
            items={pinGroups}
            loading={pins.isLoading}
            columnDefinitions={[
              {
                id: "name",
                header: t("common.name"),
                cell: (item) => (
                  <div className="s-chips">
                    <span>{item.name}</span>
                    <Chip mono dot={item.mode === "ad_block" ? "warm" : undefined} muted={item.mode !== "ad_block"}>{item.mode}</Chip>
                  </div>
                ),
              },
              {
                id: "categories",
                header: t("catalog.categories_count"),
                cell: (item) => item.category_names?.length ?? 0,
              },
              {
                id: "actions",
                header: t("common.actions"),
                cell: (item) => (
                  <SpaceBetween direction="horizontal" size="xs">
                    <IconAction
                      iconName="edit"
                      ariaLabel={`${t("common.edit")} ${item.name}`}
                      onClick={() => {
                        setRenameTarget(item);
                        setRenameTo(item.name);
                      }}
                    />
                    <IconAction
                      iconName="remove"
                      ariaLabel={`${t("common.delete")} ${item.name}`}
                      onClick={() => setDeleteTarget(item)}
                    />
                  </SpaceBetween>
                ),
              },
            ]}
            empty={<div className="s-empty">{t("common.no_items")}</div>}
          />
        </SpaceBetween>
      </FormModal>

      <FormModal
        visible={!!renameTarget}
        header={t("catalog.rename_group")}
        confirmLabel={t("common.save")}
        loading={renameGroup.isPending}
        onSubmit={handleRename}
        onCancel={() => setRenameTarget(null)}
      >
        <FormField label={t("common.name")}>
          <Input value={renameTo} onChange={({ detail }) => setRenameTo(detail.value)} />
        </FormField>
      </FormModal>

      <ConfirmModal visible={!!deleteTarget} onConfirm={handleDelete} onCancel={() => setDeleteTarget(null)}>
        {deleteTarget?.name}
      </ConfirmModal>
    </>
  );
}
