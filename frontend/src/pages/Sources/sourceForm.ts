export interface StandardSourceDraft {
  name: string;
  ingestKind: string;
  sourceMode: string;
  targetContractId: string;
  clashUrl: string;
  shadowrocketUrl: string;
  manualNodesText: string;
}

export function validateStandardSourceDraft(draft: StandardSourceDraft): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!draft.name.trim()) errors.name = "validation.required";
  if (draft.ingestKind === "manual_nodes") {
    if (!draft.manualNodesText.trim()) errors.manualNodesText = "validation.required";
  } else {
    if (!draft.clashUrl.trim()) errors.clashUrl = "validation.required";
    if (!draft.shadowrocketUrl.trim()) errors.shadowrocketUrl = "validation.required";
  }
  if ((draft.ingestKind === "manual_nodes" || draft.sourceMode === "route_contract") && !draft.targetContractId) {
    errors.targetContractId = "validation.required";
  }
  return errors;
}

export function resolvePullMode(mode: string): string {
  return mode || "direct_then_proxy";
}
