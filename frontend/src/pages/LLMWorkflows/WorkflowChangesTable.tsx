import { Checkbox, Table } from "@cloudscape-design/components";
import { Chip } from "@/components/Chip";
import { useLocale } from "@/contexts/LocaleContext";
import type { LlmWorkflowChange, LlmWorkflowId } from "@/types";

interface WorkflowChangesTableProps {
  workflowType: LlmWorkflowId;
  changes: LlmWorkflowChange[];
  selectedChangeIds: string[];
  onToggle: (changeId: string) => void;
}

interface DisplayChange {
  change_id: string;
  type: string;
  subject: string;
  from: string;
  to: string;
  note: string;
}

function fallbackText(value: string, emptyLabel: string) {
  return value || emptyLabel;
}

export function WorkflowChangesTable({
  workflowType,
  changes,
  selectedChangeIds,
  onToggle,
}: WorkflowChangesTableProps) {
  const { t } = useLocale();
  const emptyValue = t("llm.empty_value");
  const isSelected = (changeId: string) => selectedChangeIds.includes(changeId);

  const displayChanges: DisplayChange[] = changes.map((item) => {
    if (workflowType === "directness") {
      return {
        change_id: item.change_id,
        type: t("llm.change_type.directness"),
        subject: item.name,
        from: fallbackText(item.from_directness, emptyValue),
        to: fallbackText(item.to_directness, emptyValue),
        note: [item.confidence, item.reason].filter(Boolean).join(" | "),
      };
    }

    if (workflowType === "routing") {
      return {
        change_id: item.change_id,
        type: t("llm.change_type.routing"),
        subject: item.name,
        from: fallbackText(item.from_display_name || item.from_contract_id, emptyValue),
        to: fallbackText(item.to_display_name || item.to_contract_id, emptyValue),
        note: item.current_effective_directness
          ? `${t("llm.current_directness")}: ${item.current_effective_directness}`
          : "",
      };
    }

    switch (item.type) {
      case "create_group":
        return {
          change_id: item.change_id,
          type: t("llm.change_type.create_group"),
          subject: item.group_name,
          from: emptyValue,
          to: fallbackText(item.mode, emptyValue),
          note: item.to_description,
        };
      case "update_group":
        return {
          change_id: item.change_id,
          type: t("llm.change_type.update_group"),
          subject: item.group_name,
          from: fallbackText(item.from_mode, emptyValue),
          to: fallbackText(item.to_mode, emptyValue),
          note: [item.from_description, item.to_description].filter(Boolean).join(" -> "),
        };
      case "delete_group":
        return {
          change_id: item.change_id,
          type: t("llm.change_type.delete_group"),
          subject: item.group_name,
          from: item.group_name,
          to: emptyValue,
          note: "",
        };
      default:
        return {
          change_id: item.change_id,
          type: t("llm.change_type.move_category"),
          subject: item.name,
          from: fallbackText(item.from_group, t("llm.unassigned")),
          to: fallbackText(item.to_group, t("llm.unassigned")),
          note: item.routing_side_effect ? t("llm.routing_side_effect") : "",
        };
    }
  });

  return (
    <Table
      variant="embedded"
      wrapLines
      items={displayChanges}
      columnDefinitions={[
        {
          id: "keep",
          header: t("llm.apply"),
          cell: (item) => (
            <Checkbox
              checked={isSelected(item.change_id)}
              onChange={() => onToggle(item.change_id)}
              ariaLabel={isSelected(item.change_id) ? t("llm.discard") : t("llm.keep")}
            />
          ),
        },
        {
          id: "type",
          header: t("common.type"),
          cell: (item) => <Chip>{item.type}</Chip>,
        },
        {
          id: "subject",
          header: t("llm.subject"),
          cell: (item) => item.subject,
        },
        {
          id: "from",
          header: t("llm.from"),
          cell: (item) => item.from,
        },
        {
          id: "to",
          header: t("llm.to"),
          cell: (item) => item.to,
        },
        {
          id: "note",
          header: t("llm.note"),
          cell: (item) => item.note || emptyValue,
        },
      ]}
      empty={<div className="s-empty">{t("common.no_items")}</div>}
    />
  );
}
