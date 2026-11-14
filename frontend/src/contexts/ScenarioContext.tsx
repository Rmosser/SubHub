import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useScenarios } from "@/api/queries";
import type { ScenarioProfile } from "@/types";

const DEFAULT_SCENARIO_ID = "scenario-default";
const STORAGE_KEY = "subhub:selected-scenario-id";

export function resolveScenarioSelection<T extends { id: string; enabled: boolean }>(
  requestedScenarioId: string,
  scenarios: readonly T[],
  isLoading: boolean,
): {
  requestedScenario: T | null;
  selectedScenario: T | null;
  selectedScenarioId: string;
  selectionIssue: "missing" | "disabled" | null;
} {
  const requestedScenario = scenarios.find((item) => item.id === requestedScenarioId) || null;
  const selectedScenario = requestedScenario?.enabled ? requestedScenario : null;
  const selectionIssue: "missing" | "disabled" | null = isLoading
    ? null
    : selectedScenario
      ? null
      : requestedScenario
        ? "disabled"
        : "missing";

  return {
    requestedScenario,
    selectedScenario,
    // Preserve the requested id as the query boundary. Consumers can stop
    // rendering on selectionIssue instead of reading another scenario.
    selectedScenarioId: requestedScenarioId,
    selectionIssue,
  };
}

interface ScenarioContextValue {
  requestedScenarioId: string;
  requestedScenario: ScenarioProfile | null;
  selectedScenarioId: string;
  selectedScenario: ScenarioProfile | null;
  enabledScenarios: ScenarioProfile[];
  hasSelectionMismatch: boolean;
  selectionIssue: "missing" | "disabled" | null;
  isLoading: boolean;
  error: Error | null;
  setSelectedScenarioId: (scenarioId: string) => void;
}

const ScenarioContext = createContext<ScenarioContextValue | undefined>(undefined);

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const scenarios = useScenarios();
  const [requestedScenarioId, setRequestedScenarioIdState] = useState(() => {
    if (typeof window === "undefined") {
      return DEFAULT_SCENARIO_ID;
    }
    return window.localStorage.getItem(STORAGE_KEY) || DEFAULT_SCENARIO_ID;
  });

  const enabledScenarios = useMemo(
    () => (scenarios.data ?? []).filter((item) => item.enabled),
    [scenarios.data],
  );

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(STORAGE_KEY, requestedScenarioId);
  }, [requestedScenarioId]);

  // Keep the requested id as the query boundary.  An invalid or disabled
  // selection is observable through selectionIssue; it must not silently
  // switch the user to the default or first enabled scenario.
  const {
    requestedScenario,
    selectedScenario,
    selectedScenarioId,
    selectionIssue,
  } = resolveScenarioSelection(requestedScenarioId, scenarios.data ?? [], scenarios.isLoading);
  const hasSelectionMismatch = selectionIssue !== null;

  const value = useMemo<ScenarioContextValue>(
    () => ({
      requestedScenarioId,
      requestedScenario,
      selectedScenarioId,
      selectedScenario,
      enabledScenarios,
      hasSelectionMismatch,
      selectionIssue,
      isLoading: scenarios.isLoading,
      error: (scenarios.error as Error | null) ?? null,
      setSelectedScenarioId: (scenarioId: string) => setRequestedScenarioIdState(scenarioId.trim()),
    }),
    [
      enabledScenarios,
      hasSelectionMismatch,
      requestedScenario,
      requestedScenarioId,
      scenarios.error,
      scenarios.isLoading,
      selectedScenario,
      selectedScenarioId,
      selectionIssue,
    ],
  );

  return <ScenarioContext.Provider value={value}>{children}</ScenarioContext.Provider>;
}

export function useScenario() {
  const value = useContext(ScenarioContext);
  if (!value) {
    throw new Error("useScenario must be used within ScenarioProvider");
  }
  return value;
}
