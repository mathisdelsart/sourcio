"use client";

import { useT } from "@/lib/i18n";
import { scrollToId } from "@/lib/scroll";

const CHIP_KEYS = ["hero.chip.grounded", "hero.chip.cited", "hero.chip.refuses"] as const;

/** Arrow-down glyph for the primary call-to-action. */
function ArrowDown() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 5v14M19 12l-7 7-7-7" />
    </svg>
  );
}

/**
 * Landing hero: product name, a strong value proposition, a supporting line, a
 * primary CTA that smooth-scrolls to the tool, and the trust chips. Sober by
 * design — generous whitespace, no loud gradients.
 */
export function Hero({ targetId = "tool" }: { targetId?: string }) {
  const { t } = useT();
  return (
    <section
      aria-labelledby="hero-heading"
      className="rounded-2xl border border-zinc-200 bg-white px-6 py-12 text-center shadow-card dark:border-zinc-800 dark:bg-zinc-900 sm:px-10 sm:py-16"
    >
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-600 dark:text-indigo-400">
        {t("app.name")}
      </p>
      <h1
        id="hero-heading"
        className="mx-auto mt-4 max-w-2xl text-balance text-2xl font-semibold leading-tight tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-4xl"
      >
        {t("hero.valueProp")}
      </h1>
      <p className="mx-auto mt-4 max-w-xl text-pretty text-sm leading-relaxed text-zinc-600 dark:text-zinc-300 sm:text-base">
        {t("hero.description")}
      </p>

      <div className="mt-7 flex justify-center">
        <button
          type="button"
          onClick={() => scrollToId(targetId)}
          aria-label={t("hero.ctaAria")}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-700 active:bg-indigo-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 dark:bg-indigo-500 dark:hover:bg-indigo-400 dark:active:bg-indigo-600 dark:focus-visible:ring-offset-zinc-900"
        >
          {t("hero.cta")}
          <ArrowDown />
        </button>
      </div>

      <ul
        className="mt-8 flex flex-wrap justify-center gap-2"
        aria-label={t("hero.principles")}
      >
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
