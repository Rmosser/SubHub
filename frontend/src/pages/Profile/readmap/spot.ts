/* Where the phone is, as the page shows it and as the address bar keeps it. Pure, so node can test it. */
import type { Pick } from "./stack";

/** The pick only counts while its screen is the one in front: a root switch or a pop leaves nothing behind. */
export function pickOnFront(pick: Pick | null, path: readonly string[]): Pick | null {
  const front = path[path.length - 1];
  return pick && front != null && pick.screen === front ? pick : null;
}

/** The `s` / `r` / `i` part of the address for a deck at `path`. */
export function spotOf(path: readonly string[], pick: Pick | null, root: string | undefined, items: Readonly<Record<string, number>>) {
  const p = pickOnFront(pick, path);
  const parent = path[path.length - 2];
  const item = p?.item ?? (parent != null ? items[parent] : undefined);
  return {
    s: path.length > 1 || (root != null && path[0] !== root) ? path[path.length - 1] : null,
    r: p?.row ?? null,
    i: item != null ? String(item) : null,
  };
}
