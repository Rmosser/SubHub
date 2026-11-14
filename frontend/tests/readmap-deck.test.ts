import assert from "node:assert/strict";
import test from "node:test";
import { tapWhile, Transit, type Timers } from "../src/pages/Profile/readmap/transit.ts";
import { pickOnFront, spotOf } from "../src/pages/Profile/readmap/spot.ts";
import { drawnLines } from "../src/pages/Profile/readmap/lineWindow.ts";

/** A clock the test moves by hand. */
function fakeTimers() {
  let now = 0, next = 1;
  const due = new Map<number, { at: number; fn: () => void }>();
  const timers: Timers = {
    set: (fn, ms) => { const id = next++; due.set(id, { at: now + ms, fn }); return id; },
    clear: (id) => { due.delete(id); },
  };
  const advance = (ms: number) => {
    const end = now + ms;
    for (;;) {
      const [id, t] = [...due.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at || a[0] - b[0])[0] ?? [];
      if (id == null || !t) break;
      due.delete(id);
      now = t.at;
      t.fn();
    }
    now = end;
  };
  return { timers, advance, pending: () => due.size };
}

/** One deck move the way PhoneStack makes it: a pressed beat, a 450ms slide, an end. */
function move(tr: Transit, log: string[], beat = 90, ms = 450) {
  tr.start(beat, () => { log.push("run"); return { ms, end: (cut) => log.push(cut ? "cut" : "end") }; }, () => log.push("drop"));
}

test("a move runs after its pressed beat and ends on time", () => {
  const { timers, advance } = fakeTimers();
  const tr = new Transit(timers), log: string[] = [];
  move(tr, log);
  assert.equal(tr.phase, "pressed");
  advance(90);
  assert.equal(tr.phase, "running");
  advance(450);
  assert.deepEqual(log, ["run", "end"]);
  assert.equal(tr.busy, false);
});

test("reduced motion switched on inside the pressed beat still finishes the move (#32)", () => {
  const { timers, advance } = fakeTimers();
  const tr = new Transit(timers), log: string[] = [];
  move(tr, log);
  advance(40);
  tr.settle();
  assert.deepEqual(log, ["run", "end"]);
  assert.equal(tr.busy, false, "the deck takes taps again");
  // And the next tap is not swallowed by a queue that never drains.
  let tapped = 0;
  assert.equal(tr.defer(() => tapped++), false);
  advance(1000);
  assert.equal(tapped, 0);
});

test("settle mid-slide ends the move once, then the queued request runs", () => {
  const { timers, advance } = fakeTimers();
  const tr = new Transit(timers), log: string[] = [];
  move(tr, log);
  advance(200);
  assert.equal(tr.defer(() => log.push("queued")), true);
  tr.settle();
  advance(1000);
  assert.deepEqual(log, ["run", "end", "queued"]);
});

test("during a move only the last request runs, once", () => {
  const { timers, advance } = fakeTimers();
  const tr = new Transit(timers), log: string[] = [];
  move(tr, log);
  tr.defer(() => log.push("a"));
  tr.defer(() => log.push("b"));
  advance(2000);
  assert.deepEqual(log, ["run", "end", "b"]);
});

test("a load cuts the move: no follow-ups, the queue is forgotten", () => {
  const { timers, advance, pending } = fakeTimers();
  const tr = new Transit(timers), log: string[] = [];
  move(tr, log);
  tr.abort();
  assert.deepEqual(log, ["drop"], "a load inside the beat only lets go of the pressed row");
  move(tr, log);
  advance(200);
  tr.defer(() => log.push("queued"));
  tr.abort();
  advance(2000);
  assert.deepEqual(log, ["drop", "run", "cut"]);
  assert.equal(tr.busy, false);
  assert.equal(pending(), 0);
});

test("a second tap inside the pressed beat is dropped, not queued against the screen that is leaving (#23)", () => {
  assert.equal(tapWhile("idle", true), "now");
  assert.equal(tapWhile("pressed", true), "drop");
  assert.equal(tapWhile("running", true), "wait");
  assert.equal(tapWhile("running", false), "drop");
});

test("a 40ms double tap pushes once", () => {
  const { timers, advance } = fakeTimers();
  const tr = new Transit(timers), log: string[] = [];
  // The deck as it stands: the tapped row's screen is in front until the move runs.
  let front = "home";
  const tap = () => {
    const now = tapWhile(tr.phase, true);
    if (now === "now") tr.start(90, () => { front = "child"; log.push("push"); return { ms: 450, end: () => {} }; }, () => {});
    else if (now === "wait") tr.defer(() => log.push(`tap on ${front}`));
  };
  tap();
  advance(40);
  tap();
  advance(2000);
  assert.deepEqual(log, ["push"]);
  assert.equal(front, "child");
});

test("a pick only counts on the screen in front (#22)", () => {
  const pick = { screen: "tab-home", row: "@tab:activity", key: "@tab:activity" };
  assert.equal(pickOnFront(pick, ["tab-home"]), pick);
  assert.equal(pickOnFront(pick, ["tab-config"]), null, "a root switch leaves nothing behind");
  assert.equal(pickOnFront(pick, ["tab-home", "home-groups"]), null);
  assert.equal(pickOnFront(pick, []), null);
});

test("the address keeps no row once the deck has moved on (#22)", () => {
  const pick = { screen: "tab-home", row: "proxy", key: "proxy@2", item: 2 };
  assert.deepEqual(spotOf(["tab-home"], pick, "tab-home", {}), { s: null, r: "proxy", i: "2" });
  assert.deepEqual(spotOf(["tab-config"], pick, "tab-home", {}), { s: "tab-config", r: null, i: null });
  assert.deepEqual(spotOf(["tab-home", "node"], null, "tab-home", { "tab-home": 3 }), { s: "node", r: null, i: "3" });
});

test("the roving tab stop is drawn even far outside the window (#32)", () => {
  const near = drawnLines(100, 900, 0, 400, 20, 20, 105);
  assert.equal(near[0], 100);
  assert.equal(near.at(-1), 139);
  const below = drawnLines(100, 900, 0, 400, 20, 20, 700);
  assert.ok(below.includes(700));
  assert.equal(below.at(-1), 700);
  const above = drawnLines(100, 900, 10000, 400, 20, 20, 101);
  assert.equal(above[0], 101);
  assert.ok(above.slice(1).every((i) => i >= 580));
  assert.deepEqual(drawnLines(100, 900, 0, 400, 20, 20, 2000), drawnLines(100, 900, 0, 400, 20, 20, null), "a stop from another section draws nothing");
});
