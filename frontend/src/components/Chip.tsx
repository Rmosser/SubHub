import type { ReactNode } from "react";

// 中性分类标签：刻在面板上的细描边。动作类别需要区分时，最多带一个淡色点。
export type ChipDot = "flow" | "teal" | "warm" | "muted";

interface ChipProps {
  children: ReactNode;
  dot?: ChipDot;
  mono?: boolean;
  muted?: boolean;
  lit?: boolean;
  title?: string;
}

export function Chip({ children, dot, mono, muted, lit, title }: ChipProps) {
  const className = ["s-chip", mono ? "mono" : "", muted ? "muted" : "", lit ? "lit" : ""].filter(Boolean).join(" ");
  return (
    <span className={className} title={title}>
      {dot ? <i className={`s-chip-dot ${dot === "muted" ? "" : dot}`} aria-hidden="true" /> : null}
      <span>{children}</span>
    </span>
  );
}

export function ChipList({ children }: { children: ReactNode }) {
  return <span className="s-chips">{children}</span>;
}
