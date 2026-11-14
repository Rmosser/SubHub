export interface ReviewAnnotation {
  key: string;
  diff_type: "added" | "removed" | "changed";
  primary_value: string;
  target_value: string;
  explanation: string;
}

export interface ReviewSettings {
  review_model: string;
  gemini_api_key_set: boolean;
}

export interface ReviewResult {
  target_profile_id: string;
  target_profile_name: string;
  annotations: ReviewAnnotation[];
  error: string | null;
}

export interface ReviewRunResponse {
  reviews: ReviewResult[];
}
