import { isRecord } from "@/api/validators/shared";

export function scenarioCreateRequestToken(state: unknown, inScenarioSection: boolean): number {
  if (!inScenarioSection || !isRecord(state) || state.scenarioAction !== "create") return 0;
  return typeof state.scenarioNavNonce === "number" && Number.isFinite(state.scenarioNavNonce) ? state.scenarioNavNonce : 0;
}

export function withoutScenarioCreateRequest(state: unknown): unknown {
  if (!isRecord(state) || state.scenarioAction !== "create") return state;
  const nextState = { ...state };
  delete nextState.scenarioAction;
  delete nextState.scenarioNavNonce;
  return Object.keys(nextState).length ? nextState : null;
}
