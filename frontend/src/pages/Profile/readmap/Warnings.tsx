/* The render's notes: an etched count of kinds in the bar, a glass popover with one line per kind. */
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { placePop } from "./popPlace";
import { groupWarnings, type Warning } from "./warningGroups";

/** Details shown per kind before "and N more". */
const SHOWN = 40;

export function WarningsChip({ list }: { list: readonly Warning[] }) {
  const groups = useMemo(() => groupWarnings(list), [list]);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const wrap = useRef<HTMLSpanElement>(null);
  const chip = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const id = useId();

  // The bar wraps on narrow windows and can leave the chip anywhere along a line, so the popover is placed
  // from where the chip is before it paints, and again whenever the window changes size.
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const w = wrap.current, c = chip.current, p = pop.current;
      if (!w || !c || !p) return;
      const at = c.getBoundingClientRect();
      const { left, width } = placePop(at.left, at.right, document.documentElement.clientWidth);
      p.style.left = `${left - w.getBoundingClientRect().left}px`;
      p.style.width = `${width}px`;
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    // Focus goes into the popover (its first kind that opens, else the popover itself); Escape or a press
    // outside closes it and gives the focus back.
    (pop.current?.querySelector<HTMLElement>("button") ?? pop.current)?.focus({ preventScroll: true });
    const onDown = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      e.preventDefault();
      setOpen(false);
      chip.current?.focus({ preventScroll: true });
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("pointerdown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  if (!groups.length) return null;
  const total = groups.reduce((n, g) => n + g.count, 0);
  return (
    <span className="rm-warn-wrap" ref={wrap}
      onBlur={(e) => { if (open && !wrap.current?.contains(e.relatedTarget as Node | null)) setOpen(false); }}>
      {/* The chip is the only way in, so every opening starts folded. */}
      <button type="button" ref={chip} className="rm-warn" aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? id : undefined}
        aria-label={`${groups.length} 类提示，共 ${total} 条`} onClick={() => { setExpanded(null); setOpen((v) => !v); }}>
        {groups.length} 类提示
      </button>
      {open ? (
        <div className="rm-warn-pop" id={id} ref={pop} role="dialog" aria-label="生成提示" tabIndex={-1}>
          {groups.map((g) => {
            const on = expanded === g.key;
            const more = g.lead || g.items.length;
            const label = (
              <>
                <span className="t">{g.title}</span>
                {g.count > 1 ? <span className="n">{g.count}</span> : null}
              </>
            );
            return (
              <div key={g.key} className={`rm-wg ${g.tone}${on ? " on" : ""}`}>
                {/* A kind with nothing underneath is a plain line, not a control. */}
                {more ? (
                  <button type="button" className="rm-wg-head" aria-expanded={on} onClick={() => setExpanded(on ? null : g.key)}>{label}</button>
                ) : (
                  <div className="rm-wg-head">{label}</div>
                )}
                {on ? (
                  <div className="rm-wg-body">
                    {g.lead ? <p className="lead">{g.lead}</p> : null}
                    {g.items.length ? (
                      <ul>
                        {g.items.slice(0, SHOWN).map((t, i) => <li key={i}>{t}</li>)}
                        {g.items.length > SHOWN ? <li className="more">还有 {g.items.length - SHOWN} 条</li> : null}
                      </ul>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}
    </span>
  );
}
