/* Which lines of an open section are drawn. Pure, so node can test it. */

/** Lines in view with `pad` either side, plus the roving tab stop wherever it is: the section keeps
    its one way in from the keyboard even when that line has scrolled far out of the window. In order. */
export function drawnLines(start: number, end: number, top: number, h: number, lineH: number, pad: number, stop: number | null): number[] {
  const first = Math.max(start, start + Math.floor(top / lineH) - pad);
  const last = Math.min(end, start + Math.ceil((top + h) / lineH) + pad);
  const out: number[] = [];
  if (stop != null && stop >= start && stop < first) out.push(stop);
  for (let i = first; i < last; i++) out.push(i);
  if (stop != null && stop >= last && stop < end) out.push(stop);
  return out;
}
