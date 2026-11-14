import { useReducedMotion } from "motion/react";

export function useMotionReady() {
  const shouldReduceMotion = useReducedMotion();
  return { shouldAnimate: !shouldReduceMotion, shouldReduceMotion };
}
