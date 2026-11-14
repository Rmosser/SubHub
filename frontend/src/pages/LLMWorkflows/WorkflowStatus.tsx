import { StatusBadge } from "@/components/StatusBadge";
import { ReasonText } from "@/components/ReasonText";

// 工作流当前所处的一步：一行状态，下面一行说明；失败原因可能很长，限高可展开。
export type WorkflowStatusVariant = "info" | "success" | "warning" | "error";

export function WorkflowStatus({ variant, title, body }: { variant: WorkflowStatusVariant; title: string; body?: string }) {
  return (
    <div className="s-status-line" role="status">
      <StatusBadge status={variant}>{title}</StatusBadge>
      {body ? (variant === "error" ? <ReasonText text={body} /> : <span className="s-muted">{body}</span>) : null}
    </div>
  );
}
