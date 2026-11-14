/* Tabs etched on the glass: the selected tab is lit, a count follows the label, an amber dot marks a tab that needs attention.
   Roving tabindex: arrows / Home / End move between tabs and select them. Only the selected panel is rendered.
   Pass activeId + onChange to control the selection; otherwise the tabs keep it themselves. */
import { useId, useRef, useState } from "react";

export interface GlassTab {
  id: string;
  label: string;
  count?: number;
  attention?: boolean;
  /** Spoken label when the tab carries an attention dot. */
  attentionLabel?: string;
  content: React.ReactNode;
}

interface Props {
  ariaLabel: string;
  tabs: GlassTab[];
  activeId?: string;
  onChange?(id: string): void;
}

export function GlassTabs({ ariaLabel, tabs, activeId, onChange }: Props) {
  const base = useId();
  const list = useRef<HTMLDivElement>(null);
  const [ownId, setOwnId] = useState(tabs[0]?.id);
  const currentId = activeId ?? ownId;
  const active = tabs.find((tab) => tab.id === currentId) ?? tabs[0];
  const select = (id: string) => {
    if (activeId === undefined) setOwnId(id);
    onChange?.(id);
  };

  const onKey = (event: React.KeyboardEvent) => {
    const at = tabs.findIndex((tab) => tab.id === active.id);
    let next = -1;
    if (event.key === "ArrowRight") next = (at + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (at + tabs.length - 1) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    if (next < 0) return;
    event.preventDefault();
    select(tabs[next].id);
    list.current?.querySelectorAll<HTMLButtonElement>("[role=tab]")[next]?.focus();
  };

  return (
    <>
      <div className="s-tabs" role="tablist" aria-label={ariaLabel} ref={list} onKeyDown={onKey}>
        {tabs.map((tab) => {
          const selected = tab.id === active.id;
          return (
            <button
              key={tab.id}
              id={`${base}-tab-${tab.id}`}
              type="button"
              role="tab"
              className="s-tab"
              aria-selected={selected}
              aria-controls={`${base}-panel-${tab.id}`}
              aria-label={tab.attention && tab.attentionLabel ? tab.attentionLabel : undefined}
              tabIndex={selected ? 0 : -1}
              onClick={() => select(tab.id)}
            >
              {tab.label}
              {typeof tab.count === "number" ? <span className="s-tab-count">{tab.count}</span> : null}
              {tab.attention ? <i className="s-dot amber" aria-hidden="true" /> : null}
            </button>
          );
        })}
      </div>
      <section className="s-tab-panel" role="tabpanel" id={`${base}-panel-${active.id}`} aria-labelledby={`${base}-tab-${active.id}`}>
        {active.content}
      </section>
    </>
  );
}
