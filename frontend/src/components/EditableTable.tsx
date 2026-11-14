import { useReducer } from "react";
import {
  Table,
  Button,
  Input,
  Toggle,
  Select,
  SelectProps,
  TableProps,
} from "@cloudscape-design/components";
import { useLocale } from "@/contexts/LocaleContext";
import { Section } from "./Section";
import { ErrorNote } from "./ErrorNote";
import { IconButton } from "./InlineAction";
import { editableTableReducer, initialEditableTableState } from "./editableTableState";

export interface EditableColumn<T> {
  id: string;
  header: string;
  width?: number;
  editType?: "text" | "number" | "toggle" | "select";
  selectOptions?: SelectProps.Option[];
  cell: (item: T) => React.ReactNode;
  editCell?: (item: T, value: unknown, onChange: (val: unknown) => void, disabled: boolean) => React.ReactNode;
}

interface EditableTableProps<T extends { id?: string }> {
  items: T[];
  columns: EditableColumn<T>[];
  header: string;
  loading?: boolean;
  onSave: (items: T[]) => Promise<T[]>;
  validateItems?: (items: T[]) => string | undefined;
  saving?: boolean;
  onAddRow?: () => T;
  onDeleteRow?: (item: T) => void;
}

export function EditableTable<T extends { id?: string }>({
  items: initialItems,
  columns,
  header,
  loading,
  onSave,
  saving,
  onAddRow,
  onDeleteRow,
  validateItems,
}: EditableTableProps<T>) {
  const { t } = useLocale();
  const [state, dispatch] = useReducer(editableTableReducer<T>, initialItems, initialEditableTableState<T>);
  const { items: editedItems, dirty } = state;
  const isSaving = state.saving || saving;

  // Sync when initial items change and not dirty
  if (initialItems !== state.serverItems) {
    dispatch({ type: "server", items: initialItems });
  }

  const updateItem = (index: number, key: string, value: unknown) => {
    const next = [...editedItems];
    next[index] = { ...next[index], [key]: value };
    dispatch({ type: "edit", items: next });
  };

  const handleSave = async () => {
    if (isSaving) return;
    const error = validateItems?.(editedItems);
    if (error) {
      dispatch({ type: "failed", error });
      return;
    }
    dispatch({ type: "saving" });
    try {
      const savedItems = await onSave(editedItems);
      dispatch({ type: "saved", items: savedItems });
    } catch (error) {
      dispatch({ type: "failed", error: error instanceof Error ? error.message : t("toast.save_error") });
    }
  };

  const handleAdd = () => {
    if (onAddRow) {
      dispatch({ type: "edit", items: [...editedItems, onAddRow()] });
    }
  };

  const handleDelete = (index: number) => {
    const item = editedItems[index];
    dispatch({ type: "edit", items: editedItems.filter((_, i) => i !== index) });
    onDeleteRow?.(item);
  };

  const columnDefs: TableProps.ColumnDefinition<T>[] = columns.map((col) => ({
    id: col.id,
    header: col.header,
    width: col.width,
    cell: (item: T) => {
      const index = editedItems.indexOf(item);
      if (col.editCell) {
        return col.editCell(item, (item as Record<string, unknown>)[col.id], (val) =>
          updateItem(index, col.id, val), Boolean(isSaving),
        );
      }
      if (col.editType === "toggle") {
        return (
          <Toggle
            ariaLabel={`${col.header} ${index + 1}`}
            disabled={isSaving}
            checked={!!(item as Record<string, unknown>)[col.id]}
            onChange={({ detail }) => updateItem(index, col.id, detail.checked)}
          />
        );
      }
      if (col.editType === "select" && col.selectOptions) {
        const val = String((item as Record<string, unknown>)[col.id] ?? "");
        return (
          <Select
            ariaLabel={`${col.header} ${index + 1}`}
            selectedOption={col.selectOptions.find((o) => o.value === val) || (val ? { value: val, label: val } : null)}
            options={col.selectOptions}
            disabled={isSaving}
            onChange={({ detail }) => updateItem(index, col.id, detail.selectedOption.value)}
          />
        );
      }
      if (col.editType === "number") {
        return (
          <Input
            ariaLabel={`${col.header} ${index + 1}`}
            type="number"
            disabled={isSaving}
            value={String((item as Record<string, unknown>)[col.id] ?? "")}
            onChange={({ detail }) => updateItem(index, col.id, Number(detail.value))}
          />
        );
      }
      if (col.editType === "text") {
        return (
          <Input
            ariaLabel={`${col.header} ${index + 1}`}
            disabled={isSaving}
            value={String((item as Record<string, unknown>)[col.id] ?? "")}
            onChange={({ detail }) => updateItem(index, col.id, detail.value)}
          />
        );
      }
      return col.cell(item);
    },
  }));

  // Add actions column
  columnDefs.push({
    id: "_actions",
    header: "",
    width: 60,
    cell: (item: T) => {
      const index = editedItems.indexOf(item);
      return (
        <IconButton iconName="remove" ariaLabel={`${t("common.delete")} ${index + 1}`} disabled={isSaving} onClick={() => handleDelete(index)} />
      );
    },
  });

  // 标题已由所在的标签页说过一次：这里只留动作，标题作为表格的可访问名称。
  return (
    <Section
      ariaLabel={header}
      actions={
        <>
          {onAddRow && <Button iconName="add-plus" onClick={handleAdd} disabled={isSaving}>{t("common.add")}</Button>}
          <Button variant="primary" onClick={handleSave} loading={isSaving} disabled={!dirty}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      {state.error ? <ErrorNote title={t("toast.save_error")} reason={state.error} /> : null}
      <Table
        items={editedItems}
        columnDefinitions={columnDefs}
        loading={loading}
        ariaLabels={{ tableLabel: header }}
        empty={<div className="s-empty">{t("common.no_items")}</div>}
      />
    </Section>
  );
}
