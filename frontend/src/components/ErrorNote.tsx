import Button from "@cloudscape-design/components/button";
import { StatusBadge } from "@/components/StatusBadge";
import { ReasonText } from "@/components/ReasonText";
import { t } from "@/i18n/translations";

// 错误：一行状态、所属的原因、旁边的重试。整页失败也用它，不用大红框。
interface ErrorNoteProps {
  title: string;
  reason?: string;
  onRetry?: () => void;
  retrying?: boolean;
  retryLabel?: string;
  page?: boolean;
}

export function ErrorNote({ title, reason, onRetry, retrying, retryLabel, page }: ErrorNoteProps) {
  return (
    <div className={`s-error${page ? " page" : ""}`} role="alert">
      <StatusBadge status="error">{title}</StatusBadge>
      {reason ? <ReasonText text={reason} lines={3} /> : null}
      {onRetry ? <Button onClick={onRetry} loading={retrying}>{retryLabel || t("workspace.retry")}</Button> : null}
    </div>
  );
}
