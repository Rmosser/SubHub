export interface ApiListResponse<T> {
  items: T[];
}

export interface ApiItemResponse<T> {
  item: T | null;
}

export type Locale = "zh-CN" | "en-US";
