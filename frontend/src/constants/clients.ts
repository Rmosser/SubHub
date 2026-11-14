import type { SelectProps } from "@cloudscape-design/components";

export const CLIENT_TARGETS = ["surge", "clash", "shadowrocket"] as const;
export type ClientTarget = (typeof CLIENT_TARGETS)[number];

export const CLIENT_TARGET_OPTIONS: SelectProps.Option[] = [
  { value: "surge", label: "Surge" },
  { value: "clash", label: "Clash" },
  { value: "shadowrocket", label: "Shadowrocket" },
];
