import type { ReactNode } from "react";

// 等人处理的事是纸：一张轻的半透明纸条，放在它所属的那一项上，或页面最上方一次。
interface PaperNoteProps {
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function PaperNote({ children, action, className }: PaperNoteProps) {
  return (
    <div className={["s-paper", className ?? ""].filter(Boolean).join(" ")} role="note">
      <div className="s-paper-body">{children}</div>
      {action ? <div className="s-paper-action">{action}</div> : null}
    </div>
  );
}
