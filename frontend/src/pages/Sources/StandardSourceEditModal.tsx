import { useState, useEffect, useId } from "react";
import {
  ExpandableSection,
  FormField,
  Input,
  Select,
  SelectProps,
  SpaceBetween,
  Textarea,
  Toggle,
} from "@cloudscape-design/components";
import { useContracts } from "@/api/queries";
import { FormModal } from "@/components/FormModal";
import { ErrorNote } from "@/components/ErrorNote";
import { useLocale } from "@/contexts/LocaleContext";
import type { StandardSource } from "@/types";
import { resolvePullMode, validateStandardSourceDraft } from "./sourceForm";

interface StandardSourceEditModalProps {
  visible: boolean;
  source: StandardSource | null;
  initialIngestKind?: string;
  loading: boolean;
  errorText?: string;
  onSave: (data: Record<string, unknown>) => void;
  onCancel: () => void;
}

const INGEST_KIND_REMOTE_SUBSCRIPTION = "remote_subscription";
const INGEST_KIND_MANUAL_NODES = "manual_nodes";
const DEFAULT_SCENARIO_ID = "scenario-default";
const SOURCE_MODE_ROUTE_CONTRACT = "route_contract";
const SOURCE_MODE_HIGH_QUALITY_AIRPORT = "high_quality_airport";

const PULL_MODES = ["", "direct_then_proxy", "direct_only", "proxy_then_direct"] as const;

export function StandardSourceEditModal({
  visible,
  source,
  initialIngestKind = INGEST_KIND_REMOTE_SUBSCRIPTION,
  loading,
  errorText,
  onSave,
  onCancel,
}: StandardSourceEditModalProps) {
  const { t } = useLocale();
  const enabledId = useId();
  const pullModeOptions: SelectProps.Option[] = PULL_MODES.map((value) => ({ value, label: t(`sources.pull_mode_${value || "default"}`) }));
  const contracts = useContracts(DEFAULT_SCENARIO_ID);
  const isEdit = !!source;

  const [name, setName] = useState("");
  const [clashUrl, setClashUrl] = useState("");
  const [shadowrocketUrl, setShadowrocketUrl] = useState("");
  const [surgeUrl, setSurgeUrl] = useState("");
  const [loginUrl, setLoginUrl] = useState("");
  const [ingestKind, setIngestKind] = useState(INGEST_KIND_REMOTE_SUBSCRIPTION);
  const [manualNodesText, setManualNodesText] = useState("");
  const [sourceMode, setSourceMode] = useState(SOURCE_MODE_ROUTE_CONTRACT);
  const [targetContractId, setTargetContractId] = useState("");
  const [pullMode, setPullMode] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [advancedExpanded, setAdvancedExpanded] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const isManualNodes = ingestKind === INGEST_KIND_MANUAL_NODES;

  const enabledContractOptions: SelectProps.Option[] = (contracts.data ?? [])
    .filter((item) => item.can_bind_standard_source === true)
    .map((item) => ({
      value: item.id,
      label: item.display_name,
      description: item.description || undefined,
    }));
  const currentContract = (contracts.data ?? []).find((item) => item.id === targetContractId);
  const currentContractOption =
    sourceMode === SOURCE_MODE_ROUTE_CONTRACT && targetContractId
      ? {
          value: targetContractId,
          label:
            String(currentContract?.display_name || source?.target_contract_display_name || targetContractId).trim(),
          description: currentContract?.description || t("sources.target_contract_unavailable"),
          disabled: !currentContract || currentContract.can_bind_standard_source !== true,
        }
      : null;
  const contractOptions: SelectProps.Option[] = currentContractOption
    && !enabledContractOptions.some((item) => item.value === currentContractOption.value)
    ? [currentContractOption, ...enabledContractOptions]
    : enabledContractOptions;

  const sourceModeOptions: SelectProps.Option[] = [
    { value: SOURCE_MODE_ROUTE_CONTRACT, label: t("sources.mode_route_contract") },
    { value: SOURCE_MODE_HIGH_QUALITY_AIRPORT, label: t("sources.mode_high_quality_airport") },
  ];

  useEffect(() => {
    setSubmitted(false);
    if (source) {
      setName(source.name);
      setClashUrl(source.clash_url);
      setShadowrocketUrl(source.shadowrocket_url);
      setSurgeUrl(source.surge_url);
      setLoginUrl(source.login_url);
      setIngestKind(source.ingest_kind || INGEST_KIND_REMOTE_SUBSCRIPTION);
      setManualNodesText(source.manual_nodes_text || "");
      setSourceMode(source.source_mode || SOURCE_MODE_ROUTE_CONTRACT);
      setTargetContractId(source.target_contract_id || "");
      setPullMode(source.pull_network_mode || "");
      setEnabled(source.enabled);
      setAdvancedExpanded(true);
    } else {
      setName("");
      setClashUrl("");
      setShadowrocketUrl("");
      setSurgeUrl("");
      setLoginUrl("");
      setIngestKind(initialIngestKind);
      setManualNodesText("");
      setSourceMode(SOURCE_MODE_ROUTE_CONTRACT);
      setTargetContractId("");
      setPullMode("");
      setEnabled(true);
      setAdvancedExpanded(false);
    }
  }, [initialIngestKind, source, visible]);

  const errors = validateStandardSourceDraft({ name, ingestKind, sourceMode, targetContractId, clashUrl, shadowrocketUrl, manualNodesText });
  const fieldError = (field: string) => submitted && errors[field] ? t(errors[field]) : undefined;
  const contractRequired = isManualNodes || sourceMode === SOURCE_MODE_ROUTE_CONTRACT;
  const contractSelectionValid = Boolean(
    targetContractId && enabledContractOptions.some((item) => item.value === targetContractId),
  );
  const targetContractError = submitted
    ? errors.targetContractId
      ? t(errors.targetContractId)
      : contractRequired && !contractSelectionValid
        ? t("sources.target_contract_required")
        : undefined
    : undefined;

  const handleSubmit = () => {
    setSubmitted(true);
    if (Object.keys(errors).length || (contractRequired && !contractSelectionValid)) return;
    const body: Record<string, unknown> = {
      name: name.trim(),
      ingest_kind: ingestKind,
      source_mode: isManualNodes ? SOURCE_MODE_ROUTE_CONTRACT : sourceMode,
      enabled,
    };
    if (isManualNodes) {
      body.manual_nodes_text = manualNodesText;
    } else {
      body.clash_url = clashUrl;
      body.shadowrocket_url = shadowrocketUrl;
      body.surge_url = surgeUrl;
      body.login_url = loginUrl;
    }
    if (isManualNodes || sourceMode === SOURCE_MODE_ROUTE_CONTRACT) {
      body.target_contract_id = targetContractId;
    }
    if (!isManualNodes) body.pull_network_mode = resolvePullMode(pullMode);
    if (isEdit) body.id = source!.id;
    onSave(body);
  };

  return (
    <FormModal
      visible={visible}
      header={isEdit ? t("sources.edit_standard") : isManualNodes ? t("sources.add_manual") : t("sources.add_remote")}
      loading={loading}
      errorText={errorText}
      confirmLabel={t("common.save")}
      confirmDisabled={
        contracts.isLoading ||
        Boolean(contracts.error) ||
        (contractRequired && !contractSelectionValid)
      }
      onSubmit={handleSubmit}
      onCancel={onCancel}
    >
      <SpaceBetween size="l">
        {contracts.error && (
          <ErrorNote title={t("sources.contracts_unavailable")} reason={contracts.error.message} onRetry={() => contracts.refetch()} />
        )}
        <FormField label={t("common.name")} errorText={fieldError("name")}>
          <Input value={name} onChange={({ detail }) => setName(detail.value)} />
        </FormField>
        {isManualNodes ? (
          <FormField label={t("sources.manual_nodes_text")} errorText={fieldError("manualNodesText")}>
            <Textarea
              value={manualNodesText}
              onChange={({ detail }) => setManualNodesText(detail.value)}
              rows={8}
              placeholder={t("sources.manual_nodes_help")}
            />
          </FormField>
        ) : (
          <>
            <FormField label={t("sources.clash_url")} errorText={fieldError("clashUrl")}>
              <Input
                value={clashUrl}
                onChange={({ detail }) => setClashUrl(detail.value)}
                type="url"
                placeholder={t("sources.quick_primary_url_placeholder")}
              />
            </FormField>
            <FormField label={t("sources.shadowrocket_url")} errorText={fieldError("shadowrocketUrl")}>
              <Input
                value={shadowrocketUrl}
                onChange={({ detail }) => setShadowrocketUrl(detail.value)}
                type="url"
                placeholder={t("sources.quick_primary_url_placeholder")}
              />
            </FormField>
          </>
        )}
        <FormField label={t("sources.target_contract")} errorText={targetContractError || fieldError("targetContractId")}>
          <Select
            selectedOption={contractOptions.find((o) => o.value === targetContractId) || currentContractOption}
            options={contractOptions}
            onChange={({ detail }) => setTargetContractId(detail.selectedOption.value || "")}
            disabled={!isManualNodes && sourceMode !== SOURCE_MODE_ROUTE_CONTRACT}
            placeholder={t("sources.target_contract_placeholder")}
          />
        </FormField>
        {!isManualNodes && (
          <ExpandableSection
            headerText={t("sources.advanced_import_options")}
            expanded={advancedExpanded}
            onChange={({ detail }) => setAdvancedExpanded(detail.expanded)}
          >
            <SpaceBetween size="l">
              <FormField label={t("sources.surge_url")}>
                <Input value={surgeUrl} onChange={({ detail }) => setSurgeUrl(detail.value)} type="url" />
              </FormField>
              <FormField label={t("sources.login_url")}>
                <Input value={loginUrl} onChange={({ detail }) => setLoginUrl(detail.value)} type="url" />
              </FormField>
              <FormField label={t("sources.source_mode")}>
                <Select
                  selectedOption={sourceModeOptions.find((o) => o.value === sourceMode) || null}
                  options={sourceModeOptions}
                  onChange={({ detail }) => setSourceMode(detail.selectedOption.value || SOURCE_MODE_ROUTE_CONTRACT)}
                />
              </FormField>
              <FormField label={t("sources.pull_mode")}>
                <Select
                  selectedOption={pullModeOptions.find((o) => o.value === pullMode) || pullModeOptions[0]}
                  options={pullModeOptions}
                  onChange={({ detail }) => setPullMode(detail.selectedOption.value || "")}
                />
              </FormField>
            </SpaceBetween>
          </ExpandableSection>
        )}
        <FormField controlId={enabledId} label={t("common.enabled")}>
          <Toggle controlId={enabledId} checked={enabled} onChange={({ detail }) => setEnabled(detail.checked)} />
        </FormField>
      </SpaceBetween>
    </FormModal>
  );
}
