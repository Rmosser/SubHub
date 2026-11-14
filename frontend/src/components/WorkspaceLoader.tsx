import { Spinner } from "@cloudscape-design/components";
import { AnimatePresence, motion } from "motion/react";
import { t } from "@/i18n/translations";
import { FADE_SCALE_IN, REDUCED_FADE, SPRING_DEFAULT, REDUCED_INSTANT, useMotionReady } from "@/motion";
import { ErrorNote } from "./ErrorNote";

interface WorkspaceLoaderProps {
  loading: boolean;
  error?: Error | null;
  onRetry?: () => void;
  children: React.ReactNode;
}

export function WorkspaceLoader({ loading, error, onRetry, children }: WorkspaceLoaderProps) {
  const { shouldAnimate } = useMotionReady();
  const variants = shouldAnimate ? FADE_SCALE_IN : REDUCED_FADE;
  const transition = shouldAnimate ? SPRING_DEFAULT : REDUCED_INSTANT;

  const stateKey = loading ? "loading" : error ? "error" : "content";

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={stateKey}
        initial={variants.initial}
        animate={variants.animate}
        exit={variants.exit}
        transition={transition}
      >
        {loading ? (
          <div className="s-loading" role="status">
            <Spinner size="large" />
            <span>{t("workspace.loading.title")}</span>
          </div>
        ) : error ? (
          <ErrorNote page title={t("workspace.error.title")} reason={error.message} onRetry={onRetry} />
        ) : (
          <>{children}</>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
