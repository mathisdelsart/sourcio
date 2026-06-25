"use client";

import { useT } from "@/lib/i18n";

const CHIP_KEYS = ["hero.chip.grounded", "hero.chip.cited", "hero.chip.refuses"] as const;

/**
 * Concise landing header: product name, one-line value proposition, and a small
 * row of feature chips. Sober by design and collapses cleanly on small screens.
 */
export function Hero() {
  const { t } = useT();
  return (
    <section
      aria-labelledby="hero-heading"
      className="rounded-2xl border border-zinc-200 bg-white px-5 py-6 shadow-card dark:border-zinc-800 dark:bg-zinc-900 sm:px-7 sm:py-8"
    >
      <h1
        id="hero-heading"
        className="text-balance text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-2xl"
      >
        {t("hero.title")}
      </h1>
      <p className="mt-2 max-w-xl text-pretty text-sm leading-relaxed text-zinc-600 dark:text-zinc-300 sm:text-[15px]">
        {t("hero.description")}
      </p>
      <ul className="mt-4 flex flex-wrap gap-2" aria-label={t("hero.principles")}>
        {CHIP_KEYS.map((chip) => (
          <li
            key={chip}
            className="inline-flex items-center gap-1.5 rounded-full border border-zinc-200 bg-zinc-50 px-3 py-1 text-xs font-medium text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
          >
            <span
              aria-hidden
              className="h-1.5 w-1.5 rounded-full bg-indigo-500 dark:bg-indigo-400"
            />
            {t(chip)}
          </li>
        ))}
      </ul>
    </section>
  );
}
