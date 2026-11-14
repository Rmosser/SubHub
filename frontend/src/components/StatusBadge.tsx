import { AnimatePresence, motion } from "motion/react";
import { SPRING_SNAPPY, REDUCED_INSTANT, useMotionReady } from "@/motion";

// 全站唯一的状态写法：一个小点加一句短语。正常是刻字（常规字重），要人处理的用琥珀或红，点在呼吸；
// 停用与等待是空心点。不用实心彩色徽章，也不用图标。
export type StatusKind = "success" | "error" | "warning" | "info" | "stopped" | "pending" | "loading" | "in-progress";

export type StatusTone = "ok" | "amber" | "red" | "info" | "idle" | "busy";

const TONE: Record<StatusKind, StatusTone> = {
  success: "ok",
  error: "red",
  warning: "amber",
  info: "info",
  stopped: "idle",
  pending: "idle",
  loading: "busy",
  "in-progress": "busy",
};

interface StatusBadgeProps {
  status?: StatusKind;
  tone?: StatusTone;
  children: React.ReactNode;
  className?: string;
}

export function StatusDot({ tone }: { tone: StatusTone }) {
  return <i className={`s-dot ${tone}`} aria-hidden="true" />;
}

export function StatusBadge({ status = "info", tone, children, className }: StatusBadgeProps) {
  const { shouldAnimate } = useMotionReady();
  const resolved = tone ?? TONE[status] ?? "info";

  return (
    <AnimatePresence mode="popLayout" initial={false}>
      <motion.span
        key={resolved}
        className={["s-status", resolved, className ?? ""].filter(Boolean).join(" ")}
        initial={shouldAnimate ? { opacity: 0 } : undefined}
        animate={{ opacity: 1 }}
        exit={shouldAnimate ? { opacity: 0 } : undefined}
        transition={shouldAnimate ? SPRING_SNAPPY : REDUCED_INSTANT}
      >
        <StatusDot tone={resolved} />
        <span className="s-status-text">{children}</span>
      </motion.span>
    </AnimatePresence>
  );
}
