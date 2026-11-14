export interface EditableTableState<T> {
  items: T[];
  serverItems: T[];
  dirty: boolean;
  saving: boolean;
  error: string;
}

export type EditableTableAction<T> =
  | { type: "server"; items: T[] }
  | { type: "edit"; items: T[] }
  | { type: "saving" }
  | { type: "saved"; items: T[] }
  | { type: "failed"; error: string };

export function initialEditableTableState<T>(items: T[]): EditableTableState<T> {
  return { items, serverItems: items, dirty: false, saving: false, error: "" };
}

export function editableTableReducer<T>(
  state: EditableTableState<T>,
  action: EditableTableAction<T>,
): EditableTableState<T> {
  switch (action.type) {
    case "server":
      return { ...state, serverItems: action.items, items: state.dirty ? state.items : action.items };
    case "edit":
      return state.saving ? state : { ...state, items: action.items, dirty: true, error: "" };
    case "saving":
      return { ...state, saving: true, error: "" };
    case "saved":
      return {
        ...state,
        // Use canonical mutation output, even if a subsequent readback fails.
        items: action.items,
        dirty: false,
        saving: false,
        error: "",
      };
    case "failed":
      return { ...state, saving: false, error: action.error };
  }
}
