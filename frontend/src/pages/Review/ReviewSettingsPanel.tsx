import { useState, useEffect } from "react";
import { Button, FormField, Input } from "@cloudscape-design/components";
import { StatusBadge } from "@/components/StatusBadge";
import { Section, Surface } from "@/components/Section";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useReviewSettings } from "@/api/queries";
import { useUpdateReviewSettings } from "@/api/mutations";

export function ReviewSettingsPanel() {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const settings = useReviewSettings();
  const updateSettings = useUpdateReviewSettings();

  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const reviewModel = settings.data?.review_model ?? "";
  const apiKeyConfigured = settings.data?.gemini_api_key_set === true;

  useEffect(() => {
    if (settings.data) {
      setModel(reviewModel);
    }
  }, [reviewModel, settings.data]);

  const handleSave = () => {
    if (apiKeyConfigured && !apiKey.trim()) {
      addToast("warning", t("review.api_key_reenter_required"));
      return;
    }

    updateSettings.mutate(
      { review_model: model, gemini_api_key: apiKey.trim() },
      {
        onSuccess: () => {
          setApiKey("");
          addToast("success", t("toast.save_success"));
        },
        onError: (err) => addToast("error", t("toast.save_error"), err.message),
      },
    );
  };

  return (
    <Section
      title={t("review.settings")}
      actions={
        <Button onClick={handleSave} loading={updateSettings.isPending}>
          {t("common.save")}
        </Button>
      }
    >
      <Surface>
        <div className="s-row">
          <div className="s-grow">
            <FormField label={t("review.model")}>
              <Input value={model} onChange={({ detail }) => setModel(detail.value)} placeholder="gpt-4o" />
            </FormField>
          </div>
          <div className="s-grow">
            <FormField
              label={t("review.api_key")}
              info={
                <StatusBadge status={apiKeyConfigured ? "success" : "warning"}>
                  {apiKeyConfigured ? t("review.api_key_set") : t("review.api_key_missing")}
                </StatusBadge>
              }
            >
              <Input
                type="password"
                value={apiKey}
                onChange={({ detail }) => setApiKey(detail.value)}
                placeholder={apiKeyConfigured ? t("review.api_key_reenter_placeholder") : "AIza..."}
              />
            </FormField>
          </div>
        </div>
      </Surface>
    </Section>
  );
}
