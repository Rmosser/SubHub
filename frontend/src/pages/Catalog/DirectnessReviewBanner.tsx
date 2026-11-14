import { useState } from "react";
import { Table, Button } from "@cloudscape-design/components";
import { useLocale } from "@/contexts/LocaleContext";
import { useNotifications } from "@/contexts/NotificationContext";
import { useDirectnessReviews } from "@/api/queries";
import { useApplyDirectnessReviews } from "@/api/mutations";
import { formatDateTime } from "@/utils/formatting";
import { PaperNote } from "@/components/PaperNote";
import { Chip } from "@/components/Chip";
import { InlineAction, LinkAction } from "@/components/InlineAction";
import { ReasonText } from "@/components/ReasonText";
import { Surface } from "@/components/Section";

// 待审核直连是一张纸：数量和批量动作在纸上，逐条明细按需展开到纸下方的面板里。
export function DirectnessReviewBanner() {
  const { t } = useLocale();
  const { addToast } = useNotifications();
  const reviews = useDirectnessReviews();
  const applyReviews = useApplyDirectnessReviews();
  const [open, setOpen] = useState(false);

  const pendingReviews = (reviews.data ?? []).filter((r) => r.status === "pending");

  if (pendingReviews.length === 0) return null;

  const handleAction = (ids: string[], action: "accept" | "dismiss") => {
    applyReviews.mutate(
      { review_ids: ids, action },
      {
        onSuccess: () => addToast("success", t("toast.update_success")),
        onError: (err) => addToast("error", t("toast.update_error"), err.message),
      },
    );
  };
  const allIds = pendingReviews.map((r) => r.id);

  return (
    <div className="s-stack">
      <PaperNote
        action={
          <>
            <InlineAction onClick={() => setOpen((value) => !value)} ariaExpanded={open} ariaLabel={`${open ? t("common.collapse") : t("common.expand")} ${t("catalog.directness_pending")}`}>
              {open ? t("common.collapse") : t("catalog.directness_review_each")}
            </InlineAction>
            <Button onClick={() => handleAction(allIds, "accept")} loading={applyReviews.isPending}>
              {t("catalog.directness_accept_all")}
            </Button>
            <LinkAction onClick={() => handleAction(allIds, "dismiss")} disabled={applyReviews.isPending}>
              {t("catalog.directness_dismiss_all")}
            </LinkAction>
          </>
        }
      >
        <strong>{t("catalog.directness_pending")}</strong> <span className="s-num">{pendingReviews.length}</span>
      </PaperNote>
      {open ? (
        <Surface flush>
          <Table
            variant="embedded"
            items={pendingReviews}
            columnDefinitions={[
              { id: "category_name", header: t("common.name"), cell: (item) => item.category_name },
              {
                id: "proposed_decision",
                header: t("catalog.directness_decision"),
                cell: (item) => <Chip mono dot={item.proposed_decision === "DIRECT" ? "teal" : "flow"}>{item.proposed_decision}</Chip>,
              },
              { id: "confidence", header: t("catalog.directness_confidence"), cell: (item) => <span className="s-num">{item.confidence}</span> },
              { id: "reason", header: t("catalog.directness_reason"), cell: (item) => <ReasonText text={String(item.reason ?? "")} /> },
              { id: "created_at", header: t("common.updated_at"), cell: (item) => formatDateTime(item.created_at) },
              {
                id: "actions",
                header: t("common.actions"),
                cell: (item) => (
                  <div className="s-chips">
                    <InlineAction onClick={() => handleAction([item.id], "accept")} disabled={applyReviews.isPending}>
                      {t("catalog.directness_accept")}
                    </InlineAction>
                    <InlineAction onClick={() => handleAction([item.id], "dismiss")} disabled={applyReviews.isPending}>
                      {t("catalog.directness_dismiss")}
                    </InlineAction>
                  </div>
                ),
              },
            ]}
            empty={<div className="s-empty">{t("common.no_items")}</div>}
          />
        </Surface>
      ) : null}
    </div>
  );
}
