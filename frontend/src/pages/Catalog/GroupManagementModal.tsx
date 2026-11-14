import { useState } from "react";
import {
  Table,
  Button,
  SpaceBetween,
  Input,
  FormField,
} from "@cloudscape-design/components";
import { FormModal } from "@/components/FormModal";
import { ConfirmModal } from "@/components/ConfirmModal";
import { IconAction } from "@/components/InlineAction";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useBusinessGroups } from "@/api/queries";
import {
  useCreateBusinessGroup,
  useRenameBusinessGroup,
  useDeleteBusinessGroup,
} from "@/api/mutations";
import type { BusinessGroup } from "@/types";

interface GroupManagementModalProps {
  visible: boolean;
  onClose: () => void;
}

export function GroupManagementModal({ visible, onClose }: GroupManagementModalProps) {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const groups = useBusinessGroups();
  const createGroup = useCreateBusinessGroup();
  const renameGroup = useRenameBusinessGroup();
  const deleteGroup = useDeleteBusinessGroup();

  const [newName, setNewName] = useState("");
  const [renameTarget, setRenameTarget] = useState<BusinessGroup | null>(null);
  const [renameTo, setRenameTo] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<BusinessGroup | null>(null);

  const handleCreate = () => {
    if (!newName.trim()) return;
    createGroup.mutate(
      { name: newName.trim() },
      {
        onSuccess: () => {
          addToast("success", t("toast.create_success"));
          setNewName("");
        },
        onError: (err) => addToast("error", t("toast.create_error"), err.message),
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
        header={t("catalog.group_management")}
        confirmLabel={t("common.close")}
        hideCancel
        size="large"
        onSubmit={onClose}
        onCancel={onClose}
      >
        <SpaceBetween size="m">
          <div className="s-row">
            <div className="s-grow">
              <FormField label={t("catalog.add_group")}>
                <Input value={newName} onChange={({ detail }) => setNewName(detail.value)} placeholder={t("catalog.group_name_placeholder")} />
              </FormField>
            </div>
            <Button onClick={handleCreate} loading={createGroup.isPending}>
              {t("common.add")}
            </Button>
          </div>

          <Table
            variant="embedded"
            items={groups.data ?? []}
            loading={groups.isLoading}
            columnDefinitions={[
              { id: "name", header: t("common.name"), cell: (item) => item.name },
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
