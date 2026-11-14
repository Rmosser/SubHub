import { getLocale } from "@/i18n/translations";

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString(getLocale(), { hour12: false });
  } catch {
    return String(value);
  }
}

export function formatBool(value: boolean): string {
  return value ? (getLocale() === "en-US" ? "Yes" : "是") : (getLocale() === "en-US" ? "No" : "否");
}

const RELATIVE_STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600], ["month", 30 * 24 * 3600], ["week", 7 * 24 * 3600],
  ["day", 24 * 3600], ["hour", 3600], ["minute", 60],
];

// 「2 分钟前」「7 个月前」：只取最大的一个单位，一分钟内算「现在」。
export function formatRelativeTime(value: string | null | undefined, now: number = Date.now(), locale: string = getLocale()): string {
  if (!value) return "";
  const at = new Date(value).getTime();
  if (!Number.isFinite(at)) return "";
  const seconds = Math.round((at - now) / 1000);
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, size] of RELATIVE_STEPS) {
    if (Math.abs(seconds) >= size) return format.format(Math.trunc(seconds / size), unit);
  }
  return format.format(0, "second");
}
