// Editing state and copied links belong to the route and scenario that opened them.
export function workspaceScopeKey(pathname: string, scenarioId: string): string {
  return JSON.stringify([pathname, scenarioId]);
}
