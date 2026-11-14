import type { ReviewAnnotation, ReviewResult, ReviewRunResponse, ReviewSettings } from "@/types";
import { asRecord, asString } from "./shared";
import { bool, object, response, str } from "./schema";

function parseReviewAnnotation(raw: unknown): ReviewAnnotation {
  const item = asRecord(raw);
  const diffType = asString(item.diff_type);
  return {
    key: asString(item.key),
    diff_type: diffType === "added" || diffType === "removed" || diffType === "changed" ? diffType : "changed",
    primary_value: asString(item.primary_value),
    target_value: asString(item.target_value),
    explanation: asString(item.explanation),
  };
}

function parseReviewResult(raw: unknown): ReviewResult {
  const item = asRecord(raw);
  return {
    target_profile_id: asString(item.target_profile_id),
    target_profile_name: asString(item.target_profile_name),
    annotations: Array.isArray(item.annotations) ? item.annotations.map(parseReviewAnnotation) : [],
    error: item.error == null ? null : asString(item.error),
  };
}

export function parseReviewRunResponse(raw: unknown): ReviewRunResponse {
  const payload = asRecord(raw);
  return {
    reviews: Array.isArray(payload.reviews) ? payload.reviews.map(parseReviewResult) : [],
  };
}


const reviewSettingsItem = response(
  object<{ item: ReviewSettings }>({ item: object<ReviewSettings>({ review_model: str, gemini_api_key_set: bool }) }),
);

export function parseReviewSettings(raw: unknown): ReviewSettings {
  return reviewSettingsItem(raw).item;
}
