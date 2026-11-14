import { useLayoutEffect, useRef, useState } from "react";
import { useLocale } from "@/contexts/LocaleContext";

// 原因写在所属条目下方：短的一行原样显示，长的限高并可展开。
interface ReasonTextProps {
  text: string;
  lines?: number;
  className?: string;
}

export function ReasonText({ text, lines = 2, className }: ReasonTextProps) {
  const { t } = useLocale();
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [overflowing, setOverflowing] = useState(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || open) return;
    const check = () => setOverflowing(el.scrollHeight > el.clientHeight + 1);
    check();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text, open, lines]);

  return (
    <div className={["s-reason", className ?? ""].filter(Boolean).join(" ")}>
      <div ref={ref} className={`s-reason-text${open ? "" : " clamp"}`} style={open ? undefined : { WebkitLineClamp: lines }}>
        {text}
      </div>
      {overflowing || open ? (
        <button type="button" className="s-reason-toggle" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          {open ? t("common.collapse") : t("common.expand")}
        </button>
      ) : null}
    </div>
  );
}
