/* Where the notes popover sits: under its chip, lined up with the chip's nearer side, never past the window. */

/** Widest the popover gets. */
export const POP_MAX = 440;
/** Room the popover's width leaves on each side of a narrow window. */
export const POP_SIDE = 16;
/** Least room kept between the popover and either side of the window. */
export const POP_EDGE = 8;

/**
 * The popover's left edge and width, in window pixels. A chip in the right half of the window gets its
 * right edge matched, one in the left half its left edge; either way the popover is then held inside
 * `[POP_EDGE, viewW - POP_EDGE]`.
 */
export function placePop(chipLeft: number, chipRight: number, viewW: number): { left: number; width: number } {
  const width = Math.max(0, Math.min(POP_MAX, viewW - 2 * POP_SIDE));
  const want = chipLeft + chipRight > viewW ? chipRight - width : chipLeft;
  const left = Math.max(POP_EDGE, Math.min(want, viewW - POP_EDGE - width));
  return { left, width };
}
