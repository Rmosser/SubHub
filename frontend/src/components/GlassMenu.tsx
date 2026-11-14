/* A small menu on the glass: an etched icon button that opens a frosted list.
   Items can be marked danger (red text), separated by a rule, or shown only on narrow screens. */
import { useCallback, useEffect, useId, useRef, useState } from "react";

export interface GlassMenuItem {
  id: string;
  text: string;
  danger?: boolean;
  /** Only on narrow screens, where the row's own button for it is hidden. */
  narrowOnly?: boolean;
}

export type GlassMenuEntry = GlassMenuItem | "separator";

interface Props {
  ariaLabel: string;
  items: GlassMenuEntry[];
  onItem(id: string): void;
  /** "row": a 32px button for list rows; default is the compact rail button. */
  size?: "compact" | "row";
}

// Items hidden by CSS (narrow-only on a wide screen) are skipped by the arrow keys.
function visibleItems(root: HTMLElement | null) {
  return [...(root?.querySelectorAll<HTMLButtonElement>("[role=menuitem]") ?? [])].filter((item) => item.offsetParent !== null);
}

export function GlassMenu({ ariaLabel, items, onItem, size = "compact" }: Props) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) button.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    visibleItems(wrap.current)[0]?.focus();
    const onDown = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) close(false); };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open, close]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape" && open) { e.preventDefault(); e.stopPropagation(); close(true); return; }
    if (!open) return;
    const list = visibleItems(wrap.current);
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    let next = -1;
    if (e.key === "ArrowDown") next = (at + 1) % list.length;
    else if (e.key === "ArrowUp") next = (at + list.length - 1) % list.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = list.length - 1;
    if (next < 0) return;
    e.preventDefault();
    list[next]?.focus();
  };

  return (
    // The focus leaving the menu (Tab out, a click elsewhere) closes it.
    <span className={`glass-menu${size === "row" ? " row" : ""}`} ref={wrap} onKeyDown={onKey}
      onBlur={(e) => { if (open && !wrap.current?.contains(e.relatedTarget as Node | null)) setOpen(false); }}>
      <button ref={button} type="button" className="glass-menu-button" aria-label={ariaLabel} aria-haspopup="menu"
        aria-expanded={open} aria-controls={open ? menuId : undefined} onClick={() => setOpen((v) => !v)}>
        {size === "row"
          ? <svg viewBox="0 0 16 16" aria-hidden="true"><g fill="currentColor"><circle cx="3.5" cy="8" r="1.25" /><circle cx="8" cy="8" r="1.25" /><circle cx="12.5" cy="8" r="1.25" /></g></svg>
          : <svg viewBox="0 0 16 4" aria-hidden="true"><g fill="currentColor"><circle cx="2" cy="2" r="1.6" /><circle cx="8" cy="2" r="1.6" /><circle cx="14" cy="2" r="1.6" /></g></svg>}
      </button>
      {open ? (
        <span className="glass-menu-list" role="menu" id={menuId} aria-label={ariaLabel} tabIndex={-1}>
          {items.map((it, index) => it === "separator"
            ? <span key={`sep-${index}`} className="glass-menu-sep" role="separator" />
            : (
              <button key={it.id} type="button" role="menuitem"
                className={[it.danger ? "danger" : "", it.narrowOnly ? "narrow-only" : ""].filter(Boolean).join(" ") || undefined}
                onClick={() => { close(true); onItem(it.id); }}>{it.text}</button>
            ))}
        </span>
      ) : null}
    </span>
  );
}
