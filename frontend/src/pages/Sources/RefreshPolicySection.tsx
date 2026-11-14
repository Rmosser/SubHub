import { useState, useEffect } from "react";
import { Button } from "@cloudscape-design/components";
import { SettingField, type SettingSchema } from "@/components/SettingsForm";
import { Disclosure } from "@/components/Disclosure";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useRefreshPolicy } from "@/api/queries";
import { useUpdateRefreshPolicy } from "@/api/mutations";
import { settingsErrors } from "@/components/settingsValidation";
import { WorkspaceLoader } from "@/components/WorkspaceLoader";

// 刷新策略平时是折起来的一行：标题刻在玻璃上，右边一句当前策略；展开是一片玻璃上的四个字段与保存。
export function RefreshPolicySection() {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const policy = useRefreshPolicy();
  const updatePolicy = useUpdateRefreshPolicy();
  const [values, setValues] = useState<Record<string, unknown>>({});

  const schema: SettingSchema[] = [
    { key: "standard_source_auto_pull_enabled", label: t("sources.auto_pull"), type: "bool" },
    {
      key: "standard_source_auto_pull_interval_minutes",
      label: t("sources.interval_minutes"),
      type: "int",
      constraint: t("sources.interval_minutes_range"),
    },
    {
      key: "rule_catalog_cache_hours",
      label: t("sources.rule_catalog_cache_hours"),
      type: "int",
      constraint: t("sources.cache_hours_range"),
    },
    {
      key: "cn_cache_hours",
      label: t("sources.cn_cache_hours"),
      type: "int",
      constraint: t("sources.cache_hours_range"),
    },
  ];

  useEffect(() => {
    if (policy.data) {
      setValues({ ...policy.data });
    }
  }, [policy.data]);

  const handleChange = (key: string, value: unknown) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const invalid = Object.keys(settingsErrors(schema, values)).length > 0;
  const handleSave = () => {
    if (invalid) return;
    updatePolicy.mutate(values, {
      onSuccess: () => addToast("success", t("toast.save_success")),
      onError: (err) => addToast("error", t("toast.save_error"), err.message),
    });
  };

  const saved = policy.data;
  const summary = !saved ? undefined
    : saved.standard_source_auto_pull_enabled
      ? t("sources.auto_pull_every", { count: String(saved.standard_source_auto_pull_interval_minutes ?? "") })
      : t("sources.auto_pull_off");

  return (
    <div className="src-disc">
      <Disclosure title={t("sources.refresh_policy")} summary={summary}>
        <WorkspaceLoader loading={policy.isLoading} error={policy.error} onRetry={() => policy.refetch()}>
          <div className="src-form">
            {schema.map((field) => (
              <SettingField key={field.key} field={field} value={values[field.key]} onChange={(value) => handleChange(field.key, value)} disabled={updatePolicy.isPending} />
            ))}
          </div>
          <div className="src-form-foot">
            <Button variant="primary" onClick={handleSave} loading={updatePolicy.isPending} disabled={invalid}>
              {t("common.save")}
            </Button>
          </div>
        </WorkspaceLoader>
      </Disclosure>
    </div>
  );
}
