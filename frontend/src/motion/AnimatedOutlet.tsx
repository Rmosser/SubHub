import { useOutlet, useLocation } from "react-router-dom";
import { useScenario } from "@/contexts/ScenarioContext";
import { AnimatePresence, motion } from "motion/react";
import { SLIDE_UP, REDUCED_FADE, SPRING_DEFAULT, REDUCED_INSTANT } from "./tokens";
import { useMotionReady } from "./useMotionReady";

export function AnimatedOutlet() {
  const location = useLocation();
  const outlet = useOutlet();
  const { selectedScenarioId } = useScenario();
  const { shouldAnimate } = useMotionReady();

  const variants = shouldAnimate ? SLIDE_UP : REDUCED_FADE;
  const transition = shouldAnimate ? SPRING_DEFAULT : REDUCED_INSTANT;

  return (
    <AnimatePresence key={selectedScenarioId} mode="wait">
      <motion.div
        key={location.pathname}
        initial={variants.initial}
        animate={variants.animate}
        exit={variants.exit}
        transition={transition}
      >
        {outlet}
      </motion.div>
    </AnimatePresence>
  );
}
