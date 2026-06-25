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
      className="relative overflow-hidden rounded-3xl border border-zinc-200 bg-gradient-to-b from-indigo-50 to-white px-6 py-20 text-center dark:border-zinc-800 dark:from-indigo-950/30 dark:to-zinc-950 sm:px-10 sm:py-24"
    >
      <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
        {t("app.name")}
      </p>
      <h1
        id="hero-heading"
        className="mx-auto mt-4 max-w-3xl text-balance text-4xl font-bold leading-[1.1] tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-5xl lg:text-6xl"
      >
        {t("hero.valueProp")}
      </h1>
      <p className="mx-auto mt-5 max-w-2xl text-pretty text-base leading-relaxed text-zinc-600 dark:text-zinc-300 sm:text-lg">
        {t("hero.description")}
      </p>

      <div className="mt-9 flex justify-center">
        <button
          type="button"
          onClick={() => scrollToId(targetId)}
          aria-label={t("hero.ctaAria")}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-6 py-3 text-base font-medium text-white shadow-sm transition-colors hover:bg-indigo-500 active:bg-indigo-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-zinc-950"
        >
          {t("hero.cta")}
          <ArrowDown />
        </button>
      </div>

      <ul
        className="mt-10 flex flex-wrap justify-center gap-2.5"
        aria-label={t("hero.principles")}
      >
        {CHIP_KEYS.map((chip) => (
          <li
            key={chip}
            className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-3 py-1 text-sm font-medium text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
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
