import { useMemo, useSyncExternalStore } from "react";

// 媒体查询的外部仓库：订阅 change 事件，快照是当前是否匹配。没有 matchMedia（如服务端）时恒为 false。
interface QueryList {
  matches: boolean;
  addEventListener(type: "change", listener: () => void): void;
  removeEventListener(type: "change", listener: () => void): void;
}

interface QuerySource {
  matchMedia?: (query: string) => QueryList;
}

export function mediaQueryStore(query: string, source: QuerySource) {
  return {
    subscribe(onChange: () => void) {
      const list = source.matchMedia?.(query);
      if (!list) return () => {};
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    getSnapshot() {
      return source.matchMedia?.(query).matches ?? false;
    },
  };
}

export const COARSE_POINTER = "(pointer: coarse)";

export function useMediaQuery(query: string) {
  const store = useMemo(() => mediaQueryStore(query, typeof window === "undefined" ? {} : window), [query]);
  return useSyncExternalStore(store.subscribe, store.getSnapshot, () => false);
}

// 主指针是手指（触屏）时为 true
export function useCoarsePointer() {
  return useMediaQuery(COARSE_POINTER);
}
