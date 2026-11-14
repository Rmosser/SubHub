import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "@/styles/fonts.css";
import "@/styles/animations.css";
import "@/styles/sonner-cloudscape.css";
import { MotionConfig } from "motion/react";
import { applyWorkbenchTheme } from "@/theme/workbench";
import { initThemePreference } from "@/theme/glassTheme";
import { ThemedToaster } from "@/components/ThemedToaster";
import "@/styles/workbench.css";
import "@/styles/surfaces.css";

applyWorkbenchTheme();
initThemePreference();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MotionConfig reducedMotion="user">
    <App />
    <ThemedToaster />
    </MotionConfig>
  </React.StrictMode>
);
