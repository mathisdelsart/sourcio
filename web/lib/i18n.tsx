"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { KEYS, readLocal, writeLocal } from "@/lib/storage";
import { en } from "@/lib/locales/en";
import type { TranslationKey } from "@/lib/locales/en";
import { fr } from "@/lib/locales/fr";
import { nl } from "@/lib/locales/nl";

/** Supported UI locales. UI strings only — never API-returned content. */
export type Locale = "en" | "fr" | "nl";

/** Re-exported so consumers keep importing the key type from `@/lib/i18n`. */
export type { TranslationKey };

const DICTIONARIES: Record<Locale, Record<TranslationKey, string>> = { en, fr, nl };

/** Pick a sensible default locale from the browser language (fr/nl → match, else en). */
function detectLocale(): Locale {
  if (typeof navigator === "undefined") return "en";
  const lang = (navigator.language || "").toLowerCase();
  if (lang.startsWith("fr")) return "fr";
  if (lang.startsWith("nl")) return "nl";
  return "en";
}

/** Resolve the persisted locale, falling back to browser detection. */
function resolveLocale(): Locale {
  const stored = readLocal(KEYS.locale);
  if (stored === "en" || stored === "fr" || stored === "nl") return stored;
  return detectLocale();
}

/**
 * Translate `key` for `locale`, substituting `{name}` placeholders from `vars`.
 * Missing keys fall back to the English value, then to the raw id — never throws.
 */
function translate(
  locale: Locale,
  key: TranslationKey,
  vars?: Record<string, string | number>,
): string {
  const dict = DICTIONARIES[locale] ?? en;
  let value: string = dict[key] ?? en[key] ?? key;
  if (vars) {
    for (const [name, replacement] of Object.entries(vars)) {
      value = value.replaceAll(`{${name}}`, String(replacement));
    }
  }
  return value;
}

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

/**
 * Provides the active locale + translator. The initial render uses the default
 * (`en`) so SSR and the first client paint match; the persisted/detected locale
 * is resolved in an effect on mount, mirroring the theme's no-flash approach.
 */
export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");

  useEffect(() => {
    setLocaleState(resolveLocale());
  }, []);

  // Keep <html lang> in sync for accessibility once a locale is resolved.
  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale;
    }
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    writeLocal(KEYS.locale, next);
  }, []);

  const value = useMemo<I18nContextValue>(
    () => ({
      locale,
      setLocale,
      t: (key, vars) => translate(locale, key, vars),
    }),
    [locale, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

/**
 * Access the translator and locale. Falls back to English with no persistence
 * when used outside the provider, so components never crash in isolation.
 */
export function useT(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (ctx) return ctx;
  return {
    locale: "en",
    setLocale: () => {},
    t: (key, vars) => translate("en", key, vars),
  };
}

// Known backend error messages (English constants from `core/errors.py` and
// `core/documents.py`) matched by a stable fragment, so they can be shown in the
// UI language. Anything unmatched falls back to the raw message unchanged.
const _BACKEND_ERROR_MAP: { match: string; key: TranslationKey }[] = [
  { match: "too large for the free model", key: "err.freeTierCapacity" },
  { match: "hit its provider's rate", key: "err.ownKeyCapacity" },
  { match: "scanned or image-based PDF", key: "err.scannedNeedsKey" },
  { match: "API key was rejected", key: "err.keyRejected" },
  { match: "Unsupported file type", key: "err.unsupportedFile" },
];

/**
 * Translate a known backend error message into the UI language. The API emits
 * these as English strings (API-key / capacity / unsupported-file errors); this
 * maps them to the localized copy, leaving any unrecognized message untouched.
 */
export function localizeError(
  t: I18nContextValue["t"],
  message: string | null | undefined,
): string {
  if (!message) return message ?? "";
  for (const { match, key } of _BACKEND_ERROR_MAP) {
    if (message.includes(match)) return t(key);
  }
  return message;
}
