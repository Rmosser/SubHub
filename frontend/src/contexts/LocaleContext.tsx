import React, { createContext, useContext } from "react";
import type { Locale } from "@/types/common";
import { getLocale, setLocale, t, tx, initLocale } from "@/i18n/translations";

interface LocaleContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
  tx: (text: string) => string;
}

const LocaleContext = createContext<LocaleContextValue>({
  locale: "zh-CN",
  setLocale: () => {},
  t,
  tx,
});

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const locale = initLocale();

  return (
    <LocaleContext.Provider value={{ locale, setLocale, t, tx }}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale() {
  return useContext(LocaleContext);
}

export { getLocale };
