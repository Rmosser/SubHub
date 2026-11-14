import React, { createContext, useCallback, useContext, useState } from "react";
import { useLocation } from "react-router-dom";
import { useScenario } from "@/contexts/ScenarioContext";
import { workspaceScopeKey } from "@/utils/workspaceScope";

interface SplitPanelState {
  isOpen: boolean;
  header: string;
  content: React.ReactNode;
  contentKey: string;
  scopeKey: string;
}

interface SplitPanelContextValue {
  splitPanel: SplitPanelState;
  openSplitPanel: (header: string, content: React.ReactNode) => void;
  closeSplitPanel: () => void;
}

const defaultState: SplitPanelState = {
  isOpen: false,
  header: "",
  content: null,
  contentKey: "0",
  scopeKey: "",
};

const SplitPanelContext = createContext<SplitPanelContextValue>({
  splitPanel: defaultState,
  openSplitPanel: () => {},
  closeSplitPanel: () => {},
});

export function SplitPanelProvider({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  const { selectedScenarioId } = useScenario();
  const scopeKey = workspaceScopeKey(pathname, selectedScenarioId);
  const [splitPanel, setSplitPanel] = useState<SplitPanelState>(defaultState);
  const [lastScopeKey, setLastScopeKey] = useState(scopeKey);
  if (lastScopeKey !== scopeKey) {
    setLastScopeKey(scopeKey);
    setSplitPanel(defaultState);
  }

  const openSplitPanel = useCallback((header: string, content: React.ReactNode) => {
    setSplitPanel({ isOpen: true, header, content, contentKey: String(Date.now()), scopeKey });
  }, [scopeKey]);

  const closeSplitPanel = useCallback(() => {
    setSplitPanel(defaultState);
  }, []);

  return (
    <SplitPanelContext.Provider value={{ splitPanel: splitPanel.scopeKey === scopeKey ? splitPanel : defaultState, openSplitPanel, closeSplitPanel }}>
      {children}
    </SplitPanelContext.Provider>
  );
}

export function useSplitPanel() {
  return useContext(SplitPanelContext);
}

// 详情抽屉面板的 id。触发按钮在抽屉打开时用 aria-controls 指向它（抽屉关着时不留悬空引用）
export const SPLIT_PANEL_ID = "s-detail-drawer";

export function useSplitPanelControls() {
  return useContext(SplitPanelContext).splitPanel.isOpen ? SPLIT_PANEL_ID : undefined;
}
