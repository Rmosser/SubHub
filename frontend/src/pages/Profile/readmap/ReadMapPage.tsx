/* 配置与场景 — read-only map of what SubHub writes onto the phone.
   Left: the phone app's own screens, stacked like the iOS app switcher, with real values from the rendered config.
   Right: the rendered config itself, folded by section. Picking either side lights the other. */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Spinner from "@cloudscape-design/components/spinner";
import { useDevicePreview, useDevices } from "@/api/queries";
import { GlassSelect } from "@/components/GlassSelect";
import { parseConfig } from "./parse";
import { ReadMap, type ClientMap, type RowDef, type RRow } from "./model";
import { PhoneStack, TOP, isShell, type Pick } from "./stack";
import { GAP, fitStage, frameWidth, sameGeo, type StageGeo } from "./stageFit";
import { FOLD_MS, ReadingColumn, type Explain } from "./ReadingColumn";
import { ScenarioSection } from "./ScenarioSection";
import { pickOnFront, spotOf } from "./spot";
import { WarningsChip } from "./Warnings";
import type { Warning } from "./warningGroups";
import "./phone.css";
import "./readmap.css";

type Client = ClientMap["client"];
const CLIENTS: { id: Client; label: string }[] = [
  { id: "surge", label: "Surge" },
  { id: "shadowrocket", label: "Shadowrocket" },
  { id: "clash-mi", label: "Clash Mi" },
];
const LOADERS: Record<Client, () => Promise<ClientMap>> = {
  surge: () => import("./data/surge.json").then((m) => m.default as unknown as ClientMap),
  shadowrocket: () => import("./data/shadowrocket.json").then((m) => m.default as unknown as ClientMap),
  "clash-mi": () => import("./data/clash-mi.json").then((m) => m.default as unknown as ClientMap),
};
const LAST = "subhub.readmap.client";
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
/** What the page lays under the stage on its way down: its ancestors' bottom padding, borders and margins. */
function roomBelow(el: HTMLElement) {
  let px = 0;
  for (let e = el.parentElement; e && e !== document.documentElement; e = e.parentElement) {
    const cs = getComputedStyle(e);
    px += parseFloat(cs.paddingBottom) + parseFloat(cs.borderBottomWidth) + parseFloat(cs.marginBottom);
  }
  return px;
}

function useClientMap(client: Client) {
  const [map, setMap] = useState<ClientMap | null>(null);
  useEffect(() => {
    let live = true;
    setMap(null);
    void LOADERS[client]().then((m) => { if (live) setMap(m); });
    return () => { live = false; };
  }, [client]);
  return map;
}

/** Where a row's setting lives, for rows SubHub leaves alone. Lit rows say what was written instead. */
function whereItLives(def: RowDef, r: RRow): string | null {
  if (r.state === "lit") return null;
  if (def.rel === "d" || (def.rel === "n" && def.layer === "a")) return "只在手机上设置，配置里没有它。";
  if (def.rel === "n") return "配置里没有这一项，App 用默认值。";
  if ((def.rel === "w" || def.rel === "p") && def.bind && !r.lines.length) return "这份配置没有写这一项，App 用默认值。";
  return null;
}

export function ReadMapPage() {
  const [params, setParams] = useSearchParams();
  const client = (CLIENTS.find((c) => c.id === params.get("c"))?.id ?? (localStorage.getItem(LAST) as Client | null) ?? "surge") as Client;
  const devices = useDevices();
  const list = devices.data ?? [];
  const device = list.find((d) => d.id === params.get("d")) ?? list[0];
  const map = useClientMap(client);
  const preview = useDevicePreview(device?.subscription_id ?? "", map ? map.target : null);

  const setParam = useCallback((patch: Record<string, string | null>) => {
    setParams((p) => {
      const n = new URLSearchParams(p);
      for (const [k, v] of Object.entries(patch)) { if (v == null) n.delete(k); else n.set(k, v); }
      return n;
    }, { replace: true });
  }, [setParams]);
  // Where the phone is (screen / row / item) changes on every tap. It goes straight into the address bar
  // for reloads and shared links; routing through the router would re-render the whole shell each time.
  const writeSpot = useCallback((patch: Record<string, string | null>) => {
    const n = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(patch)) { if (v == null) n.delete(k); else n.set(k, v); }
    const search = n.toString();
    if (`?${search}` === window.location.search || (!search && !window.location.search)) return;
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`);
  }, []);

  const blocked = preview.error && (preview.error as { status?: number }).status === 409 ? (preview.error as Error).message : null;
  const content = preview.data?.content ?? "";
  const rm = useMemo(() => (map && (preview.data || blocked) ? new ReadMap(map, parseConfig(blocked ? "" : content, map.format)) : null),
    [map, content, blocked, preview.data]);
  const warnings: Warning[] = useMemo(() => {
    const d = preview.data;
    return d ? [...(d.blockers ?? []), ...(d.diagnostics ?? [])] : [];
  }, [preview.data]);

  /* ---------- deck ---------- */
  // Switching client or device keeps the last map on screen until the next one is ready: no spinner flash.
  const lastRm = useRef<ReadMap | null>(null);
  if (rm) lastRm.current = rm;
  const view = rm ?? lastRm.current;
  const pending = !rm && !!view;
  const ready = view != null; // the host div exists exactly while there is a map to draw
  const pageRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const stackRef = useRef<PhoneStack | null>(null);
  const [pick, setPick] = useState<Pick | null>(null);
  const [path, setPath] = useState<string[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [focusLine, setFocusLine] = useState<number | null>(null);
  const [geo, setGeo] = useState<StageGeo | null>(null);
  /** The last fit, as soon as it is made: the wire reads it on the next frame, before the render that `geo` waits for. */
  const fitted = useRef<StageGeo | null>(null);

  // Everything the page holds about the phone (open section, focused line, picked row, path) belongs to one
  // map of one device. A new client, device or config resets it during render, so no frame ever reads an
  // index or a row from the map before.
  const session = `${client}|${device?.id ?? ""}`;
  const [bound, setBound] = useState<{ session: string; view: ReadMap | null }>({ session, view });
  if (bound.session !== session || bound.view !== view) {
    setBound({ session, view });
    setOpen(null);
    setFocusLine(null);
    setPick(null);
    if (bound.session !== session) setPath([]);
  }
  /** The session the deck was last loaded for; the address bar is only written for that one. */
  const loadedFor = useRef<string | null>(null);
  const wireRef = useRef<SVGPathElement>(null);
  const dotRef = useRef<SVGCircleElement>(null);

  /* ---------- wire (drawn straight onto the SVG; scrolling never re-renders the page) ---------- */
  const live = useRef<{ focusLine: number | null; rm: ReadMap | null; blockOf(line: number): number }>({ focusLine, rm, blockOf: () => -1 });
  const drawWire = useCallback(() => {
    const stage = stageRef.current, line = wireRef.current, dot = dotRef.current, s = stackRef.current;
    if (!stage || !line || !dot) return;
    const hide = () => { line.setAttribute("d", ""); dot.setAttribute("r", "0"); };
    const { focusLine: fl, blockOf } = live.current;
    if (!s || !s.pick || s.moving || !fitted.current || fitted.current.stacked) return hide();
    const el = s.rowEl(s.pick.key);
    const read = stage.querySelector<HTMLElement>(".rm-read");
    if (!el || !read) return hide();
    const st = stage.getBoundingClientRect();
    const a = el.getBoundingClientRect();
    const scr = el.closest(".ios-screen")!.getBoundingClientRect();
    // A pinned note (a row or a control with nothing in the 原文) glows on its own edge instead.
    if (isShell(s.pick.row) || read.querySelector(".rm-explain.pinned")) return hide();
    let target: DOMRect | null = null;
    const lineEl = fl != null ? read.querySelector<HTMLElement>(`[data-line="${fl}"]`) : null;
    if (lineEl) {
      const r = lineEl.getBoundingClientRect();
      const box = (lineEl.closest(".rm-body") ?? read).getBoundingClientRect();
      const y = Math.min(Math.max(r.top + r.height / 2, box.top + 4), box.bottom - 4);
      target = new DOMRect(r.left, y - 1, 2, 2);
    } else if (fl != null) {
      const h = read.querySelector<HTMLElement>(`[data-block="${blockOf(fl)}"]`);
      const body = read.querySelector<HTMLElement>(".rm-body");
      if (h) target = h.getBoundingClientRect();
      else if (body) { const box = body.getBoundingClientRect(); target = new DOMRect(box.left, box.top + 2, 2, 2); }
    }
    if (!target) return hide();
    const cy = a.top + a.height / 2;
    if (cy < scr.top + 40 || cy > scr.bottom - 40) return hide();
    const x1 = scr.right - st.left + 8, y1 = cy - st.top;
    const x2 = target.left - st.left, y2 = target.top + target.height / 2 - st.top;
    const mx = (x1 + x2) / 2;
    line.setAttribute("d", `M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`);
    dot.setAttribute("cx", String(x1)); dot.setAttribute("cy", String(y1)); dot.setAttribute("r", "2.5");
  }, []);
  const frame = useRef(0);
  const scheduleWire = useCallback(() => {
    if (frame.current) return;
    frame.current = requestAnimationFrame(() => { frame.current = 0; drawWire(); });
  }, [drawWire]);
  useEffect(() => () => { cancelAnimationFrame(frame.current); frame.current = 0; }, []);

  useLayoutEffect(() => {
    if (!hostRef.current) return;
    const s = new PhoneStack(hostRef.current, {
      onPick: (p) => setPick(p),
      onPath: (p) => setPath(p),
      onMoved: scheduleWire,
    });
    stackRef.current = s;
    return () => { s.destroy(); stackRef.current = null; };
  }, [ready, scheduleWire]);

  // Size: the phone scale follows the visible height; the deck is the same width for every client. The width
  // comes from the page, never from the stage or the frame: those are sized from it, so reading them back
  // would keep the last width and the reading column could only ever shrink.
  useLayoutEffect(() => {
    const page = pageRef.current, stage = stageRef.current, s = stackRef.current;
    if (!page || !stage || !s) return;
    let lastW = 0, raf = 0;
    const fit = () => {
      lastW = page.clientWidth;
      const top = stage.getBoundingClientRect().top + window.scrollY;
      // The stage and what sits under it fill the window exactly, so a tall enough window never scrolls.
      const availH = Math.max(480, window.innerHeight - Math.max(top, 72) - Math.max(28, roomBelow(stage)));
      const g = fitStage(lastW, availH, PhoneStack);
      fitted.current = g;
      s.setScale(g.S);
      setGeo((was) => (sameGeo(was, g) ? was : g));
      scheduleWire();
    };
    fit();
    // The page's height follows the stage, so only a new width (a drawer, the rail folding) is a reason to fit
    // again here; the window's own size changes come through `resize`. The fit resizes the deck at once, and so
    // the page, which must not happen inside the observer's own callback: it waits for the next frame.
    const ro = new ResizeObserver(() => {
      if (raf || page.clientWidth === lastW) return;
      raf = requestAnimationFrame(() => { raf = 0; fit(); });
    });
    ro.observe(page);
    window.addEventListener("resize", fit);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); window.removeEventListener("resize", fit); };
  }, [ready, scheduleWire]);

  // A new session lets go of the old deck's selection at once; the old deck stays on screen, dimmed, until the new map is ready.
  useLayoutEffect(() => { stackRef.current?.clearPick(); }, [session]);

  // Load the client (or a new revision / device): start at the deep-linked screen or the root.
  useEffect(() => {
    const s = stackRef.current;
    if (!s || !map || !rm || map.client !== client) return;
    loadedFor.current = session;
    // The spot lives in the address bar (see writeSpot), so read it from there, not from the router.
    const q = new URLSearchParams(window.location.search);
    const want = q.get("s");
    const screen = want && map.screens[want] ? want : map.root;
    const start = rm.path(screen);
    const item = q.get("i");
    const n = item != null && /^\d+$/.test(item) ? Number(item) : undefined;
    const items: Record<string, number> = {};
    // A detail screen reads its parent list's item; a picked list row carries its own.
    const parent = map.screens[screen]?.parent;
    const row = q.get("r");
    const own = row ? rm.rowDef(screen, row)?.bind?.kind === "list" : false;
    if (n != null && parent && !own) items[parent] = n;
    s.load(map, rm, start, items);
    if (row) s.select(screen, row, own ? n : undefined);
  }, [map, rm, session, client]);

  /* ---------- selection → reading column ---------- */
  // Only a pick on the screen in front explains anything: the deck may have moved on since it was made.
  const front = path[path.length - 1];
  const shown = useMemo(() => pickOnFront(pick, front != null ? [front] : []), [pick, front]);
  const rrow = useMemo(() => {
    const s = stackRef.current;
    if (!shown || !rm || !s || isShell(shown.row) || !rm.map.screens[shown.screen]) return null;
    const data = rm.screen(shown.screen, s.items, shown.item);
    return data.groups.flatMap((g) => g.rows).find((r) => r.key === shown.key) ?? null;
  }, [shown, rm]);

  const litLines = useMemo(() => new Set(rrow?.lines ?? []), [rrow]);
  const blockOf = useCallback((line: number) => rm?.sections.findIndex((s) => line === s.block.header || (line >= s.block.start && line < s.block.end)) ?? -1, [rm]);
  live.current = { focusLine, rm, blockOf };

  useEffect(() => {
    if (!rrow || !rm) return;
    const first = rrow.lines[0];
    if (first == null) { setFocusLine(null); return; } // nothing in the 原文: the note pins to the top
    const b = blockOf(first);
    if (b >= 0 && !rm.sections[b].block.line) setOpen(b);
    setFocusLine(first);
  }, [rrow, rm, blockOf]);

  useEffect(() => {
    // Nothing until the deck has loaded this session: the deep link stays intact, and a previous device's spot is never written back.
    if (!path.length || loadedFor.current !== session) return;
    writeSpot({ c: client, d: device?.id ?? null, ...spotOf(path, pick, map?.root, stackRef.current?.items ?? {}) });
  }, [path, pick, client, device?.id, map, writeSpot, session]);

  // Walking the phone into a screen that a section lands on opens that section of the 原文.
  const lastFront = useRef<string | null>(null);
  useEffect(() => {
    const front = path[path.length - 1];
    if (!rm || !front || front === lastFront.current) return;
    const first = lastFront.current == null;
    lastFront.current = front;
    if (first && front === map?.root) return; // plain arrival: keep the overview
    const i = rm.sections.findIndex((s) => s.landing === front && !s.block.line);
    if (i >= 0) { setOpen(i); return; }
    // A detail screen opened from a list: open its item's lines.
    const s = stackRef.current, parent = map?.screens[front]?.parent;
    if (!s || !parent || s.items[parent] == null) return;
    const line = rm.screen(front, s.items).groups.flatMap((g) => g.rows).find((r) => r.lines.length)?.lines[0];
    const b = line != null ? blockOf(line) : -1;
    if (b >= 0 && !rm.sections[b].block.line) { setOpen(b); setFocusLine(line!); }
  }, [path, rm, map, blockOf]);
  useEffect(() => { lastFront.current = null; }, [rm]);

  // Every row explains itself: what SubHub wrote there, or what the control does and where it lives.
  const explain: Explain | null = useMemo(() => {
    if (!shown || !rm) return null;
    // The app's own controls: one sentence on what they do. Nothing in the 原文, so the note pins.
    if (isShell(shown.row)) {
      const text = rm.map.screens[shown.screen]?.shell?.[shown.row.slice(1)];
      return text ? { text, pinned: true, quiet: true } : null;
    }
    if (!rrow) return null;
    const def = rm.rowDef(shown.screen, shown.row);
    if (!def) return null;
    const pinned = !rrow.lines.length;
    if (rrow.paper) return { text: rrow.paper, paper: true, pinned };
    if (def.explain) {
      const links = rrow.state === "lit"
        ? rm.papersFor(rm.sectionKeys(shown.screen, shown.row)).filter((p) => p.row !== shown.row).map((p) => ({ text: p.text, screen: p.screen, row: p.row }))
        : [];
      return { text: def.explain, links, pinned };
    }
    const text = [def.about, whereItLives(def, rrow)].filter(Boolean).join("");
    return text ? { text, pinned, quiet: true } : null;
  }, [shown, rm, rrow]);

  const litBlocks = useMemo(() => {
    const out = new Set<number>();
    if (!rm) return out;
    for (const l of litLines) { const b = blockOf(l); if (b >= 0) out.add(b); }
    const front = path[path.length - 1];
    rm.sections.forEach((s, i) => { if (s.landing && s.landing === front) out.add(i); });
    return out;
  }, [rm, litLines, path, blockOf]);

  /* ---------- reading column → phone ---------- */
  const goLine = useCallback((line: number) => {
    const s = stackRef.current;
    const t = rm?.target(line);
    if (!s || !rm || !t) return;
    void s.goTo(rm.path(t.screen), { row: t.row, item: t.item });
  }, [rm]);

  const toggle = useCallback((i: number) => {
    setOpen((o) => (o === i ? null : i));
    setFocusLine(null);
    const s = stackRef.current;
    const sec = rm?.sections[i];
    if (s && rm && sec?.landing && open !== i) {
      s.clearPick();
      void s.goTo(rm.path(sec.landing));
    }
  }, [rm, open]);

  const goPaper = useCallback((screen: string, row: string) => {
    const s = stackRef.current;
    if (s && rm) void s.goTo(rm.path(screen), { row });
  }, [rm]);

  useLayoutEffect(() => { scheduleWire(); });

  // Stacked, the 原文 sits under the phone: bring the note into view, by as little as it takes.
  const stacked = !!geo?.stacked;
  useEffect(() => {
    if (!explain || !stacked) return;
    const bring = () => stageRef.current?.querySelector<HTMLElement>(".rm-read .rm-explain")
      ?.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
    const id = requestAnimationFrame(bring);
    // A section that unfolds for the note moves it while it opens: look again once the fold has settled.
    const t = window.setTimeout(bring, FOLD_MS + 60);
    return () => { cancelAnimationFrame(id); window.clearTimeout(t); };
  }, [explain, stacked]);

  /* ---------- render ---------- */
  if (devices.isLoading) return <div className="rm-empty"><Spinner size="large" /></div>;
  if (!device) {
    return (
      <div className="rm-page">
        <div className="rm-empty"><div className="outline" /><Link to="/devices">添加设备</Link></div>
        <ScenarioSection />
      </div>
    );
  }

  // The selection and the spot reset with the session (see `bound`); only the address bar needs the old spot gone.
  const switchClient = (id: Client) => {
    if (id === client) return;
    localStorage.setItem(LAST, id);
    setParam({ c: id, s: null, r: null, i: null });
  };
  const inset = geo && !geo.stacked ? geo.deckW - geo.S * 402 : 0; // the front phone's left edge
  const fw = geo ? frameWidth(geo) : null;

  return (
    <div className="rm-page" ref={pageRef}>
      <div className="rm-frame" style={fw != null ? { width: fw } : undefined}>
        <div className="rm-bar" style={{ paddingLeft: inset }}>
          <div className="glass-seg rm-clients" role="group" aria-label="客户端">
            {CLIENTS.map((c) => (
              <button key={c.id} type="button" aria-pressed={c.id === client} onClick={() => switchClient(c.id)}>{c.label}</button>
            ))}
          </div>
          {list.length > 1 ? (
            <GlassSelect ariaLabel="设备" value={device.id} options={list.map((d) => ({ value: d.id, label: d.device_name }))}
              onChange={(v) => setParam({ d: v, s: null, r: null, i: null })} />
          ) : (
            <span className="rm-device-name" data-glass-etch>{device.device_name}</span>
          )}
          <span className="rm-bar-fill" />
          {warnings.length ? <WarningsChip list={warnings} /> : null}
        </div>
        <div className={`rm-stage${geo?.stacked ? " stacked" : ""}${pending ? " pending" : ""}`} ref={stageRef} style={{ gap: GAP }}>
          <svg className="rm-wires" aria-hidden="true"><path ref={wireRef} /><circle ref={dotRef} r="0" /></svg>
          {/* Keyed apart: the deck owns its host's children, so React must never reuse that div for anything else. */}
          {view ? <div key="stack" className="rm-stack" ref={hostRef} /> : <div key="wait" className="rm-empty"><Spinner size="large" /></div>}
          {view && geo ? (
            <div className="rm-col" style={{ width: geo.readW, height: geo.h, paddingTop: geo.stacked ? 0 : TOP }}>
              {blocked ? (
                <section className="rm-read"><div className="rm-blocked">{blocked}</div></section>
              ) : (
                <ReadingColumn rm={view} open={open} litLines={litLines} litBlocks={litBlocks} focusLine={focusLine} explain={explain}
                  onToggle={toggle} onLine={goLine} onPaper={goPaper} onScroll={scheduleWire} />
              )}
            </div>
          ) : null}
        </div>
      </div>
      <ScenarioSection />
    </div>
  );
}
