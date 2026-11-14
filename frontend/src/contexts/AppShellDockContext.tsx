import { createContext, useContext, type ReactNode } from "react";

// 玻璃外壳没有 masthead：固定工具栏贴在视口顶边。
export const APP_SHELL_TOP_NAV_HEIGHT = 0;
export const APP_SHELL_DOCK_TOP = 0;

interface AppShellDockContextValue {
  setDockContent: (content: ReactNode | null) => void;
}

const AppShellDockContext = createContext<AppShellDockContextValue>({
  setDockContent: () => {},
});

export const AppShellDockProvider = AppShellDockContext.Provider;

export function useAppShellDock() {
  return useContext(AppShellDockContext);
}
