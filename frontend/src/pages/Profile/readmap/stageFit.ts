/* The stage's geometry from two numbers the stage itself never changes: the page's width and the height left
   for it in the window. The frame the result sizes sits inside the page and is never wider than it, so
   measuring the page again after a fit gives the same answer. */

/** Deck ↔ reading column. */
export const GAP = 32;
export const MIN_READ = 360;
export const MAX_READ = 880;
/** Below this page width the phone goes above the 原文. */
export const SIDE_BY_SIDE_FROM = 760;
/** The phone's scale never goes above 0.9, nor below where its 17pt body text drops under 12px. */
export const STACK_MAX = 0.9;
export const STACK_MIN = 12 / 17;

/** The deck's size at scale S; both grow in a straight line with S. */
export interface DeckSize { width(S: number): number; height(S: number): number }

export interface StageGeo { S: number; deckW: number; readW: number; h: number; stacked: boolean }

export function fitStage(pageW: number, availH: number, deck: DeckSize): StageGeo {
  const fits = (S: number) => pageW - deck.width(S) - GAP >= MIN_READ;
  let stacked = pageW < SIDE_BY_SIDE_FROM;
  let S = 0;
  if (!stacked) {
    // Side by side the phone follows the visible height, down to the 12px floor and no further:
    // a shorter window scrolls the page instead. Width only takes it to the same floor.
    const fill = (availH - deck.height(0)) / (deck.height(1) - deck.height(0));
    S = Math.max(STACK_MIN, Math.min(STACK_MAX, fill));
    while (S > STACK_MIN && !fits(S)) S = Math.max(STACK_MIN, S - 0.01);
    if (!fits(S)) stacked = true;
  }
  if (stacked) {
    // By width: the phone is the page here. Below the 12px floor only when the page itself is narrower.
    S = Math.min(STACK_MAX, pageW / deck.width(1));
    if (S < STACK_MIN && deck.width(STACK_MIN) <= pageW) S = STACK_MIN;
  }
  const deckW = deck.width(S);
  return {
    S, deckW, stacked,
    h: stacked ? Math.round(availH) : Math.round(deck.height(S)),
    readW: stacked ? pageW : Math.min(MAX_READ, pageW - deckW - GAP),
  };
}

/** The frame's width side by side: the deck, the gap and the reading column. Stacked, the frame takes the page. */
export const frameWidth = (g: StageGeo) => (g.stacked ? null : g.deckW + GAP + g.readW);

export const sameGeo = (a: StageGeo | null, b: StageGeo) =>
  !!a && a.S === b.S && a.deckW === b.deckW && a.readW === b.readW && a.h === b.h && a.stacked === b.stacked;
