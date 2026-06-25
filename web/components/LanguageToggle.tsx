"use client";

import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

/**
 * Header English/French toggle. Mirrors {@link ThemeToggle}'s styling and sizing;
 * shows the active locale code and flips it on click. The active locale is
 * resolved and persisted by the i18n provider, so this control stays in sync.
 */
export function LanguageToggle() {
  const { locale, setLocale, t } = useT();
  const next = locale === "en" ? "fr" : "en";
  const label = next === "fr" ? t("lang.switchToFrench") : t("lang.switchToEnglish");

  return (
    <button
      type="button"
      onClick={() => setLocale(next)}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex h-9 min-w-9 items-center justify-center rounded-lg border px-2 text-xs font-semibold uppercase text-zinc-600",
        "border-zinc-200 bg-white transition-colors hover:bg-zinc-50",
        "dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2",
        "dark:focus-visible:ring-offset-zinc-950",
      )}
    >
      <span className="tabular-nums">{locale}</span>
      <span className="sr-only">{t("lang.label")}</span>
    </button>
  );
}
