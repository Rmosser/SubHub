import { useState } from "react";
import { motion } from "motion/react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Button from "@cloudscape-design/components/button";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import Multiselect from "@cloudscape-design/components/multiselect";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useGeneralProfiles, useReviewSettings } from "@/api/queries";
import { useRunReview, useClearReviewCache } from "@/api/mutations";
import { ReviewSettingsPanel } from "./ReviewSettingsPanel";
import { ReviewResultsPanel, ReviewResultSummary } from "./ReviewResultsPanel";
import { PageHeader } from "@/components/PageHeader";
import { PaperNote } from "@/components/PaperNote";
import { Section, Surface } from "@/components/Section";
import { SLIDE_UP, SPRING_DEFAULT } from "@/motion";
import type { ReviewResult } from "@/types/review";

export function ReviewPage() {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const profiles = useGeneralProfiles();
  const settings = useReviewSettings();
  const runReview = useRunReview();
  const clearCache = useClearReviewCache();

  const [primaryId, setPrimaryId] = useState("");
  const [targetIds, setTargetIds] = useState<string[]>([]);
  const [results, setResults] = useState<ReviewResult[]>([]);
  const [runError, setRunError] = useState<string | null>(null);
  const reviewReady = Boolean(settings.data?.review_model && settings.data.gemini_api_key_set);

  const profileOptions = (profiles.data ?? []).map((p) => ({
    value: p.id,
    label: p.name,
  }));

  const handleRun = () => {
    if (!primaryId || targetIds.length === 0 || !reviewReady) return;
    setRunError(null);
    runReview.mutate(
      { primary_profile_id: primaryId, target_profile_ids: targetIds },
      {
        onSuccess: (data) => {
          setResults(data.reviews);
        },
        onError: (err) => {
          setRunError(err.message);
          addToast("error", t("review.run_failed"), err.message);
        },
      },
    );
  };

  const handleClearCache = () => {
    clearCache.mutate(undefined, {
      onSuccess: () => addToast("success", t("toast.delete_success")),
      onError: (err) => addToast("error", err.message),
    });
  };

  return (
    <ContentLayout header={<PageHeader title={t("review.title")} />}>
      <motion.div initial={SLIDE_UP.initial} animate={SLIDE_UP.animate} transition={SPRING_DEFAULT}>
        <div className="s-stack s-page-stack">
          {!reviewReady && !settings.isLoading ? (
            <PaperNote>
              <strong>{t("review.missing_state")}</strong>
              <div className="s-muted">{t("review.missing_state_help")}</div>
            </PaperNote>
          ) : null}

          <ReviewSettingsPanel />

          <Section
            title={t("review.run_review")}
            actions={
              <>
                <Button onClick={handleClearCache} loading={clearCache.isPending}>
                  {t("review.clear_cache")}
                </Button>
                <Button
                  variant="primary"
                  onClick={handleRun}
                  loading={runReview.isPending}
                  disabled={!primaryId || targetIds.length === 0 || !reviewReady}
                >
                  {runReview.isPending ? t("review.running") : t("review.run_review")}
                </Button>
              </>
            }
          >
            <Surface>
              <div className="s-row">
                <div className="s-grow">
                  <FormField label={t("review.primary_profile")}>
                    <Select
                      selectedOption={profileOptions.find((o) => o.value === primaryId) || null}
                      options={profileOptions}
                      onChange={({ detail }) => setPrimaryId(detail.selectedOption.value!)}
                      placeholder={t("review.primary_profile_placeholder")}
                    />
                  </FormField>
                </div>
                <div className="s-grow">
                  <FormField label={t("review.target_profiles")}>
                    <Multiselect
                      selectedOptions={profileOptions.filter((o) => targetIds.includes(o.value!))}
                      options={profileOptions.filter((o) => o.value !== primaryId)}
                      onChange={({ detail }) => setTargetIds(detail.selectedOptions.map((o) => o.value!))}
                      placeholder={t("review.target_profiles_placeholder")}
                    />
                  </FormField>
                </div>
              </div>
            </Surface>
          </Section>

          <Section title={t("review.results")} meta={<ReviewResultSummary results={results} />}>
            <ReviewResultsPanel results={results} runError={runError} onRetry={handleRun} retrying={runReview.isPending} />
          </Section>
        </div>
      </motion.div>
    </ContentLayout>
  );
}
