/* Phone deck. The front phone never moves; every level it came from sinks behind it with a thin edge left
   showing (click the edge to go back). A push lays the next screen on top with a short slide; sheets rise.
   Motion is transform + opacity only, so it stays on the compositor. */
import type { ClientMap, ReadMap, RScreen } from "./model";
import { chromeFor, renderPhoneScreen } from "./phoneKit";
import { tapWhile, Transit } from "./transit";

const W = 402;
const H = 874;
/** Visible edge of each level behind the front phone, in phone px. */
const EDGE = 15;
/** Levels drawn behind the front phone. */
const DEPTH = 3;
/** Band above the phones for the hover title. */
export const TOP = 26;
const SCALE = [1, 0.955, 0.912, 0.872];
const VEIL = [0, 0.38, 0.54, 0.66];
const SHIFT = 30;
const RISE = 64;
const DUR = 420;
/** Everything on a phone screen that answers a tap or a key. */
const ACTIVE = ".row,[data-root],[data-nav],[data-shell]";

export interface Pick {
  screen: string;
  /** Data row id, or `@<id>` for a piece of the app's own chrome (启动, a tab, a nav button). */
  row: string;
  key: string;
  item?: number;
}

/** Shell picks (the app's own buttons and tabs) carry `@` ids. */
export const isShell = (row: string) => row.startsWith("@");

interface Slot {
  el: HTMLDivElement;
  pane: HTMLDivElement;
  veil: HTMLDivElement;
  screen: HTMLDivElement;
  id: string;
  way: "right" | "up";
  data?: RScreen;
}

interface Geom { x: number; y: number; s: number; op: number; veil: number }

/** Run after the next frame has been painted. */
function afterPaint(fn: () => void) {
  requestAnimationFrame(() => requestAnimationFrame(fn));
}

/** A dialog or menu is open somewhere on the page: Escape belongs to it. */
function overlayOpen(except: HTMLElement): boolean {
  return [...document.querySelectorAll<HTMLElement>('[role="dialog"],[role="alertdialog"],[role="menu"],[role="listbox"],dialog[open]')]
    .some((el) => !except.contains(el) && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden");
}

export interface StackEvents {
  onPick(p: Pick | null): void;
  onPath(path: string[]): void;
  /** Something under the wire moved (scroll, transition end). */
  onMoved(): void;
}

export class PhoneStack {
  private host: HTMLElement;
  private tag: HTMLDivElement;
  private map!: ClientMap;
  private rm!: ReadMap;
  private ev: StackEvents;
  private slots: Slot[] = [];
  private S = 0.75;
  private dur: number;
  private motion: MediaQueryList;
  /** The running transition, and the last request made during it. */
  private transit = new Transit();
  private hoverAt = -1;
  /** Bumped by every load (new client / config / device): work started before it is stale. */
  private gen = 0;
  /** Selected list index per list screen (feeds detail screens). */
  items: Record<string, number> = {};
  pick: Pick | null = null;

  constructor(host: HTMLElement, ev: StackEvents) {
    this.host = host;
    this.ev = ev;
    this.motion = matchMedia("(prefers-reduced-motion: reduce)");
    this.dur = this.motion.matches ? 0 : DUR;
    host.style.setProperty("--dur", `${this.dur}ms`);
    this.tag = Object.assign(document.createElement("div"), { className: "tag" });
    host.addEventListener("click", this.onClick);
    host.addEventListener("keydown", this.onKey);
    document.addEventListener("keydown", this.onDocKey);
    this.motion.addEventListener("change", this.onMotion);
  }

  destroy() {
    this.gen++;
    this.transit.abort();
    this.host.removeEventListener("click", this.onClick);
    this.host.removeEventListener("keydown", this.onKey);
    document.removeEventListener("keydown", this.onDocKey);
    this.motion.removeEventListener("change", this.onMotion);
    this.host.innerHTML = "";
  }

  get path() {
    return this.slots.map((s) => s.id);
  }

  get moving() {
    return this.transit.busy;
  }

  /** Width the deck needs at scale S. The same for every client, so switching never moves the phone. */
  static width(S: number) {
    return (W + EDGE * DEPTH) * S;
  }

  static height(S: number) {
    return H * S + TOP;
  }

  setScale(S: number) {
    this.S = S;
    this.host.style.width = `${PhoneStack.width(S)}px`;
    this.host.style.height = `${PhoneStack.height(S)}px`;
    this.instant(() => this.layout());
  }

  /** New client / config / device: drop whatever was in flight and rebuild instantly on `path`. */
  load(map: ClientMap, rm: ReadMap, path: string[], items: Record<string, number> = {}, pick: Pick | null = null) {
    const swap = !!this.map && this.map !== map && !!this.dur; // another client: a short crossfade, never a slide
    this.gen++;
    this.transit.abort();
    this.map = map;
    this.rm = rm;
    this.reset(path, items, pick);
    if (swap) this.host.animate([{ opacity: 0.2 }, { opacity: 1 }], { duration: 260, easing: "ease-out" });
  }

  /** Same client: rebuild on another root (tab / segment switch). The page hears the new path and pick at once. */
  private reset(path: string[], items: Record<string, number>, pick: Pick | null) {
    this.items = { ...items };
    this.pick = pick;
    this.host.innerHTML = "";
    this.host.append(this.tag);
    this.slots = [];
    this.hoverAt = -1;
    this.instant(() => {
      path.forEach((id, i) => {
        const slot = this.make(id, this.wayOf(id, path[i - 1]));
        this.host.append(slot.el);
        this.slots.push(slot);
      });
      this.layout();
      this.marks();
    });
    this.ev.onPath(this.path);
    this.ev.onPick(this.pick);
  }

  /** Re-resolve every screen (selection of a list item changed what a detail screen shows). */
  refresh() {
    this.slots.forEach((s) => this.draw(s));
    this.marks();
  }

  front() {
    return this.slots[this.slots.length - 1];
  }

  rowEl(key: string): HTMLElement | null {
    return this.front()?.screen.querySelector(`[data-key="${CSS.escape(key)}"]`) ?? null;
  }

  /* ---------- geometry ---------- */

  private wayOf(id: string, prev?: string): "right" | "up" {
    const def = this.map.screens[id];
    return def?.sheet && !(prev && this.map.screens[prev]?.sheet) ? "up" : "right";
  }

  private geom(depth: number, mode: "rest" | "enter" | "exit" | "fade", way: "right" | "up", hover = false): Geom {
    const S = this.S;
    const d = Math.min(depth, DEPTH);
    const s = S * SCALE[d];
    const reserve = EDGE * DEPTH * S;
    const g: Geom = { x: reserve - EDGE * d * S, y: TOP + (H * S - H * s) / 2, s, op: depth > DEPTH ? 0 : 1, veil: VEIL[d] };
    if (hover && depth > 0) { g.x -= 22 * S; g.veil *= 0.45; }
    if (mode === "enter" || mode === "exit") {
      g.op = 0;
      if (way === "up") g.y += RISE * S;
      else g.x = reserve + SHIFT * S;
    }
    if (mode === "fade") g.op = 0;
    return g;
  }

  private apply(slot: Slot, g: Geom) {
    slot.el.style.transform = `translate3d(${g.x}px,${g.y}px,0) scale(${g.s})`;
    slot.el.style.opacity = String(g.op);
    slot.veil.style.opacity = String(g.veil);
  }

  /** Front screen: every drawn control is a button in the tab order. Levels behind: out of it. */
  private wire(slot: Slot) {
    const i = this.slots.indexOf(slot);
    const back = i >= 0 && i < this.slots.length - 1;
    slot.screen.querySelectorAll<HTMLElement>(ACTIVE).forEach((r) => {
      r.tabIndex = back ? -1 : 0;
      r.setAttribute("role", "button");
    });
  }

  private layout() {
    const n = this.slots.length;
    this.slots.forEach((slot, i) => {
      const depth = n - 1 - i;
      const back = depth > 0;
      slot.el.classList.toggle("back", back);
      slot.el.style.zIndex = String(10 - depth);
      this.apply(slot, this.geom(depth, "rest", slot.way, this.hoverAt === i));
      slot.pane.tabIndex = back ? 0 : -1;
      slot.pane.setAttribute("role", back ? "button" : "group");
      slot.pane.setAttribute("aria-label", back ? `回到「${slot.data?.title ?? ""}」` : slot.data?.title ?? "");
      slot.screen.setAttribute("aria-hidden", back ? "true" : "false");
      // A level behind is one button (its pane): nothing inside it takes focus or a pointer, so a tap on it lands on the pane.
      slot.screen.inert = back;
      this.wire(slot);
    });
    this.showTag();
  }

  /** Title of the level under the pointer, in the band above the deck. */
  private showTag() {
    const slot = this.slots[this.hoverAt];
    if (!slot || this.hoverAt >= this.slots.length - 1) { this.tag.classList.remove("on"); return; }
    const depth = this.slots.length - 1 - this.hoverAt;
    this.tag.textContent = slot.data?.title ?? "";
    this.tag.style.transform = `translateX(${this.geom(depth, "rest", slot.way, true).x}px)`;
    this.tag.classList.add("on");
  }

  private instant(fn: () => void) {
    this.host.classList.add("instant");
    fn();
    void this.host.offsetWidth;
    requestAnimationFrame(() => { if (this.dur) this.host.classList.remove("instant"); });
  }

  /** Reduced motion can change while the page is open: follow it at once, and finish a running slide now. */
  private onMotion = () => {
    this.dur = this.motion.matches ? 0 : DUR;
    this.host.style.setProperty("--dur", `${this.dur}ms`);
    if (this.dur) { this.host.classList.remove("instant"); return; }
    this.host.classList.add("instant");
    this.transit.settle();
  };

  /* ---------- slots ---------- */

  private make(id: string, way: "right" | "up"): Slot {
    const el = document.createElement("div");
    el.className = "slot";
    el.dataset.screen = id;
    const shade = Object.assign(document.createElement("div"), { className: "shade" });
    const pane = Object.assign(document.createElement("div"), { className: "pane" });
    const screen = document.createElement("div");
    const veil = Object.assign(document.createElement("div"), { className: "veil" });
    pane.append(screen, veil);
    el.append(shade, pane);
    const slot: Slot = { el, pane, veil, screen, id, way };
    this.draw(slot);
    pane.addEventListener("pointerenter", () => {
      const i = this.slots.indexOf(slot);
      if (i >= 0 && i < this.slots.length - 1 && !this.transit.busy) { this.hoverAt = i; this.layout(); }
    });
    pane.addEventListener("pointerleave", () => {
      if (this.hoverAt >= 0 && this.hoverAt === this.slots.indexOf(slot)) { this.hoverAt = -1; this.layout(); }
    });
    return slot;
  }

  private draw(slot: Slot) {
    const sc = slot.screen.querySelector<HTMLElement>(".scroll");
    const top = sc?.scrollTop ?? 0;
    const around = this.pick?.screen === slot.id ? this.pick.item : undefined;
    slot.data = this.rm.screen(slot.id, this.items, around);
    renderPhoneScreen(slot.screen, this.map, slot.data, chromeFor(this.map, slot.id));
    const sc2 = slot.screen.querySelector<HTMLElement>(".scroll");
    if (sc2) {
      sc2.scrollTop = top;
      sc2.addEventListener("scroll", () => this.ev.onMoved(), { passive: true });
    }
    // A redraw replaces the rows: give the new ones their tab stops and roles again.
    this.wire(slot);
  }

  /** Light the picked row and the entry rows along the path. */
  private marks() {
    this.slots.forEach((slot, i) => {
      const next = this.slots[i + 1];
      slot.screen.querySelectorAll(".pick").forEach((e) => e.classList.remove("pick"));
      let on: Element | null = null;
      if (next) {
        const via = this.map.screens[next.id]?.via;
        const item = this.items[slot.id];
        on = slot.screen.querySelector(item != null
          ? `[data-row="${CSS.escape(via ?? "")}"][data-item="${item}"]`
          : `[data-row="${CSS.escape(via ?? "")}"]`);
      } else if (this.pick && this.pick.screen === slot.id) {
        on = slot.screen.querySelector(`[data-key="${CSS.escape(this.pick.key)}"]`);
      }
      on?.classList.add("pick");
      slot.screen.classList.toggle("has-pick", !next && !!on);
    });
  }

  /* ---------- navigation ---------- */

  /** One transition: keep the first `keep` levels, lay `add` on top. Pops and pushes happen together. */
  private go(keep: number, add: string[], from?: HTMLElement): Promise<void> {
    return new Promise((done) => {
      if (keep === this.slots.length && !add.length) return done();
      if (add.some((id) => !this.map.screens[id])) return done();
      const gen = this.gen;
      // Keyboard users keep their place: the focus follows the push, and comes back to the row on a pop.
      const hadFocus = this.host.contains(document.activeElement);
      const popped = add.length ? undefined : this.slots[keep]?.id;
      this.hoverAt = -1;
      from?.classList.add("pressed");
      const run = () => {
        from?.classList.remove("pressed");
        const gone = this.slots.splice(keep);
        gone.forEach((s) => { delete this.items[s.id]; });
        // Leaving levels: the one that was in front slides back out the way it came; the rest just fade.
        gone.forEach((slot, k) => {
          const top = k === gone.length - 1;
          slot.el.style.zIndex = String(add.length ? 9 : 20 + k);
          slot.el.style.transition = top
            ? `transform var(--dur) var(--ease), opacity calc(var(--dur) * .5) ease calc(var(--dur) * .15)`
            : `opacity calc(var(--dur) * .5) ease`;
          this.apply(slot, this.geom(top ? 0 : gone.length - 1 - k, top ? "exit" : "fade", slot.way));
        });
        // Arriving levels: the last one enters; any in between appear in place behind it.
        const total = keep + add.length;
        add.forEach((id, k) => {
          const prev = k ? add[k - 1] : this.slots[keep - 1]?.id;
          const slot = this.make(id, this.wayOf(id, prev));
          const last = k === add.length - 1;
          this.apply(slot, this.geom(last ? 0 : total - 1 - (keep + k), last ? "enter" : "fade", slot.way));
          slot.el.style.zIndex = String(last ? 11 : 10 - (total - 1 - (keep + k)));
          this.host.append(slot.el);
          this.slots.push(slot);
        });
        void this.host.offsetWidth;
        this.pick = null;
        this.layout();
        this.marks();
        // Tell the page only once the transition runs on the compositor, so its re-render never eats a frame.
        // It hears the deck as it is then: a pick made right after the move (goTo under reduced motion) stands.
        afterPaint(() => { if (gen === this.gen) { this.ev.onPath(this.path); this.ev.onPick(this.pick); } });
        return {
          ms: this.dur ? this.dur + 30 : 0,
          end: (cut: boolean) => {
            gone.forEach((s) => s.el.remove());
            if (!cut && gen === this.gen) {
              this.ev.onMoved();
              if (hadFocus) this.focusAfter(popped);
            }
            done();
          },
        };
      };
      // A tapped row shows its pressed state for a beat, like iOS; a load in that beat just lets go of it.
      this.transit.start(this.dur && from ? 90 : 0, run, () => { from?.classList.remove("pressed"); done(); });
    });
  }

  /** After a push the focus goes to the new screen's way back (or its first control); after a pop, to the row it came from. */
  private focusAfter(popped?: string) {
    const f = this.front();
    if (!f) return;
    let el: HTMLElement | null = null;
    const via = popped ? this.map.screens[popped]?.via : undefined;
    if (via) {
      const item = this.items[f.id];
      el = f.screen.querySelector<HTMLElement>(item != null
        ? `[data-row="${CSS.escape(via)}"][data-item="${item}"]` : `[data-row="${CSS.escape(via)}"]`);
    }
    el ??= f.screen.querySelector<HTMLElement>("[data-nav]") ?? f.screen.querySelector<HTMLElement>(ACTIVE);
    el?.focus({ preventScroll: true });
  }

  popTo(i: number): Promise<void> {
    if (i < 0 || i >= this.slots.length - 1) return Promise.resolve();
    if (this.transit.defer(() => void this.popTo(i))) return Promise.resolve();
    return this.go(i + 1, []);
  }

  /** One level up; on the root, Escape just lets go of the selection. */
  back() {
    if (this.transit.defer(() => this.back())) return;
    if (this.slots.length > 1) void this.popTo(this.slots.length - 2);
    else if (this.pick) this.clearPick();
  }

  /** Go to a screen (one transition from the current path) and optionally pick a row.
      Asked during a transition, it waits for the end; only the last such request runs. */
  async goTo(target: string[], pick?: { row: string; item?: number }) {
    if (this.transit.defer(() => void this.goTo(target, pick))) return;
    const gen = this.gen;
    if (target[0] !== this.slots[0]?.id) this.reset([target[0]], {}, null);
    let k = 0;
    while (k < target.length && k < this.slots.length && this.slots[k].id === target[k]) k++;
    // A list screen the path walks through shows its first item unless one is already chosen.
    for (let j = Math.max(k, 1); j < target.length; j++) {
      const parent = target[j - 1];
      const via = this.map.screens[target[j]]?.via;
      if (parent && via && this.rm.rowDef(parent, via)?.bind?.kind === "list" && this.items[parent] == null) this.items[parent] = 0;
    }
    await this.go(k, target.slice(k));
    if (gen !== this.gen) return;
    if (pick) this.select(target[target.length - 1], pick.row, pick.item);
  }

  /** Pick a row (or a piece of chrome, `@id`) on the front screen. */
  select(screen: string, row: string, item?: number) {
    const f = this.front();
    if (!f || f.id !== screen) return;
    const key = item != null ? `${row}@${item}` : row;
    const prev = this.pick;
    this.pick = { screen, row, key, item };
    if (item != null && !this.rowEl(key)) this.draw(f);
    const el = this.rowEl(key);
    // A stale link (a row this config does not draw) picks nothing.
    if (!el) { this.pick = prev; return; }
    this.marks();
    const sc = f.screen.querySelector<HTMLElement>(".scroll");
    if (el && sc && sc.contains(el)) {
      // Keep the picked row clear of the nav bar and tab bar; centre it when it is off screen.
      const r = el.getBoundingClientRect(), b = sc.getBoundingClientRect();
      if (r.top < b.top + 120 * this.S || r.bottom > b.bottom - 110 * this.S) {
        sc.scrollTo({ top: Math.max(0, sc.scrollTop + (r.top - b.top) / this.S - H / 2 + 30), behavior: this.dur ? "smooth" : "auto" });
      }
    }
    this.ev.onPick(this.pick);
  }

  clearPick() {
    this.pick = null;
    this.marks();
    this.ev.onPick(null);
  }

  private onClick = (e: MouseEvent) => {
    const t = e.target as HTMLElement;
    const slotEl = t.closest<HTMLElement>(".slot");
    if (!slotEl) return;
    const onFront = () => slotEl === this.front()?.el;
    const now = tapWhile(this.transit.phase, onFront());
    // A tap on the screen that is arriving waits for it, and still has to land on the front screen then.
    if (now === "wait") this.transit.defer(() => { if (onFront()) this.tap(t); });
    else if (now === "now") this.tap(t);
  };

  private tap(t: HTMLElement) {
    const slotEl = t.closest<HTMLElement>(".slot");
    const i = this.slots.findIndex((s) => s.el === slotEl);
    if (i < 0) return;
    if (i < this.slots.length - 1) { void this.popTo(i); return; }
    const f = this.front();
    const rootEl = t.closest<HTMLElement>("[data-root]");
    if (rootEl) {
      const id = rootEl.dataset.root!;
      if (id !== this.slots[0]?.id) {
        const refocus = this.host.contains(document.activeElement);
        this.reset([id], {}, null);
        if (refocus) this.front()?.screen.querySelector<HTMLElement>(`[data-root="${CSS.escape(id)}"]`)?.focus({ preventScroll: true });
      }
      return;
    }
    if (t.closest("[data-nav]")) { void this.popTo(this.slots.length - 2); return; }
    // The app's own chrome (启动, tabs, nav buttons) picks like a row: it explains itself, nothing opens.
    const r = t.closest<HTMLElement>("[data-shell], .row");
    if (!r) return;
    const item = r.dataset.item != null ? Number(r.dataset.item) : undefined;
    if (r.dataset.to) {
      if (item != null) this.items[f.id] = item;
      else delete this.items[f.id];
      void this.go(this.slots.length, [r.dataset.to], r);
      return;
    }
    if (this.pick?.key === r.dataset.key) this.clearPick();
    else this.select(f.id, r.dataset.row!, item);
  }

  private onKey = (e: KeyboardEvent) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const t = e.target as HTMLElement;
    if (t.classList.contains("pane") || t.getAttribute("role") === "button") { e.preventDefault(); t.click(); }
  };

  /** Escape anywhere on the page steps back, unless a field, a dialog or a menu owns it. */
  private onDocKey = (e: KeyboardEvent) => {
    if (e.key !== "Escape" || e.defaultPrevented || e.isComposing || !this.host.isConnected) return;
    const t = e.target as HTMLElement | null;
    if (t?.closest?.("input,textarea,select,[contenteditable]:not([contenteditable='false'])")) return;
    if (overlayOpen(this.host)) return;
    if (this.slots.length < 2 && !this.pick && !this.transit.busy) return;
    e.preventDefault();
    this.back();
  };
}
