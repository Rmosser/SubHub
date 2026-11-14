import { Button } from "@cloudscape-design/components";
import { t } from "@/i18n/translations";
import { GlassDialog } from "./GlassDialog";
import { LinkAction } from "./InlineAction";
import { Facts } from "./Facts";

interface ConfirmModalDetail {
  label: string;
  value: React.ReactNode;
}

interface ConfirmModalProps {
  visible: boolean;
  header?: string;
  children: React.ReactNode;
  description?: React.ReactNode;
  details?: ConfirmModalDetail[];
  consequences?: React.ReactNode[];
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "primary" | "normal";
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  visible,
  header,
  children,
  description,
  details,
  consequences,
  confirmLabel,
  cancelLabel,
  variant = "primary",
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  return (
    <GlassDialog
      visible={visible}
      header={header || t("confirm.title")}
      onDismiss={onCancel}
      actions={
        <>
          <LinkAction onClick={onCancel}>
            {cancelLabel || t("confirm.cancel")}
          </LinkAction>
          <Button variant={variant} onClick={onConfirm} disabled={confirmDisabled}>
            {confirmLabel || t("confirm.delete")}
          </Button>
        </>
      }
    >
      {description ? <p className="s-dialog-lead">{description}</p> : null}
      {children}
      {details?.length ? <Facts compact items={details} /> : null}
      {consequences?.length ? (
        <ul className="s-dialog-list" aria-label={t("confirm.impact_title")}>
          {consequences.map((consequence, index) => (
            <li key={index}>{consequence}</li>
          ))}
        </ul>
      ) : null}
    </GlassDialog>
  );
}
