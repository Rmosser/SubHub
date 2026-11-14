import type { ReactNode } from "react";

// 页标题刻在玻璃上：标题、可选的一行短用途、本页唯一的主操作。
interface PageHeaderProps {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <header className="s-page-head">
      <div>
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actions ? <div className="s-page-actions">{actions}</div> : null}
    </header>
  );
}
