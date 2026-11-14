import { useState, useEffect } from "react";
import { FormField, Input, SpaceBetween } from "@cloudscape-design/components";
import { FormModal } from "@/components/FormModal";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useCreateManualCategory, useRenameCategory } from "@/api/mutations";

interface ManualCategoryModalProps {
  visible: boolean;
  editName?: string | null;
  onClose: () => void;
}

export function ManualCategoryModal({ visible, editName, onClose }: ManualCategoryModalProps) {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const createCategory = useCreateManualCategory();
  const renameCategory = useRenameCategory();

  const isEdit = !!editName;
  const [name, setName] = useState("");

  useEffect(() => {
    if (editName) setName(editName);
    else setName("");
  }, [editName, visible]);

  const handleSubmit = () => {
    if (!name.trim()) return;
    if (isEdit) {
      renameCategory.mutate(
        { name: editName!, new_name: name.trim() },
        {
          onSuccess: () => {
            addToast("success", t("toast.update_success"));
            onClose();
          },
          onError: (err) => addToast("error", t("toast.update_error"), err.message),
        },
      );
    } else {
      createCategory.mutate(
        { name: name.trim() },
        {
          onSuccess: () => {
            addToast("success", t("toast.create_success"));
            onClose();
          },
          onError: (err) => addToast("error", t("toast.create_error"), err.message),
        },
      );
    }
  };

  return (
    <FormModal
      visible={visible}
      header={isEdit ? t("common.edit") : t("catalog.create_manual")}
      confirmLabel={t("common.save")}
      loading={createCategory.isPending || renameCategory.isPending}
      onSubmit={handleSubmit}
      onCancel={onClose}
    >
      <SpaceBetween size="l">
        <FormField label={t("common.name")}>
          <Input value={name} onChange={({ detail }) => setName(detail.value)} autoFocus />
        </FormField>
      </SpaceBetween>
    </FormModal>
  );
}
