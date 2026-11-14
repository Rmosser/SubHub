import { Fragment, memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReadMap, SectionView } from "./model";
import { MASK, secretSpans } from "./mask";
import { drawnLines } from "./lineWindow";

export const LINE_H = 20;
/** Fold / unfold of the sheet. */
export const FOLD_MS = 380;
const COMMENT = /^\s*(#|;|\/\/)/;

export interface Explain {
  text: string;
  paper?: boolean;
  links?: { text: string; screen: string; row: string }[];
  /** The row has no line in the 原文: the note pins to the top of the column. */
  pinned?: boolean;
  /** A row SubHub leaves alone: the note reads as the phone's own, not as something written. */
  quiet?: boolean;
}

function Note({ explain, className, style, onPaper, noteRef }: {
  explain: Explain; className: string; style?: React.CSSProperties; onPaper(screen: string, row: string): void;
  noteRef?: React.Ref<HTMLDivElement>;
}) {
  const cls = ["rm-explain", className, explain.paper ? "paper" : "", explain.quiet ? "quiet" : ""].filter(Boolean).join(" ");
  return (
    <div ref={noteRef} className={cls} style={style} role="note">
      {explain.text}
      {explain.links?.map((l) => (
        <span key={l.row} className="pl" role="link" tabIndex={0} onClick={() => onPaper(l.screen, l.row)}
          onKeyDown={(e) => { if (e.key === "Enter") onPaper(l.screen, l.row); }}>{l.text}</span>
      ))}
    </div>
  );
}

interface Props {
  rm: ReadMap;
  open: number | null;
  litLines: Set<number>;
  litBlocks: Set<number>;
  focusLine: number | null;
  explain: Explain | null;
  onToggle(index: number): void;
  onLine(line: number): void;
  onPaper(screen: string, row: string): void;
  onScroll(): void;
}

/** One config line with secrets masked; each secret reveals on its own.
    Inside a line that is itself a control (`plain`), a mask is a mark the line's own click reads (see
    `maskAt`), never a control nested in a control; the keyboard reaches it through `RevealLine`. */
const Masked = memo(function Masked({ text, line, revealed, onReveal, plain }: {
  text: string; line: number; revealed: Set<string>; onReveal(k: string): void; plain?: boolean;
}) {
  const spans = useMemo(() => secretSpans(text), [text]);
  if (!spans.length) return <>{text}</>;
  const out: React.ReactNode[] = [];
  let at = 0;
  spans.forEach((s, i) => {
    if (s.from > at) out.push(text.slice(at, s.from));
    const k = maskKey(line, s.from);
    const shown = revealed.has(k);
    const value = shown ? text.slice(s.from, s.to) : MASK;
    out.push(plain ? (
      <span key={k} className={`rm-mask${shown ? " shown" : ""}`} data-k={k}>{value}</span>
    ) : (
      <button key={k} type="button" className={`rm-mask${shown ? " shown" : ""}`} aria-label={shown ? undefined : "显示"}
        onClick={(e) => { e.stopPropagation(); onReveal(k); }}>
        {value}
      </button>
    ));
    at = s.to;
    if (i === spans.length - 1 && at < text.length) out.push(text.slice(at));
  });
  return <>{out}</>;
});

const maskKey = (line: number, from: number) => `${line}:${from}`;
const lineKeys = (text: string, line: number) => secretSpans(text).map((s) => maskKey(line, s.from));

/** The mask a click inside a line landed on, if any. */
function maskAt(e: React.MouseEvent): string | null {
  return (e.target as HTMLElement).closest<HTMLElement>(".rm-mask[data-k]")?.dataset.k ?? null;
}

/** The keyboard's way to a line's masks when the line itself is a control: a sibling button, shown on focus. */
function RevealLine({ text, line, revealed, onToggle, top, tabIndex }: {
  text: string; line: number; revealed: Set<string>; onToggle(keys: string[]): void; top?: number; tabIndex: number;
}) {
  const keys = lineKeys(text, line);
  if (!keys.length) return null;
  const shown = keys.every((k) => revealed.has(k));
  return (
    <button type="button" className="rm-reveal" style={top != null ? { top } : undefined} tabIndex={tabIndex}
      aria-label={`${shown ? "隐藏密文" : "显示密文"}，第 ${line + 1} 行`} onClick={() => onToggle(keys)}>
      {shown ? "隐藏密文" : "显示密文"}
    </button>
  );
}

/** A line as a screen reader hears it: secrets stay masked. */
function spoken(text: string): string {
  let out = "", at = 0;
  for (const s of secretSpans(text)) { out += text.slice(at, s.from) + MASK; at = s.to; }
  return (out + text.slice(at)).trim();
}

/** Leading one-line blocks that are only comments (the file header): they fold into one headless block. */
function headerRun(rm: ReadMap): number {
  let n = 0;
  while (n < rm.sections.length) {
    const b = rm.sections[n].block;
    if (!b.line || b.key || !COMMENT.test(rm.doc.lines[b.header] ?? "")) break;
    n++;
  }
  return n > 1 ? n : 0;
}

const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function ReadingColumn(props: Props) {
  const { rm, litLines, litBlocks, focusLine, explain, onToggle, onLine, onPaper, onScroll } = props;
  // An index from another map is never drawn (the page resets it in the same render; this is the last guard).
  const open = props.open != null && props.open >= 0 && props.open < rm.sections.length ? props.open : null;
  const [revealed, setRevealed] = useState<Set<string>>(new Set());
  const sheetRef = useRef<HTMLElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ top: 0, h: 600 });
  const noteRef = useRef<HTMLDivElement>(null);
  const aboveRef = useRef<HTMLDivElement>(null);
  const [noteH, setNoteH] = useState(0);
  const pre = useMemo(() => headerRun(rm), [rm]);
  const [preOpen, setPreOpen] = useState(false);
  /** The mapped line that holds the section's single tab stop (roving tabindex). */
  const [cursor, setCursor] = useState<number | null>(null);
  const focusCursor = useRef(false);
  /** A head toggled from the keyboard moves in the DOM (into or out of the open part): its focus follows it. */
  const refocusHead = useRef<number | null>(null);

  // When the folded heads above overflow, keep the ones nearest the open section in view.
  useLayoutEffect(() => {
    const el = aboveRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [open, rm]);

  // Masks come back when the section folds or the config changes; so does the folded file header.
  useEffect(() => setRevealed(new Set()), [open, rm]);
  useEffect(() => { setPreOpen(false); }, [rm]);
  const reveal = useCallback((k: string) => setRevealed((s) => {
    const n = new Set(s);
    if (n.has(k)) n.delete(k); else n.add(k);
    return n;
  }), []);
  /** A whole line's masks at once: all shown goes back to all hidden. */
  const revealAll = useCallback((keys: string[]) => setRevealed((s) => {
    const n = new Set(s);
    const on = keys.every((k) => n.has(k));
    keys.forEach((k) => { if (on) n.delete(k); else n.add(k); });
    return n;
  }), []);

  /* ----- a pinned note: it takes its own room at the top of one scroller laid over the whole sheet ----- */
  // The sheet is scrolled by exactly that room, so picking never moves a line; scrolling up brings out
  // whatever the note covers, and the keyboard's focus lands below it (scroll-padding).
  const scrollRef = useRef<HTMLDivElement>(null);
  const flowRef = useRef<HTMLDivElement>(null);
  const pinRef = useRef<HTMLDivElement>(null);
  const pinRoom = useRef(0);
  const pinned = !!explain?.pinned;
  const placePin = useCallback(() => {
    const sc = scrollRef.current, flow = flowRef.current;
    if (!sc || !flow) return;
    if (!pinRef.current) {
      sc.style.height = "";
      sc.style.scrollPaddingTop = "";
      pinRoom.current = 0;
      return;
    }
    const room = flow.offsetTop; // the note and its margins
    // Folded, the sheet keeps the height of its heads; open, it is the phone's height either way.
    sc.style.height = sheetRef.current?.classList.contains("folded") ? `${flow.offsetHeight}px` : "";
    sc.style.scrollPaddingTop = `${room}px`;
    sc.scrollTop += room - pinRoom.current;
    pinRoom.current = room;
  }, []);

  const folded = open == null;
  // Before the fold below: it measures the sheet's new height, which the pinned room must already be part of.
  useLayoutEffect(() => {
    placePin();
    if (!pinned) return;
    const ro = new ResizeObserver(placePin);
    if (pinRef.current) ro.observe(pinRef.current);
    if (flowRef.current) ro.observe(flowRef.current);
    return () => ro.disconnect();
  }, [pinned, explain, folded, open, rm, placePin]);

  /* ----- fold / unfold: from the height on screen to the new one, explicitly; nothing is measured mid-way ----- */
  const lastH = useRef(0);
  const anim = useRef<{ end(): void } | null>(null);
  useLayoutEffect(() => {
    const el = sheetRef.current;
    if (!el) return;
    const from = anim.current ? el.getBoundingClientRect().height : lastH.current;
    anim.current?.end();
    el.style.transition = "none";
    el.style.height = "";
    const to = el.getBoundingClientRect().height;
    if (!from || Math.abs(from - to) < 1 || reduced()) { lastH.current = to; return; }
    el.style.height = `${from}px`;
    void el.offsetHeight;
    el.style.transition = `height ${FOLD_MS}ms cubic-bezier(.32, .72, 0, 1)`;
    el.style.height = `${to}px`;
    let timer = 0;
    const end = () => {
      window.clearTimeout(timer);
      el.removeEventListener("transitionend", onEnd);
      el.style.transition = "";
      el.style.height = "";
      anim.current = null;
      lastH.current = el.getBoundingClientRect().height;
    };
    const onEnd = (e: TransitionEvent) => { if (e.target === el && e.propertyName === "height") end(); };
    el.addEventListener("transitionend", onEnd);
    timer = window.setTimeout(end, FOLD_MS + 80);
    anim.current = { end };
  }, [folded]);
  // Every other render: remember the height on screen, for the next fold.
  useLayoutEffect(() => {
    if (!anim.current && sheetRef.current) lastH.current = sheetRef.current.getBoundingClientRect().height;
  });
  useEffect(() => () => anim.current?.end(), []);

  const sec: SectionView | null = open != null ? rm.sections[open] ?? null : null;
  const headLine = sec ? sec.block.header : null;
  const start = sec ? sec.block.start : 0;
  const end = sec ? sec.block.end : 0;

  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const sync = () => setView({ top: el.scrollTop, h: el.clientHeight });
    sync();
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    return () => ro.disconnect();
  }, [open]);

  // Bring the focused line into view (centre-ish), leaving room for the explain note.
  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el || focusLine == null) return;
    if (focusLine === headLine && (focusLine < start || focusLine >= end)) {
      el.scrollTop = 0; // the note sits at the top of the body
      setView({ top: 0, h: el.clientHeight });
      return;
    }
    if (focusLine < start || focusLine >= end) return;
    const y = (focusLine - start) * LINE_H;
    if (y < el.scrollTop + 80 || y > el.scrollTop + el.clientHeight - 40) {
      el.scrollTop = Math.max(0, y - el.clientHeight / 3);
      setView({ top: el.scrollTop, h: el.clientHeight });
    }
  }, [focusLine, start, end, open, headLine]);

  useLayoutEffect(() => {
    setNoteH(noteRef.current?.offsetHeight ?? 0);
  }, [explain, focusLine]);

  /* ----- keyboard: one tab stop per open section, arrows walk the lines that lead to the phone ----- */
  const mappedFrom = useCallback((from: number, step: 1 | -1) => {
    for (let i = from; i >= start && i < end; i += step) if (rm.target(i)) return i;
    return null;
  }, [rm, start, end]);
  const stop = useMemo(() => {
    if (!sec) return null;
    if (cursor != null && cursor >= start && cursor < end && rm.target(cursor)) return cursor;
    if (focusLine != null && focusLine >= start && focusLine < end && rm.target(focusLine)) return focusLine;
    return mappedFrom(start, 1);
  }, [sec, cursor, focusLine, start, end, rm, mappedFrom]);
  const moveTo = (line: number) => {
    const el = bodyRef.current;
    setCursor(line);
    focusCursor.current = true;
    if (!el) return;
    const y = (line - start) * LINE_H;
    if (y < el.scrollTop || y + LINE_H > el.scrollTop + el.clientHeight) {
      el.scrollTop = Math.max(0, y - el.clientHeight / 2);
      setView({ top: el.scrollTop, h: el.clientHeight });
    }
  };
  useLayoutEffect(() => {
    const i = refocusHead.current;
    if (i == null) return;
    refocusHead.current = null;
    sheetRef.current?.querySelector<HTMLElement>(`.rm-head[data-block="${i}"]`)?.focus({ preventScroll: true });
  }, [open]);
  useLayoutEffect(() => {
    if (!focusCursor.current || stop == null) return;
    focusCursor.current = false;
    bodyRef.current?.querySelector<HTMLElement>(`.rm-line[data-line="${stop}"]`)?.focus({ preventScroll: true });
  });
  const onLineKey = (e: React.KeyboardEvent<HTMLElement>, line: number) => {
    if (e.target !== e.currentTarget) return; // a mask inside the line handles its own keys
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onLine(line); return; }
    const next = e.key === "ArrowDown" ? mappedFrom(line + 1, 1) : e.key === "ArrowUp" ? mappedFrom(line - 1, -1)
      : e.key === "Home" ? mappedFrom(start, 1) : e.key === "End" ? mappedFrom(end - 1, -1) : undefined;
    if (next === undefined) return;
    e.preventDefault();
    if (next != null) moveTo(next);
  };

  // The explain note opens a gap under the focus line: the line itself never moves, nothing is covered.
  // A row that maps to the whole section (its header) gets the note at the top of the body.
  const atHead = !!sec && focusLine === sec.block.header && !(focusLine >= start && focusLine < end);
  const noteOn = !!explain && !explain.pinned && focusLine != null && !!sec && (atHead || (focusLine >= start && focusLine < end));
  const gap = noteOn ? noteH + 10 : 0;
  const topOf = (i: number) => (i - start) * LINE_H + (noteOn && (atHead || i > focusLine!) ? gap : 0);

  const lines: React.ReactNode[] = [];
  for (const i of sec ? drawnLines(start, end, view.top, view.h, LINE_H, 20, stop) : []) {
    const t = rm.doc.lines[i];
    const mapped = !!rm.target(i);
    const cls = ["rm-line", COMMENT.test(t) ? "c" : "", mapped ? "mapped" : "", litLines.has(i) ? "lit" : ""].filter(Boolean).join(" ");
    lines.push(
      <Fragment key={i}>
        <div className={cls} data-line={i} style={{ top: topOf(i) }}
          {...(mapped ? {
            role: "button", tabIndex: i === stop ? 0 : -1, "aria-label": `第 ${i + 1} 行：${spoken(t)}`,
            onClick: (e: React.MouseEvent) => { const k = maskAt(e); if (k) { reveal(k); return; } setCursor(i); onLine(i); },
            onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => onLineKey(e, i),
          } : {})}>
          <span className="no">{i + 1}</span>
          <span className="tx"><Masked text={t} line={i} revealed={revealed} onReveal={reveal} plain={mapped} /></span>
        </div>
        {mapped ? <RevealLine text={t} line={i} revealed={revealed} onToggle={revealAll} top={topOf(i)} tabIndex={i === stop ? 0 : -1} /> : null}
      </Fragment>,
    );
  }

  const head = (s: SectionView, i: number) => {
    const b = s.block;
    if (b.line) {
      const mapped = !!rm.target(b.header);
      const note = explain && !explain.pinned && focusLine === b.header;
      const text = rm.doc.lines[b.header];
      return (
        <div key={i} className="rm-hw">
          <div className={`rm-head line${mapped ? " mapped" : ""}${litLines.has(b.header) ? " lit" : ""}`} data-line={b.header}
            {...(mapped ? {
              role: "button", tabIndex: 0, "aria-label": spoken(text),
              onClick: (e: React.MouseEvent) => { const k = maskAt(e); if (k) reveal(k); else onLine(b.header); },
              onKeyDown: (e: React.KeyboardEvent) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onLine(b.header); } },
            } : {})}>
            <span className="k"><Masked text={text} line={b.header} revealed={revealed} onReveal={reveal} plain={mapped} /></span>
          </div>
          {mapped ? <RevealLine text={text} line={b.header} revealed={revealed} onToggle={revealAll} tabIndex={0} /> : null}
          {note ? <Note explain={explain} className="inline" onPaper={onPaper} /> : null}
        </div>
      );
    }
    return (
      <div key={i} className={`rm-head${s.phone ? " phone" : ""}${litBlocks.has(i) ? " lit" : ""}`} data-block={i}
        role="button" tabIndex={0} aria-expanded={open === i}
        onClick={() => onToggle(i)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); refocusHead.current = i; onToggle(i); } }}>
        <span className="k">{s.label}</span>
        {s.count != null ? <span className="n">{s.count}</span> : null}
        {s.paper ? <i className="paper" role="note" aria-label={s.paper} /> : null}
      </div>
    );
  };

  // The file header: folded to its first line, like a YAML scalar; it opens in place and never takes a section's room.
  const preHot = pre > 0 && rm.sections.slice(0, pre).some((s) => litLines.has(s.block.header) || focusLine === s.block.header);
  const preShown = preOpen || preHot;
  const heads = (from: number, to: number) => {
    const out: React.ReactNode[] = [];
    for (let i = from; i < to; i++) {
      if (i === 0 && pre) {
        const firstLine = rm.sections[0].block.header;
        out.push(
          <div key="pre" className={`rm-pre rm-hw${preShown ? " on" : ""}`}>
            <div className="rm-head line pre" role="button" tabIndex={0} aria-expanded={preShown}
              aria-label={`文件头注释，${pre} 行`}
              onClick={(e) => { const k = maskAt(e); if (k) reveal(k); else setPreOpen((v) => !v); }}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPreOpen((v) => !v); } }}>
              <span className="k"><Masked text={rm.doc.lines[firstLine]} line={firstLine} revealed={revealed} onReveal={reveal} plain /></span>
              {preShown ? null : <span className="n">{pre}</span>}
            </div>
            <RevealLine text={rm.doc.lines[firstLine]} line={firstLine} revealed={revealed} onToggle={revealAll} tabIndex={0} />
            {preShown ? rm.sections.slice(1, pre).map((s, k) => head(s, 1 + k)) : null}
          </div>,
        );
        i = pre - 1;
        continue;
      }
      out.push(head(rm.sections[i], i));
    }
    return out;
  };

  const all = rm.sections;
  return (
    <section ref={sheetRef} className={`rm-read${open == null ? " folded" : ""}${pinned ? " has-pin" : ""}`} aria-label="原文">
      <div className="rm-scroll" ref={scrollRef} onScroll={pinned ? onScroll : undefined}>
        {explain?.pinned ? <Note explain={explain} className="pinned" noteRef={pinRef} onPaper={onPaper} /> : null}
        <div className="rm-flow" ref={flowRef}>
          {open == null ? (
            <div className="rm-heads all">{heads(0, all.length)}</div>
          ) : (
            <>
              <div className="rm-heads" ref={aboveRef}>{heads(0, open)}</div>
              <div className="rm-open">
                {head(all[open], open)}
                <div className="rm-body" ref={bodyRef} onScroll={(e) => { const el = e.currentTarget; setView({ top: el.scrollTop, h: el.clientHeight }); onScroll(); }}>
                  <div className="rm-lines" style={{ height: (end - start) * LINE_H + gap + 8 }}>
                    {lines}
                    {explain && noteOn ? (
                      <Note explain={explain} className="" noteRef={noteRef} onPaper={onPaper}
                        style={{ top: atHead ? 4 : (focusLine! - start + 1) * LINE_H + 4 }} />
                    ) : null}
                  </div>
                </div>
              </div>
              <div className="rm-heads">{heads(open + 1, all.length)}</div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
