import { Box, Button, Spinner } from "@cloudscape-design/components";
import type { ModalProps } from "@cloudscape-design/components/modal";
import { t } from "@/i18n/translations";
import { GlassDialog } from "./GlassDialog";
import { LinkAction } from "./InlineAction";
import { ErrorNote } from "./ErrorNote";

interface FormModalProps {
  visible: boolean;
  header: string;
  children: React.ReactNode;
  loading?: boolean;
  errorText?: string;
  confirmLabel?: string;
  confirmDisabled?: boolean;
  cancelLabel?: string;
  /** 只有一个“完成”动作的管理型对话框不再重复一个同义的“取消”。 */
  hideCancel?: boolean;
  size?: ModalProps.Size;
  onSubmit: () => void;
  onCancel: () => void;
}

export function FormModal({
  visible,
  header,
  children,
  loading = false,
  errorText,
  confirmLabel,
  confirmDisabled = false,
  cancelLabel,
  hideCancel = false,
  size,
  onSubmit,
  onCancel,
}: FormModalProps) {
  return (
    <GlassDialog
      visible={visible}
      header={header}
      size={size}
      onDismiss={onCancel}
      actions={
        <>
          {hideCancel ? null : (
            <LinkAction onClick={onCancel} disabled={loading}>
              {cancelLabel || t("confirm.cancel")}
            </LinkAction>
          )}
          <Button variant="primary" onClick={onSubmit} loading={loading} disabled={confirmDisabled}>
            {confirmLabel || t("confirm.delete")}
          </Button>
        </>
      }
    >
      {loading && !children ? (
        <Box textAlign="center" padding="l">
          <Spinner />
        </Box>
      ) : (
        children
      )}
      {errorText ? <ErrorNote title={t("toast.save_error")} reason={errorText} /> : null}
    </GlassDialog>
  );
}
