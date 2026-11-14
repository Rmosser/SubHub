import React from "react";
import { motion } from "motion/react";
import { FADE_SCALE_IN, SPRING_DEFAULT } from "@/motion";
import { t } from "@/i18n/translations";
import { isChunkLoadError } from "@/utils/chunkLoadError";
import { ErrorNote } from "./ErrorNote";

function ErrorContent({ error, onRetry }: { error: Error | null; onRetry: () => void }) {
  return (
    <motion.div initial={FADE_SCALE_IN.initial} animate={FADE_SCALE_IN.animate} transition={SPRING_DEFAULT} style={{ padding: "0 32px" }}>
      <ErrorNote page title={t("workspace.unexpected_error")} reason={error?.message} onRetry={onRetry} />
    </motion.div>
  );
}

interface Props {
  children: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <ErrorContent
          error={this.state.error}
          onRetry={() => {
            if (isChunkLoadError(this.state.error)) window.location.reload();
            else this.setState({ hasError: false, error: null });
          }}
        />
      );
    }
    return this.props.children;
  }
}
