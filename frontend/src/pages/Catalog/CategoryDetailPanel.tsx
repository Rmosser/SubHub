import { GlassTabs } from "@/components/GlassTabs";
import { useLocale } from "@/contexts/LocaleContext";
import { CategoryCustomRulesPanel } from "./CategoryCustomRulesPanel";
import { CategoryPreviewPanel } from "./CategoryPreviewPanel";

interface CategoryDetailPanelProps {
  categoryName: string;
}

export function CategoryDetailPanel({ categoryName }: CategoryDetailPanelProps) {
  const { t } = useLocale();

  return (
    <GlassTabs
      ariaLabel={categoryName}
      tabs={[
        {
          id: "custom-rules",
          label: t("catalog.custom_rules"),
          content: <CategoryCustomRulesPanel categoryName={categoryName} />,
        },
        {
          id: "preview",
          label: t("catalog.preview_rules"),
          content: <CategoryPreviewPanel categoryName={categoryName} />,
        },
      ]}
    />
  );
}
