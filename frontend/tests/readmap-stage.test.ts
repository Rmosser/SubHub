import assert from "node:assert/strict";
import test from "node:test";
import { PhoneStack } from "../src/pages/Profile/readmap/stack.ts";
import { MAX_READ, MIN_READ, SIDE_BY_SIDE_FROM, STACK_MAX, STACK_MIN, fitStage, frameWidth, sameGeo } from "../src/pages/Profile/readmap/stageFit.ts";

const near = (a: number, b: number, eps = 0.01) => assert.ok(Math.abs(a - b) <= eps, `${a} ≉ ${b}`);

test("side by side the phone follows the height and the reading column takes the rest of the page", () => {
  // 1440×900 window: the page is 1160 wide and leaves 788px for the stage.
  const g = fitStage(1160, 788, PhoneStack);
  assert.equal(g.stacked, false);
  near(g.S, (788 - 26) / 874, 1e-9);
  assert.equal(g.h, 788);
  near(g.readW, 1160 - PhoneStack.width(g.S) - 32);
  assert.equal(frameWidth(g), 1160);
  // Taller: the phone stops at 0.9. Wider: the reading column stops at its maximum and the frame is narrower than the page.
  assert.equal(fitStage(1160, 1400, PhoneStack).S, STACK_MAX);
  const wide = fitStage(1900, 788, PhoneStack);
  assert.equal(wide.readW, MAX_READ);
  assert.ok(frameWidth(wide)! < 1900);
  // Short: the 12px floor, and the page scrolls.
  assert.equal(fitStage(1160, 480, PhoneStack).S, STACK_MIN);
});

test("stacked the phone and the 原文 both take the page's width", () => {
  const g = fitStage(390, 700, PhoneStack);
  assert.equal(g.stacked, true);
  assert.equal(frameWidth(g), null);
  assert.equal(g.readW, 390);
  near(PhoneStack.width(g.S), 390);
  assert.equal(g.h, 700);
  assert.equal(fitStage(759, 700, PhoneStack).S, STACK_MAX);
  // Narrower than the deck at the floor: the deck follows the page below the floor.
  near(PhoneStack.width(fitStage(300, 700, PhoneStack).S), 300);
});

test("the frame never outgrows the page, and side by side starts at one width only", () => {
  for (let h = 480; h <= 1400; h += 37) {
    let flips = 0, last: boolean | null = null;
    for (let w = 280; w <= 2400; w += 3) {
      const g = fitStage(w, h, PhoneStack);
      assert.ok(g.deckW <= w + 1e-9, `${w}/${h}: deck ${g.deckW}`);
      assert.ok((frameWidth(g) ?? w) <= w + 1e-9, `${w}/${h}: frame ${frameWidth(g)}`);
      assert.equal(g.stacked, w < SIDE_BY_SIDE_FROM, `${w}/${h}`);
      if (!g.stacked) assert.ok(g.readW >= MIN_READ && g.readW <= MAX_READ, `${w}/${h}: read ${g.readW}`);
      assert.ok(g.S <= STACK_MAX && g.S > 0, `${w}/${h}: S ${g.S}`);
      if (last !== null && last !== g.stacked) flips++;
      last = g.stacked;
    }
    assert.equal(flips, 1, `height ${h}`);
  }
});

test("the same page gives the same stage, so a refit with nothing new changes nothing", () => {
  const a = fitStage(1160, 788, PhoneStack);
  assert.ok(sameGeo(a, fitStage(1160, 788, PhoneStack)));
  assert.ok(!sameGeo(a, fitStage(1161, 788, PhoneStack)));
  assert.ok(!sameGeo(null, a));
});
