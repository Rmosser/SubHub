import assert from "node:assert/strict";
import test from "node:test";
import { COARSE_POINTER, mediaQueryStore } from "../src/hooks/useMediaQuery";

function fakeMedia(initial: boolean) {
  const listeners = new Set<() => void>();
  const list = {
    matches: initial,
    addEventListener: (_type: "change", listener: () => void) => { listeners.add(listener); },
    removeEventListener: (_type: "change", listener: () => void) => { listeners.delete(listener); },
  };
  const queries: string[] = [];
  return {
    source: { matchMedia: (query: string) => { queries.push(query); return list; } },
    change(next: boolean) { list.matches = next; listeners.forEach((listener) => listener()); },
    listeners,
    queries,
  };
}

test("the snapshot follows the media query, so column resizing turns off on touch and back on with a mouse", () => {
  const media = fakeMedia(false);
  const store = mediaQueryStore(COARSE_POINTER, media.source);
  assert.equal(store.getSnapshot(), false);
  let notified = 0;
  const unsubscribe = store.subscribe(() => { notified += 1; });
  media.change(true);
  assert.equal(notified, 1);
  assert.equal(store.getSnapshot(), true);
  media.change(false);
  assert.equal(notified, 2);
  assert.equal(store.getSnapshot(), false);
  assert.deepEqual([...new Set(media.queries)], ["(pointer: coarse)"]);
  unsubscribe();
  assert.equal(media.listeners.size, 0);
});

test("without matchMedia the query never matches and subscribing is a no-op", () => {
  const store = mediaQueryStore(COARSE_POINTER, {});
  assert.equal(store.getSnapshot(), false);
  const unsubscribe = store.subscribe(() => assert.fail("should not be called"));
  unsubscribe();
});
