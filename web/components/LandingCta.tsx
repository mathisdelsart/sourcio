"use client";

import { useT } from "@/lib/i18n";
import { scrollToId } from "@/lib/scroll";

/** Closing call-to-action that scrolls down into the tool. */
export function LandingCta({ targetId = "tool" }: { targetId?: string }) {
  const { t } = useT();
  return (
    <section
      aria-labelledby="landing-cta-heading"
      className="rounded-2xl border border-zinc-200 bg-zinc-900 px-6 py-10 text-center shadow-card dark:border-zinc-700 dark:bg-zinc-100 sm:px-10 sm:py-12"
    >
      <h2
        id="landing-cta-heading"
        className="mx-auto max-w-xl text-balance text-xl font-semibold tracking-tight text-white dark:text-zinc-900 sm:text-2xl"
      >
        {t("landing.cta.title")}
      </h2>
      <p className="mx-auto mt-3 max-w-lg text-pretty text-sm leading-relaxed text-zinc-300 dark:text-zinc-600">
        {t("landing.cta.body")}
      </p>
      <div className="mt-6 flex justify-center">
        <button
          type="button"
          onClick={() => scrollToId(targetId)}
          aria-label={t("hero.ctaAria")}
          className="inline-flex items-center justify-center rounded-lg bg-indigo-500 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-400 active:bg-indigo-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900 dark:focus-visible:ring-offset-zinc-100"
        >
          {t("landing.cta.button")}
        </button>
      </div>
    </section>
  );
}
