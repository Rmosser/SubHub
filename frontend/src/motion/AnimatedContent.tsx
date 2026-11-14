import { AnimatePresence, motion } from "motion/react";
import {
  FADE_SCALE_IN,
  SLIDE_UP,
  SLIDE_RIGHT,
  REDUCED_FADE,
  SPRING_DEFAULT,
  SPRING_SNAPPY,
  REDUCED_INSTANT,
} from "./tokens";
import { useMotionReady } from "./useMotionReady";

const VARIANT_MAP = {
  fadeScale: FADE_SCALE_IN,
  slideUp: SLIDE_UP,
  slideRight: SLIDE_RIGHT,
} as const;

interface AnimatedContentProps {
  show: boolean;
  variant?: keyof typeof VARIANT_MAP;
  contentKey?: string;
  snappy?: boolean;
  children: React.ReactNode;
}

export function AnimatedContent({
  show,
  variant = "fadeScale",
  contentKey,
  snappy = false,
  children,
}: AnimatedContentProps) {
  const { shouldAnimate } = useMotionReady();
  const variants = shouldAnimate ? VARIANT_MAP[variant] : REDUCED_FADE;
  const transition = shouldAnimate
    ? snappy
      ? SPRING_SNAPPY
      : SPRING_DEFAULT
    : REDUCED_INSTANT;

  return (
    <AnimatePresence mode="wait">
      {show && (
        <motion.div
          key={contentKey}
          initial={variants.initial}
          animate={variants.animate}
          exit={variants.exit}
          transition={transition}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
