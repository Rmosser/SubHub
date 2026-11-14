import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Select, { type SelectProps } from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { GlassSelect } from "@/components/GlassSelect";
import { useLocale } from "@/contexts/LocaleContext";
import { useScenario } from "@/contexts/ScenarioContext";
import "@/styles/scenario-selector.css";

interface ScenarioSelectorProps {
  label?: string;
  compact?: boolean;
  hideLabel?: boolean;
  stretch?: boolean;
  sidebar?: boolean;
}

export function ScenarioSelector({
  label,
  compact = false,
  hideLabel = false,
  stretch = false,
  sidebar = false,
}: ScenarioSelectorProps) {
  const { locale, t } = useLocale();
  const {
    enabledScenarios,
    requestedScenario,
    selectedScenario,
    selectedScenarioId,
    setSelectedScenarioId,
    isLoading,
    hasSelectionMismatch,
    selectionIssue,
  } = useScenario();
  const isZh = locale === "zh-CN";
  const resolvedLabel = label || (isZh ? "当前场景" : "Scenario");

  const options: SelectProps.Option[] = enabledScenarios.map((item) => ({
    value: item.id,
    label: item.name,
    description: item.description || item.slug,
  }));

  // On the glass (the rail) the select is etched in; elsewhere it stays a Cloudscape field.
  const selector = stretch ? (
    <GlassSelect
      stretch
      value={selectedScenarioId}
      options={enabledScenarios.map((item) => ({ value: item.id, label: item.name }))}
      ariaLabel={resolvedLabel}
      disabled={isLoading && !enabledScenarios.length}
      placeholder={isLoading ? (isZh ? "加载场景中…" : "Loading scenarios…") : (isZh ? "选择场景" : "Select scenario")}
      onChange={(value) => setSelectedScenarioId(value)}
    />
  ) : (
    <Select
      selectedOption={options.find((item) => item.value === selectedScenarioId) || null}
      options={options}
      loadingText={isZh ? "加载场景中..." : "Loading scenarios..."}
      statusType={isLoading ? "loading" : "finished"}
      placeholder={isZh ? "选择场景" : "Select scenario"}
      ariaLabel={resolvedLabel}
      onChange={({ detail }) => setSelectedScenarioId(detail.selectedOption.value || "")}
    />
  );

  const mismatchNotice = hasSelectionMismatch ? (
    <Box
      fontSize="body-s"
      color="text-body-secondary"
      padding={{ top: "xs" }}
    >
      <SpaceBetween size="xxs">
        <StatusIndicator type="warning">
          {selectionIssue === "disabled"
            ? t("scenario.selection_disabled", {
              requested: requestedScenario?.name || requestedScenario?.slug || t("scenario.current"),
              active: selectedScenario?.name || t("scenario.current"),
            })
            : t("scenario.selection_missing", {
              active: selectedScenario?.name || t("scenario.current"),
            })}
        </StatusIndicator>
        <Box variant="small">
          {t("scenario.selection_reselect_hint")}
        </Box>
      </SpaceBetween>
    </Box>
  ) : null;

  if (compact || hideLabel || stretch || sidebar) {
    const className = [
      "scenario-selector",
      compact ? "scenario-selector--compact" : "",
      hideLabel ? "scenario-selector--label-hidden" : "",
      stretch ? "scenario-selector--stretch" : "",
      sidebar ? "scenario-selector--sidebar" : "",
    ]
      .filter(Boolean)
      .join(" ");

    return (
      <div className={className}>
        {!hideLabel ? <span className="scenario-selector__label">{resolvedLabel}</span> : null}
        <div className="scenario-selector__control">
          {selector}
          {mismatchNotice}
        </div>
      </div>
    );
  }

  return (
    <FormField label={resolvedLabel}>
      <SpaceBetween size="xs">
        {selector}
        {mismatchNotice}
      </SpaceBetween>
    </FormField>
  );
}
