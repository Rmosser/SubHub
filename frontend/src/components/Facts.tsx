import type { ReactNode } from "react";

// 一排键值事实：标签是面板上的弱文字，值用等宽数字。
export interface Fact {
  label: string;
  value: ReactNode;
}

export function Facts({ items, compact }: { items: Fact[]; compact?: boolean }) {
  return (
    <dl className={`s-facts${compact ? " compact" : ""}`}>
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
