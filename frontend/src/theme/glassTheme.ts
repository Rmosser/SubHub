import { useSyncExternalStore } from "react";
import { applyMode, Mode } from "@cloudscape-design/global-styles";

// 两个主题：清透（浅色）与烟熏（深色）。默认跟随系统，可手动切换并记住。
// 手动选择写在 <html data-glass-theme>；跟随系统时不写，由 prefers-color-scheme 决定。
export type ThemePreference = "system" | "light" | "dark";

const STORAGE_KEY = "subhub.glass-theme";
const listeners = new Set<() => void>();
let preference: ThemePreference = "system";

function readStored(): ThemePreference {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

const darkQuery = () => window.matchMedia("(prefers-color-scheme: dark)");

export function isDarkEffective(pref: ThemePreference = preference) {
  return pref === "system" ? darkQuery().matches : pref === "dark";
}

function apply() {
  const root = document.documentElement;
  if (preference === "system") delete root.dataset.glassTheme;
  else root.dataset.glassTheme = preference;
  applyMode(isDarkEffective() ? Mode.Dark : Mode.Light);
  listeners.forEach((fn) => fn());
}

export function initThemePreference() {
  preference = readStored();
  apply();
  darkQuery().addEventListener("change", () => { if (preference === "system") apply(); });
}

export function setThemePreference(next: ThemePreference) {
  preference = next;
  try {
    if (next === "system") window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // 存储不可用时只在本次会话生效
  }
  apply();
}

const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };

export function useThemePreference() {
  const pref = useSyncExternalStore(subscribe, () => preference, () => "system" as ThemePreference);
  return [pref, setThemePreference] as const;
}

export function useEffectiveDark() {
  return useSyncExternalStore(subscribe, () => isDarkEffective(), () => false);
}
