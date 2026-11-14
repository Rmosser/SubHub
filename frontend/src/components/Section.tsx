import type { ReactNode } from "react";

// 分组：标题行刻在玻璃上（标题、计数、动作），下面接它的面板或表格。
interface SectionProps {
  title?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  id?: string;
  ariaLabel?: string;
}

export function Section({ title, meta, actions, children, id, ariaLabel }: SectionProps) {
  const hasHead = Boolean(title || meta || actions);
  return (
    <section className="s-section" id={id} aria-label={ariaLabel}>
      {hasHead ? (
        <div className="s-section-head">
          {title ? <h2>{title}</h2> : null}
          {meta ? <div className="s-section-meta">{meta}</div> : null}
          <span className="s-section-fill" />
          {actions ? <div className="s-section-actions">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Surface({ children, flush, className }: { children: ReactNode; flush?: boolean; className?: string }) {
  return <div className={["s-surface", flush ? "flush" : "", className ?? ""].filter(Boolean).join(" ")}>{children}</div>;
}
