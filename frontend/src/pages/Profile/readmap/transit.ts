/* The deck's clock: one transition at a time — a short pressed beat, the move, its end. A request made
   meanwhile waits for the end, and only the last one runs. No DOM here, so node can drive it with fake timers. */

export interface Timers {
  set(fn: () => void, ms: number): number;
  clear(id: number): void;
}

export const windowTimers: Timers = {
  set: (fn, ms) => window.setTimeout(fn, ms),
  clear: (id) => window.clearTimeout(id),
};

export type Phase = "idle" | "pressed" | "running";

export interface Move {
  /** How long the move runs before it ends by itself. */
  ms: number;
  /** `cut`: a new load took over, so the end only tidies up. */
  end(cut: boolean): void;
}

/** What a tap does while the deck moves. In the pressed beat it is the second half of a double tap; during the
    move, a tap on the arriving screen waits for the end and one on a screen that is leaving is dropped. */
export function tapWhile(phase: Phase, onFront: boolean): "now" | "wait" | "drop" {
  if (phase === "idle") return "now";
  if (phase === "pressed" || !onFront) return "drop";
  return "wait";
}

export class Transit {
  private _phase: Phase = "idle";
  private timer = 0;
  private drainTimer = 0;
  private launch: (() => void) | null = null;
  private drop: (() => void) | null = null;
  private stop: ((cut: boolean) => void) | null = null;
  private queued: (() => void) | null = null;

  constructor(private t: Timers = windowTimers) {}

  get phase() { return this._phase; }
  get busy() { return this._phase !== "idle"; }

  /** Start a transition. After `beat` ms (0: at once) `run` lays out the move and says how long it takes.
      `drop` undoes the beat if a load cuts in before the move starts. */
  start(beat: number, run: () => Move, drop: () => void) {
    this.halt();
    // A newer transition replaces a request still waiting for the last one's end.
    this.cancelDrain();
    this.queued = null;
    this._phase = "pressed";
    this.drop = drop;
    this.launch = () => {
      this.clearTimer();
      this.launch = null;
      this.drop = null;
      this._phase = "running";
      const m = run();
      let ended = false;
      this.stop = (cut) => {
        if (ended) return;
        ended = true;
        this.clearTimer();
        this.stop = null;
        this._phase = "idle";
        m.end(cut);
        // The caller's own follow-up (a pick after goTo) resolves first; then the queued request runs.
        if (!cut) this.drainTimer = this.t.set(() => { this.drainTimer = 0; this.drain(); }, 0);
      };
      this.timer = this.t.set(() => this.stop?.(false), m.ms);
    };
    if (beat > 0) this.timer = this.t.set(() => this.launch?.(), beat);
    else this.launch();
  }

  /** Finish now (reduced motion switched on): a pending beat launches at once, and the move ends with it. */
  settle() {
    this.launch?.();
    this.stop?.(false);
  }

  /** A new load: end whatever runs without its follow-ups, and forget the queued request. */
  abort() {
    this.queued = null;
    this.cancelDrain();
    this.halt();
  }

  /** Asked while busy: keep it for the end (the last one wins). Says whether it was kept. */
  defer(fn: () => void): boolean {
    if (!this.busy) return false;
    this.queued = fn;
    return true;
  }

  private halt() {
    this.clearTimer();
    const drop = this._phase === "pressed" ? this.drop : null;
    this.launch = null;
    this.drop = null;
    this.stop?.(true);
    this._phase = "idle";
    drop?.();
  }

  private drain() {
    if (this.busy) return;
    const q = this.queued;
    this.queued = null;
    q?.();
  }

  private cancelDrain() {
    if (this.drainTimer) this.t.clear(this.drainTimer);
    this.drainTimer = 0;
  }

  private clearTimer() {
    if (this.timer) this.t.clear(this.timer);
    this.timer = 0;
  }
}
