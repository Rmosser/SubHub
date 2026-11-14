import { useEffect, useRef, type RefObject } from "react";
import { mountGlass } from "./engine";

// 整个界面底下的一块玻璃。纯装饰，对辅助技术隐藏。
export function GlassBackdrop({ railRef }: { railRef: RefObject<HTMLElement> }) {
  const hostRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const host = hostRef.current, rail = railRef.current;
    if (!host || !rail) return;
    return mountGlass(host, rail);
  }, [railRef]);
  return <div ref={hostRef} className="glass-backdrop" aria-hidden="true" />;
}
