import { useEffect, useState } from "react";
import { Button, ExpandableSection, FormField, SpaceBetween, Textarea } from "@cloudscape-design/components";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useUpdateLlmExportSettings } from "@/api/mutations";
import { useLlmExportSettings } from "@/api/queries";

export function LlmSettingsPanel() {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const settings = useLlmExportSettings();
  const updateSettings = useUpdateLlmExportSettings();

  const [directnessPreferences, setDirectnessPreferences] = useState("");
  const [rulesPreferences, setRulesPreferences] = useState("");
  const [pinsPreferences, setPinsPreferences] = useState("");

  useEffect(() => {
    if (!settings.data) {
      return;
    }
    setDirectnessPreferences(settings.data.directness_preferences ?? "");
    setRulesPreferences(settings.data.rules_preferences ?? "");
    setPinsPreferences(settings.data.pins_preferences ?? "");
  }, [settings.data]);

  const handleSave = () => {
    updateSettings.mutate(
      {
        directness_preferences: directnessPreferences,
        rules_preferences: rulesPreferences,
        pins_preferences: pinsPreferences,
      },
      {
        onSuccess: () => addToast("success", t("toast.save_success")),
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    );
  };

  return (
    <ExpandableSection headerText={t("llm.export_settings")} variant="container">
      <SpaceBetween size="m">
        <FormField label={t("llm.directness_preferences")}>
          <Textarea
            value={directnessPreferences}
            onChange={({ detail }) => setDirectnessPreferences(detail.value)}
            rows={4}
            placeholder={t("llm.preferences_placeholder")}
          />
        </FormField>
        <FormField label={t("llm.rules_preferences")}>
          <Textarea
            value={rulesPreferences}
            onChange={({ detail }) => setRulesPreferences(detail.value)}
            rows={4}
            placeholder={t("llm.preferences_placeholder")}
          />
        </FormField>
        <FormField label={t("llm.pins_preferences")}>
          <Textarea
            value={pinsPreferences}
            onChange={({ detail }) => setPinsPreferences(detail.value)}
            rows={4}
            placeholder={t("llm.preferences_placeholder")}
          />
        </FormField>
        <div className="s-row s-row-center">
          <Button onClick={handleSave} loading={updateSettings.isPending}>
            {t("common.save")}
          </Button>
          <span className="s-muted s-small">{t("llm.settings_saved_scope")}</span>
        </div>
      </SpaceBetween>
    </ExpandableSection>
  );
}
