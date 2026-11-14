import { useEffect, useId, useState } from "react";
import {
  FormField,
  Input,
  Select,
  SpaceBetween,
  Textarea,
  Toggle,
  type SelectProps,
} from "@cloudscape-design/components";
import Multiselect from "@cloudscape-design/components/multiselect";
import { usePools } from "@/api/queries";
import { FormModal } from "@/components/FormModal";
import { useLocale } from "@/contexts/LocaleContext";
import { useScenario } from "@/contexts/ScenarioContext";
import type {
  ContractRoutingAction,
  ContractMutationBody,
  ContractMutationPayload,
  RouteContract,
} from "@/types";

interface ContractEditModalProps {
  visible: boolean;
  contract: RouteContract | null;
  loading: boolean;
  onSave: (data: ContractMutationPayload) => void;
  onCancel: () => void;
}

const DEFAULT_SCENARIO_ID = "scenario-default";

const STRATEGY_OPTIONS: SelectProps.Option[] = [
  { value: "strict", label: "strict" },
  { value: "failover", label: "failover" },
  { value: "load-balance", label: "load-balance" },
];

const FAILURE_ACTION_OPTIONS: SelectProps.Option[] = [
  { value: "interrupt", label: "interrupt" },
  { value: "direct", label: "direct" },
  { value: "degrade", label: "degrade" },
];

const ROUTING_ACTION_OPTIONS: SelectProps.Option[] = [
  { value: "proxy", label: "proxy" },
  { value: "direct", label: "direct" },
  { value: "reject", label: "reject" },
];

function canEditTopology(contract: RouteContract | null, scenarioId: string) {
  if (!contract) {
    return true;
  }
  if (contract.scope === "global") {
    return scenarioId === DEFAULT_SCENARIO_ID;
  }
  if (contract.scope === "scenario") {
    return contract.owner_scenario_id === scenarioId;
  }
  return contract.scope === "system" && scenarioId === DEFAULT_SCENARIO_ID;
}

export function ContractEditModal({
  visible,
  contract,
  loading,
  onSave,
  onCancel,
}: ContractEditModalProps) {
  const { t } = useLocale();
  const defaultId = useId();
  const enabledId = useId();
  const { selectedScenarioId } = useScenario();
  const pools = usePools();
  const isCreate = !contract;
  const topologyEditable = canEditTopology(contract, selectedScenarioId);

  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [llmRoutingIntent, setLlmRoutingIntent] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [sortOrder, setSortOrder] = useState("0");
  const [isDefault, setIsDefault] = useState(false);
  const [routingAction, setRoutingAction] = useState<ContractRoutingAction>("proxy");
  const [strategyType, setStrategyType] = useState<RouteContract["strategy_type"]>("strict");
  const [primaryPools, setPrimaryPools] = useState<string[]>(["medium"]);
  const [fallbackPools, setFallbackPools] = useState<string[]>([]);
  const [failureAction, setFailureAction] = useState<RouteContract["failure_action"]>("interrupt");

  const poolOptions: SelectProps.Option[] = (pools.data ?? [])
    .filter((item) => item.id !== "direct")
    .map((item) => ({
      value: item.id,
      label: item.display_name,
      description: item.pseudo ? "pseudo" : undefined,
    }));
  const routingActionOptions = ROUTING_ACTION_OPTIONS.map((item) => ({
    ...item,
    label: t(`contracts.routing_action_${item.value}`),
  }));

  useEffect(() => {
    if (contract) {
      setDisplayName(contract.display_name);
      setDescription(contract.description || "");
      setLlmRoutingIntent(contract.llm_routing_intent || "");
      setEnabled(contract.enabled);
      setSortOrder(String(contract.sort_order ?? 0));
      setIsDefault(contract.is_default);
      setRoutingAction(contract.routing_action || "proxy");
      setStrategyType(contract.strategy_type || "strict");
      setPrimaryPools(contract.primary_pools.length > 0 ? contract.primary_pools : ["medium"]);
      setFallbackPools(contract.fallback_pools || []);
      setFailureAction(contract.failure_action || "interrupt");
      return;
    }
    setDisplayName("");
    setDescription("");
    setLlmRoutingIntent("");
    setEnabled(true);
    setSortOrder("0");
    setIsDefault(false);
    setRoutingAction("proxy");
    setStrategyType("strict");
    setPrimaryPools(["medium"]);
    setFallbackPools([]);
    setFailureAction("interrupt");
  }, [contract, visible]);

  // 只在字段被锁住时说明原因；新建和普通编辑由表单本身说明。
  const lockedHelp = !isCreate && !topologyEditable ? t("contracts.view_only_help") : null;

  const handleSubmit = () => {
    const body: ContractMutationBody = {
      display_name: displayName,
      description,
      llm_routing_intent: llmRoutingIntent,
      enabled,
      sort_order: Number(sortOrder) || 0,
      is_default: isDefault,
    };
    if (isCreate || topologyEditable) {
      body.routing_action = routingAction;
    }
    if ((isCreate || topologyEditable) && routingAction === "proxy") {
      body.strategy_type = strategyType;
      body.primary_pools = primaryPools;
      body.fallback_pools = fallbackPools;
      body.failure_action = failureAction;
    }
    if (contract) {
      onSave({ ...body, id: contract.id });
      return;
    }
    onSave(body);
  };

  return (
    <FormModal
      visible={visible}
      header={isCreate ? t("contracts.create_contract") : t("contracts.edit_contract")}
      loading={loading}
      confirmLabel={t("common.save")}
      onSubmit={handleSubmit}
      onCancel={onCancel}
    >
      <SpaceBetween size="l">
        {lockedHelp ? <p className="s-dialog-lead">{lockedHelp}</p> : null}
        <FormField label={t("common.name")}>
          <Input value={displayName} onChange={({ detail }) => setDisplayName(detail.value)} />
        </FormField>
        <FormField label={t("common.description")}>
          <Textarea value={description} onChange={({ detail }) => setDescription(detail.value)} rows={4} />
        </FormField>
        <FormField label={t("contracts.llm_intent")}>
          <Textarea value={llmRoutingIntent} onChange={({ detail }) => setLlmRoutingIntent(detail.value)} rows={4} />
        </FormField>
        <FormField label={t("contracts.routing_action")}>
          <Select
            selectedOption={routingActionOptions.find((item) => item.value === routingAction) || null}
            options={routingActionOptions}
            disabled={!topologyEditable && !isCreate}
            onChange={({ detail }) =>
              setRoutingAction((detail.selectedOption.value as ContractRoutingAction | undefined) || "proxy")}
          />
        </FormField>
        {topologyEditable && routingAction === "proxy" && (
          <>
            <FormField label={t("contracts.strategy")}>
              <Select
                selectedOption={STRATEGY_OPTIONS.find((item) => item.value === strategyType) || null}
                options={STRATEGY_OPTIONS}
                onChange={({ detail }) =>
                  setStrategyType((detail.selectedOption.value as RouteContract["strategy_type"] | undefined) || "strict")}
              />
            </FormField>
            <FormField label={t("contracts.primary_pools")}>
              <Multiselect
                selectedOptions={poolOptions.filter((item) => primaryPools.includes(item.value || ""))}
                options={poolOptions}
                placeholder={t("contracts.primary_pool_placeholder")}
                onChange={({ detail }) => {
                  const nextPrimaryPools = detail.selectedOptions.map((item) => item.value || "");
                  setPrimaryPools(nextPrimaryPools);
                  setFallbackPools((current) => current.filter((item) => !nextPrimaryPools.includes(item)));
                }}
              />
            </FormField>
            <FormField label={t("contracts.fallback_pools")}>
              <Multiselect
                selectedOptions={poolOptions.filter((item) => fallbackPools.includes(item.value || ""))}
                options={poolOptions.filter((item) => !primaryPools.includes(item.value || ""))}
                placeholder={t("contracts.fallback_pool_placeholder")}
                onChange={({ detail }) => setFallbackPools(detail.selectedOptions.map((item) => item.value || ""))}
              />
            </FormField>
            <FormField label={t("contracts.failure_action")} description={t("contracts.failure_action_help")}>
              <Select
                selectedOption={FAILURE_ACTION_OPTIONS.find((item) => item.value === failureAction) || null}
                options={FAILURE_ACTION_OPTIONS}
                onChange={({ detail }) =>
                  setFailureAction(
                    (detail.selectedOption.value as RouteContract["failure_action"] | undefined) || "interrupt",
                  )}
              />
            </FormField>
          </>
        )}
        <FormField label={t("common.sort_order")}>
          <Input value={sortOrder} onChange={({ detail }) => setSortOrder(detail.value)} type="number" />
        </FormField>
        <FormField controlId={defaultId} label={t("contracts.default")} description={t("contracts.default_help")}>
          <Toggle controlId={defaultId} checked={isDefault} onChange={({ detail }) => setIsDefault(detail.checked)} />
        </FormField>
        <FormField controlId={enabledId} label={t("common.enabled")} description={t("contracts.enabled_help")}>
          <Toggle controlId={enabledId} checked={enabled} onChange={({ detail }) => setEnabled(detail.checked)} />
        </FormField>
      </SpaceBetween>
    </FormModal>
  );
}
