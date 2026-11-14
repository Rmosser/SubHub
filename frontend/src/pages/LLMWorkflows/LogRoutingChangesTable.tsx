import { Checkbox, Table } from "@cloudscape-design/components";
import { Chip } from "@/components/Chip";
import { useLocale } from "@/contexts/LocaleContext";
import type { LogRoutingPreviewChange } from "@/types";

interface LogRoutingChangesTableProps {
  changes: LogRoutingPreviewChange[];
  selectedActionIds: string[];
  onToggle: (changeId: string) => void;
}

export function LogRoutingChangesTable({
  changes,
  selectedActionIds,
  onToggle,
}: LogRoutingChangesTableProps) {
  const { t } = useLocale();
  const isSelected = (changeId: string) => selectedActionIds.includes(changeId);

  return (
    <Table
      variant="embedded"
      wrapLines
      items={changes}
      columnDefinitions={[
        {
          id: "keep",
          header: t("llm.apply"),
          cell: (item) => (
            <Checkbox
              checked={isSelected(item.id)}
              onChange={() => onToggle(item.id)}
              ariaLabel={`${isSelected(item.id) ? t("llm.discard") : t("llm.keep")} ${item.summary || item.id}`}
            />
          ),
        },
        {
          id: "type",
          header: t("common.type"),
          cell: (item) => <Chip mono>{item.type}</Chip>,
        },
        {
          id: "status",
          header: t("common.status"),
          cell: (item) => item.status,
        },
        {
          id: "summary",
          header: t("llm.note"),
          cell: (item) => item.summary,
        },
      ]}
      empty={<div className="s-empty">{t("llm.no_changes")}</div>}
    />
  );
}
